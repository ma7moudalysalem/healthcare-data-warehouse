"""Spark Structured Streaming: Event Hubs (Kafka) -> minute aggregates -> Azure SQL.

Reads the vital-signs stream from Azure Event Hubs via its Kafka-compatible
endpoint, tumbling-windows to 1-minute per device with anomaly detection, and
upserts each micro-batch into dw.fact_vital_signs_minute so the dashboard's
"Live Vital Signs" page reflects the live stream.

Env:
  EVENT_HUB_CONNECTION_STRING   namespace connection string ($ConnectionString auth)
  EVENT_HUB_BOOTSTRAP           <ns>.servicebus.windows.net:9093
  EVENT_HUB_NAME                topic (default vitals-stream)
  HCDW_SQL_SERVER/DB/USER/PASSWORD   Azure SQL sink
"""
from __future__ import annotations

import hashlib
import os

import pyodbc
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (BooleanType, DoubleType, StringType, StructField,
                               StructType, TimestampType)

EVENT_SCHEMA = StructType([
    StructField("event_time", TimestampType()),
    StructField("device_id", StringType()),
    StructField("patient_id", StringType()),
    StructField("hospital_code", StringType()),
    StructField("bed_number", StringType()),
    StructField("heart_rate_bpm", DoubleType()),
    StructField("spo2_pct", DoubleType()),
    StructField("systolic_bp", DoubleType()),
    StructField("diastolic_bp", DoubleType()),
    StructField("respiratory_rate", DoubleType()),
    StructField("temperature_c", DoubleType()),
    StructField("anomaly_flag", BooleanType()),
    StructField("anomaly_kind", StringType()),
])

# hospital_bk -> hospital_sk (matches pipelines/gold/seed_warehouse.py ordering)
HOSP_SK = {"HSP-CAI-01": 1, "HSP-CAI-02": 2, "HSP-GIZ-01": 3, "HSP-ALX-01": 4, "HSP-MNF-01": 5}
N_PATIENTS = 2000  # dim_patient surrogate range 1..N


def _sql_conn():
    cs = ("DRIVER={ODBC Driver 18 for SQL Server};"
          f"SERVER={os.environ['HCDW_SQL_SERVER']};DATABASE={os.environ['HCDW_SQL_DB']};"
          f"UID={os.environ['HCDW_SQL_USER']};PWD={os.environ['HCDW_SQL_PASSWORD']};"
          "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60")
    return pyodbc.connect(cs, autocommit=False)


def _patient_sk(device_id: str) -> int:
    return (int(hashlib.md5(device_id.encode()).hexdigest()[:12], 16) % N_PATIENTS) + 1


def _vital_sk(device_id: str, minute_iso: str) -> int:
    # 63-bit deterministic key, offset above the seeded 1..6000 range
    return 1_000_000 + int(hashlib.md5(f"{device_id}|{minute_iso}".encode()).hexdigest()[:15], 16) % (10**17)


def upsert_batch(batch_df, _epoch_id):
    rows = batch_df.collect()
    if not rows:
        return
    cn = _sql_conn()
    cur = cn.cursor()
    for r in rows:
        dev = r["device_id"]
        minute = r["minute_start_utc"]
        hsp_sk = HOSP_SK.get(r["hospital_code"], 1)
        pat_sk = _patient_sk(dev)
        vsk = _vital_sk(dev, minute.isoformat())
        date_sk = int(minute.strftime("%Y%m%d"))
        cur.execute("DELETE FROM dw.fact_vital_signs_minute WHERE device_id=? AND minute_start_utc=?",
                    dev, minute)
        cur.execute(
            "INSERT INTO dw.fact_vital_signs_minute (vital_sk, patient_sk, hospital_sk, device_id, "
            "bed_number, minute_start_utc, date_sk, sample_count, heart_rate_avg, heart_rate_max, "
            "heart_rate_min, spo2_avg, spo2_min, systolic_avg, diastolic_avg, respiratory_rate_avg, "
            "temperature_c_avg, temperature_c_max, anomaly_event_count, primary_anomaly_kind) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            vsk, pat_sk, hsp_sk, dev, r["bed_number"], minute, date_sk, r["sample_count"],
            r["hr_avg"], r["hr_max"], r["hr_min"], r["spo2_avg"], r["spo2_min"],
            r["sys_avg"], r["dia_avg"], r["rr_avg"], r["temp_avg"], r["temp_max"],
            r["anomaly_count"], r["anomaly_kind"])
    cn.commit()
    cn.close()
    print(f"[consumer] upserted {len(rows)} device-minutes", flush=True)


