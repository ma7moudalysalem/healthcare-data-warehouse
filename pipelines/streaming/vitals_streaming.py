"""Spark Structured Streaming: vitals stream -> Bronze + Silver Delta tables.

Reads from Azure Event Hubs (or a local Kafka shim for tests), parses the
JSON payload, applies anomaly detection rules, and writes two Delta tables:

* `bronze/vitals_stream`     - raw appended events (1:1 with input).
* `silver/vitals_minute`     - minute-level aggregates with anomaly counts.

The Gold mirror (`fact_vital_signs_minute`) is loaded from
`silver/vitals_minute` via `COPY INTO` once an hour by the ADF stream
ingestion pipeline. We don't write directly to Synapse from the streaming
job because Synapse's per-row latency would back-pressure the stream.

Run locally against stdout-fed events for testing:

    # terminal 1
    python -m src.generators.simulate_vitals --rate 5 --devices 5 --stdout > /tmp/vitals.jsonl

    # terminal 2
    python -m pipelines.streaming.vitals_streaming \
        --source file --input /tmp/vitals.jsonl \
        --bronze-root data/bronze --silver-root data/silver \
        --checkpoint-root data/checkpoints \
        --trigger-seconds 30
"""
from __future__ import annotations

import argparse
import os
import sys

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T


VITAL_SCHEMA = T.StructType([
    T.StructField("event_id",          T.StringType()),
    T.StructField("event_time",        T.StringType()),
    T.StructField("device_id",         T.StringType()),
    T.StructField("patient_id",        T.StringType()),
    T.StructField("hospital_code",     T.StringType()),
    T.StructField("bed_number",        T.StringType()),
    T.StructField("heart_rate_bpm",    T.DoubleType()),
    T.StructField("spo2_pct",          T.DoubleType()),
    T.StructField("systolic_bp",       T.DoubleType()),
    T.StructField("diastolic_bp",      T.DoubleType()),
    T.StructField("respiratory_rate",  T.DoubleType()),
    T.StructField("temperature_c",     T.DoubleType()),
    T.StructField("anomaly_flag",      T.BooleanType()),
    T.StructField("anomaly_kind",      T.StringType()),
])

# Detection thresholds. Stream-level anomaly_flag from the simulator is
# advisory only; we re-derive these so a real device feed (which won't
# carry an anomaly_flag) still gets flagged.
HR_HIGH = 130.0
HR_LOW  = 45.0
SPO2_LOW = 88.0
SBP_HIGH = 180.0
TEMP_HIGH = 39.5


def _spark() -> SparkSession:
    return (
        SparkSession.builder
        .appName("vitals_streaming")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.jars.packages", "io.delta:delta-spark_2.12:3.0.0")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.streaming.schemaInference", "true")
        .getOrCreate()
    )


def _read_source(spark: SparkSession, source: str, input_path: str | None) -> DataFrame:
    if source == "eventhub":
        conn = os.environ["EVENT_HUB_CONNECTION_STRING"]
        # In Databricks the recommended connector is the
        # `azure-eventhubs-spark` package. The config below matches
        # https://learn.microsoft.com/azure/event-hubs/event-hubs-spark-connector
        ehConf = {
            "eventhubs.connectionString": spark._jvm.org.apache.spark.eventhubs.EventHubsUtils
                                                  .encrypt(conn),
            "eventhubs.consumerGroup": os.environ.get("EVENT_HUB_CONSUMER_GROUP", "$Default"),
            "maxEventsPerTrigger": "10000",
        }
        raw = spark.readStream.format("eventhubs").options(**ehConf).load()
        return raw.select(F.col("body").cast("string").alias("body"), F.col("enqueuedTime"))
    elif source == "file":
        # Used for local tests. The simulator can be pointed at --stdout, redirected
        # into a folder; Spark's autoLoader picks up new files.
        if not input_path:
            raise SystemExit("file source requires --input")
        raw = (
            spark.readStream
                 .format("text")
                 .option("maxFilesPerTrigger", 1)
                 .load(input_path)
                 .select(F.col("value").alias("body"))
                 .withColumn("enqueuedTime", F.current_timestamp())
        )
        return raw
    else:
        raise SystemExit(f"unknown source: {source}")


def _parse(raw: DataFrame) -> DataFrame:
    return (
        raw.select(F.from_json(F.col("body"), VITAL_SCHEMA).alias("e"), "enqueuedTime")
           .select(
               "e.*",
               F.to_timestamp("e.event_time").alias("event_ts"),
               F.col("enqueuedTime").alias("ingest_ts"),
           )
    )


