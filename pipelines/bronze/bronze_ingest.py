"""Bronze layer: land raw source feeds in ADLS as-is.

Bronze is a faithful copy of the source. We do not change column names, we
do not deduplicate, we do not enforce types. We *do*:

* attach ingest metadata: `_ingest_ts`, `_source_file`, `_run_id`.
* convert to Parquet (Snappy) for Spark friendliness.
* partition by `_ingest_date` so re-ingests don't overwrite older deliveries.

Designed to run either inside Databricks (where Spark is provided) or on a
local laptop using the bundled PySpark dependency. Operate it as:

    python -m pipelines.bronze.bronze_ingest \
        --source synthea --input data/raw/synthea --layer-root data/bronze
    python -m pipelines.bronze.bronze_ingest \
        --source claims  --input data/raw/claims.jsonl --layer-root data/bronze
    python -m pipelines.bronze.bronze_ingest \
        --source providers --input data/raw/providers.json --layer-root data/bronze

In production the layer root is an ADLS Gen2 abfss:// URI; pass it via
--layer-root abfss://bronze@<account>.dfs.core.windows.net/

The script is intentionally single-process. ADF triggers it once per source
once a day; the heavy parallelism happens inside Spark.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T


def _spark(app_name: str = "bronze_ingest") -> SparkSession:
    return (
        SparkSession.builder
        .appName(app_name)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.compression.codec", "snappy")
        .getOrCreate()
    )


def _attach_metadata(df: DataFrame, source_path: str, run_id: str) -> DataFrame:
    return (
        df.withColumn("_ingest_ts", F.current_timestamp())
          .withColumn("_ingest_date", F.to_date(F.current_timestamp()))
          .withColumn("_source_file", F.lit(source_path))
          .withColumn("_run_id", F.lit(run_id))
    )


def _ingest_synthea(spark: SparkSession, input_dir: Path, layer_root: str, run_id: str) -> dict[str, int]:
    """Each Synthea CSV becomes a separate Bronze table."""
    csvs = sorted(input_dir.glob("*.csv"))
    if not csvs:
        raise SystemExit(f"No CSVs found in {input_dir}.")

    counts: dict[str, int] = {}
    for csv in csvs:
        table = f"synthea_{csv.stem.lower()}"
        df = (
            spark.read
                 .option("header", True)
                 .option("inferSchema", True)
                 .option("multiLine", True)
                 .option("escape", '"')
                 .csv(str(csv))
        )
        df = _attach_metadata(df, str(csv), run_id)
        target = f"{layer_root}/{table}"
        (
            df.write
              .mode("append")
              .partitionBy("_ingest_date")
              .parquet(target)
        )
        counts[table] = df.count()
        print(f"  {table:30s} -> {target}  ({counts[table]:,} rows)", file=sys.stderr)
    return counts


def _ingest_claims(spark: SparkSession, input_path: Path, layer_root: str, run_id: str) -> dict[str, int]:
    df = spark.read.json(str(input_path))
    df = _attach_metadata(df, str(input_path), run_id)
    target = f"{layer_root}/claims_raw"
    df.write.mode("append").partitionBy("_ingest_date").parquet(target)
    n = df.count()
    print(f"  claims_raw -> {target}  ({n:,} rows)", file=sys.stderr)
    return {"claims_raw": n}


def _ingest_providers(spark: SparkSession, input_path: Path, layer_root: str, run_id: str) -> dict[str, int]:
    df = spark.read.option("multiLine", True).json(str(input_path))
    df = _attach_metadata(df, str(input_path), run_id)
    target = f"{layer_root}/provider_registry"
    df.write.mode("overwrite").parquet(target)
    n = df.count()
    print(f"  provider_registry -> {target}  ({n:,} rows)", file=sys.stderr)
    return {"provider_registry": n}


def _ingest_vitals(spark: SparkSession, input_path: Path, layer_root: str, run_id: str) -> dict[str, int]:
    """Used in tests; the production stream goes through Bronze auto-loader.
    See pipelines/streaming/vitals_streaming.py for the live path.
    """
    schema = T.StructType([
        T.StructField("event_id", T.StringType()),
        T.StructField("event_time", T.StringType()),
        T.StructField("device_id", T.StringType()),
        T.StructField("patient_id", T.StringType()),
        T.StructField("hospital_code", T.StringType()),
        T.StructField("bed_number", T.StringType()),
        T.StructField("heart_rate_bpm", T.DoubleType()),
        T.StructField("spo2_pct", T.DoubleType()),
        T.StructField("systolic_bp", T.DoubleType()),
        T.StructField("diastolic_bp", T.DoubleType()),
        T.StructField("respiratory_rate", T.DoubleType()),
        T.StructField("temperature_c", T.DoubleType()),
        T.StructField("anomaly_flag", T.BooleanType()),
        T.StructField("anomaly_kind", T.StringType()),
    ])
    df = spark.read.schema(schema).json(str(input_path))
    df = _attach_metadata(df, str(input_path), run_id)
    target = f"{layer_root}/vitals_stream"
    df.write.mode("append").partitionBy("_ingest_date").parquet(target)
    n = df.count()
    print(f"  vitals_stream -> {target}  ({n:,} rows)", file=sys.stderr)
    return {"vitals_stream": n}


SOURCES = {
    "synthea": _ingest_synthea,
    "claims": _ingest_claims,
    "providers": _ingest_providers,
    "vitals": _ingest_vitals,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bronze layer ingest.")
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--layer-root", required=True,
                        help="Bronze root path: local dir or abfss:// URI.")
    parser.add_argument("--run-id", default=None,
                        help="Optional run id; defaults to a generated UUID.")
    args = parser.parse_args(argv)

    run_id = args.run_id or f"bronze-{dt.datetime.utcnow():%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    spark = _spark(f"bronze_ingest:{args.source}")
    try:
        n = SOURCES[args.source](spark, args.input, args.layer_root.rstrip("/"), run_id)
        print(f"Bronze ingest complete: {n}", file=sys.stderr)
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