def main() -> int:
    eh_conn = os.environ["EVENT_HUB_CONNECTION_STRING"]
    bootstrap = os.environ["EVENT_HUB_BOOTSTRAP"]
    topic = os.environ.get("EVENT_HUB_NAME", "vitals-stream")

    spark = (SparkSession.builder.appName("vitals_eventhub_to_sql")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.jars.packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0")
             .config("spark.sql.shuffle.partitions", "2")
             .getOrCreate())
    spark.sparkContext.setLogLevel("WARN")

    jaas = (f'org.apache.kafka.common.security.plain.PlainLoginModule required '
            f'username="$ConnectionString" password="{eh_conn}";')

    raw = (spark.readStream.format("kafka")
           .option("kafka.bootstrap.servers", bootstrap)
           .option("subscribe", topic)
           .option("startingOffsets", "latest")
           .option("kafka.security.protocol", "SASL_SSL")
           .option("kafka.sasl.mechanism", "PLAIN")
           .option("kafka.sasl.jaas.config", jaas)
           .option("kafka.request.timeout.ms", "60000")
           .option("kafka.session.timeout.ms", "30000")
           .option("failOnDataLoss", "false")
           .load())

    events = (raw.select(F.from_json(F.col("value").cast("string"), EVENT_SCHEMA).alias("e"))
                 .select("e.*")
                 .withWatermark("event_time", "2 minutes"))

    agg = (events.groupBy(
                F.window("event_time", "1 minute").alias("w"),
                F.col("device_id"), F.col("hospital_code"), F.col("bed_number"))
             .agg(
                F.count("*").alias("sample_count"),
                F.round(F.avg("heart_rate_bpm"), 1).alias("hr_avg"),
                F.round(F.max("heart_rate_bpm"), 1).alias("hr_max"),
                F.round(F.min("heart_rate_bpm"), 1).alias("hr_min"),
                F.round(F.avg("spo2_pct"), 1).alias("spo2_avg"),
                F.round(F.min("spo2_pct"), 1).alias("spo2_min"),
                F.round(F.avg("systolic_bp"), 1).alias("sys_avg"),
                F.round(F.avg("diastolic_bp"), 1).alias("dia_avg"),
                F.round(F.avg("respiratory_rate"), 1).alias("rr_avg"),
                F.round(F.avg("temperature_c"), 2).alias("temp_avg"),
                F.round(F.max("temperature_c"), 2).alias("temp_max"),
                F.sum(F.col("anomaly_flag").cast("int")).alias("anomaly_count"),
                F.max("anomaly_kind").alias("anomaly_kind"))
             .select(
                F.col("w.start").alias("minute_start_utc"),
                "device_id", "hospital_code", "bed_number", "sample_count",
                "hr_avg", "hr_max", "hr_min", "spo2_avg", "spo2_min",
                "sys_avg", "dia_avg", "rr_avg", "temp_avg", "temp_max",
                "anomaly_count", "anomaly_kind"))

    query = (agg.writeStream
                .outputMode("update")
                .foreachBatch(upsert_batch)
                .option("checkpointLocation", "/tmp/hcdw_vitals_ckpt")
                .trigger(processingTime="15 seconds")
                .start())
    print("[consumer] streaming started", flush=True)
    query.awaitTermination()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