def _flag_anomalies(parsed: DataFrame) -> DataFrame:
    rule = (
        (F.col("heart_rate_bpm") > HR_HIGH)
        | (F.col("heart_rate_bpm") < HR_LOW)
        | (F.col("spo2_pct") < SPO2_LOW)
        | (F.col("systolic_bp") > SBP_HIGH)
        | (F.col("temperature_c") > TEMP_HIGH)
    )
    kind = (
        F.when(F.col("heart_rate_bpm") > HR_HIGH, F.lit("tachycardia"))
         .when(F.col("heart_rate_bpm") < HR_LOW,  F.lit("bradycardia"))
         .when(F.col("spo2_pct") < SPO2_LOW,      F.lit("hypoxia"))
         .when(F.col("systolic_bp") > SBP_HIGH,   F.lit("hypertension"))
         .when(F.col("temperature_c") > TEMP_HIGH, F.lit("fever"))
         .otherwise(F.lit(None))
    )
    return (
        parsed.withColumn("derived_anomaly", rule.cast("boolean"))
              .withColumn("derived_anomaly_kind", kind)
    )


def _write_bronze(stream: DataFrame, root: str, checkpoint_root: str, trigger_s: int) -> None:
    out = (
        stream.withColumn("_ingest_date", F.to_date("ingest_ts"))
              .writeStream
              .format("delta")
              .outputMode("append")
              .partitionBy("_ingest_date")
              .option("checkpointLocation", f"{checkpoint_root}/bronze_vitals")
              .trigger(processingTime=f"{trigger_s} seconds")
              .start(f"{root}/vitals_stream")
    )
    print(f"Bronze stream started: {out.id}", file=sys.stderr)


def _write_silver_minute(stream: DataFrame, root: str, checkpoint_root: str, trigger_s: int) -> None:
    """One-minute tumbling aggregates with watermark for late events."""
    agg = (
        stream
            .withWatermark("event_ts", "5 minutes")
            .groupBy(
                F.window("event_ts", "1 minute").alias("w"),
                "device_id", "patient_id", "hospital_code", "bed_number",
            )
            .agg(
                F.count(F.lit(1)).alias("sample_count"),
                F.avg("heart_rate_bpm").cast("decimal(6,2)").alias("heart_rate_avg"),
                F.max("heart_rate_bpm").cast("decimal(6,2)").alias("heart_rate_max"),
                F.min("heart_rate_bpm").cast("decimal(6,2)").alias("heart_rate_min"),
                F.avg("spo2_pct").cast("decimal(5,2)").alias("spo2_avg"),
                F.min("spo2_pct").cast("decimal(5,2)").alias("spo2_min"),
                F.avg("systolic_bp").cast("decimal(6,2)").alias("systolic_avg"),
                F.avg("diastolic_bp").cast("decimal(6,2)").alias("diastolic_avg"),
                F.avg("respiratory_rate").cast("decimal(5,2)").alias("respiratory_rate_avg"),
                F.avg("temperature_c").cast("decimal(5,2)").alias("temperature_c_avg"),
                F.max("temperature_c").cast("decimal(5,2)").alias("temperature_c_max"),
                F.sum(F.when(F.col("derived_anomaly"), 1).otherwise(0)).alias("anomaly_event_count"),
                # Mode of anomaly kind in the minute. Approximate with first non-null.
                F.first("derived_anomaly_kind", ignorenulls=True).alias("primary_anomaly_kind"),
            )
            .select(
                F.col("w.start").alias("minute_start_utc"),
                F.col("w.end").alias("minute_end_utc"),
                F.date_format(F.col("w.start"), "yyyyMMdd").cast("int").alias("date_sk"),
                "device_id", "patient_id", "hospital_code", "bed_number",
                "sample_count",
                "heart_rate_avg", "heart_rate_max", "heart_rate_min",
                "spo2_avg", "spo2_min",
                "systolic_avg", "diastolic_avg",
                "respiratory_rate_avg",
                "temperature_c_avg", "temperature_c_max",
                "anomaly_event_count", "primary_anomaly_kind",
            )
    )
    out = (
        agg.writeStream
           .format("delta")
           .outputMode("append")
           .partitionBy("date_sk")
           .option("checkpointLocation", f"{checkpoint_root}/silver_vitals_minute")
           .trigger(processingTime=f"{trigger_s} seconds")
           .start(f"{root}/vitals_minute")
    )
    print(f"Silver minute stream started: {out.id}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["eventhub", "file"], default="eventhub")
    parser.add_argument("--input", default=None,
                        help="File source: directory of newline-delimited JSON.")
    parser.add_argument("--bronze-root", required=True)
    parser.add_argument("--silver-root", required=True)
    parser.add_argument("--checkpoint-root", required=True)
    parser.add_argument("--trigger-seconds", type=int, default=30)
    parser.add_argument("--once", action="store_true",
                        help="Use trigger=once (test mode).")
    args = parser.parse_args(argv)

    spark = _spark()
    try:
        raw = _read_source(spark, args.source, args.input)
        parsed = _parse(raw)
        flagged = _flag_anomalies(parsed)

        _write_bronze(flagged, args.bronze_root.rstrip("/"),
                      args.checkpoint_root.rstrip("/"),
                      args.trigger_seconds)
        _write_silver_minute(flagged, args.silver_root.rstrip("/"),
                             args.checkpoint_root.rstrip("/"),
                             args.trigger_seconds)

        spark.streams.awaitAnyTermination()
    finally:
        for q in spark.streams.active:
            q.stop()
        spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
