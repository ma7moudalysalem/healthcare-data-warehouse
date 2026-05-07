"""Silver: Synthea patients -> typed, deduped, governorate-remapped table.

Reads bronze.synthea_patients (Parquet), enforces types, applies the
Egyptian governorate remap, computes age_band, and writes a Delta table at
silver.dim_patient. Rejected rows go to silver_quarantine/dim_patient/.

Run:
    python -m pipelines.silver.silver_dim_patient \
        --bronze-root data/bronze \
        --silver-root data/silver \
        --quarantine-root data/silver_quarantine
"""
from __future__ import annotations

import argparse

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

from pipelines.logging_config import get_logger
from .silver_common import age_band, remap_to_governorate, split_by_rule, write_delta, write_quarantine

log = get_logger(__name__)


SCHEMA = T.StructType([
    T.StructField("Id",           T.StringType(),    False),
    T.StructField("BIRTHDATE",    T.DateType(),      True),
    T.StructField("DEATHDATE",    T.DateType(),      True),
    T.StructField("FIRST",        T.StringType(),    True),
    T.StructField("LAST",         T.StringType(),    True),
    T.StructField("MARITAL",      T.StringType(),    True),
    T.StructField("RACE",         T.StringType(),    True),
    T.StructField("ETHNICITY",    T.StringType(),    True),
    T.StructField("GENDER",       T.StringType(),    True),
    T.StructField("ADDRESS",      T.StringType(),    True),
    T.StructField("CITY",         T.StringType(),    True),
    T.StructField("STATE",        T.StringType(),    True),
    T.StructField("ZIP",          T.StringType(),    True),
])


def _spark() -> SparkSession:
    return (
        SparkSession.builder
        .appName("silver_dim_patient")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.jars.packages", "io.delta:delta-spark_2.12:3.0.0")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-root", required=True)
    parser.add_argument("--silver-root", required=True)
    parser.add_argument("--quarantine-root", required=True)
    args = parser.parse_args(argv)

    spark = _spark()
    try:
        bronze_path = f"{args.bronze_root.rstrip('/')}/synthea_patients"
        # Use the Bronze schema as a type hint, but allow extra columns to pass through.
        df = spark.read.parquet(bronze_path)
        log.info("loaded from bronze", extra={"object_name": "dim_patient", "rows_read": df.count(), "layer": "silver"})

        # --- Type enforcement / column rename ---
        df = (
            df.select(
                F.col("Id").alias("patient_bk"),
                F.col("FIRST").alias("first_name"),
                F.col("LAST").alias("last_name"),
                F.to_date(F.col("BIRTHDATE")).alias("date_of_birth"),
                F.upper(F.coalesce(F.col("GENDER"), F.lit("U"))).substr(1, 1).alias("gender"),
                F.col("MARITAL").alias("marital_status"),
                F.col("RACE").alias("race"),
                F.col("ETHNICITY").alias("ethnicity"),
                F.col("ADDRESS").alias("address_line"),
                F.col("CITY").alias("city_src"),
                F.col("STATE").alias("state_src"),
                F.col("ZIP").alias("postal_code"),
                F.to_date(F.col("DEATHDATE")).alias("deceased_date"),
                F.col("_ingest_ts"),
            )
        )

        # --- Egyptian remap + derived columns ---
        df = (
            df.withColumn("governorate", remap_to_governorate(F.col("state_src")))
              .withColumn("city", F.col("governorate"))
              .withColumn("age_band", age_band(F.col("date_of_birth")))
              .withColumn("is_deceased", F.col("deceased_date").isNotNull())
              .drop("city_src", "state_src")
        )

        # --- DQ rules ---
        rules = [
            ("dob_present", F.col("date_of_birth").isNotNull()),
            ("gender_valid", F.col("gender").isin("M", "F", "U")),
            ("dob_not_in_future", F.col("date_of_birth") <= F.current_date()),
        ]

        clean = df
        rejected_all = None
        for name, rule in rules:
            res = split_by_rule(clean, rule, name)
            res.report()
            clean = res.clean
            rejected_all = res.rejected if rejected_all is None else rejected_all.unionByName(res.rejected)

        # --- Dedupe on patient_bk: keep the latest ingest ---
        from pyspark.sql.window import Window
        w = Window.partitionBy("patient_bk").orderBy(F.col("_ingest_ts").desc())
        clean = (
            clean.withColumn("_rn", F.row_number().over(w))
                 .where(F.col("_rn") == 1)
                 .drop("_rn")
        )

        silver_path = f"{args.silver_root.rstrip('/')}/dim_patient"
        write_delta(clean, silver_path, mode="overwrite")
        log.info("wrote dim_patient",
                 extra={"object_name": "dim_patient", "rows_written": clean.count(), "layer": "silver"})

        if rejected_all is not None:
            quarantine_path = f"{args.quarantine_root.rstrip('/')}/dim_patient"
            write_quarantine(rejected_all, quarantine_path)
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
