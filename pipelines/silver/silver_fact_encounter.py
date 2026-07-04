"""Silver: Synthea encounters -> typed, deduped, with is_readmission_30d.

The 30-day readmission flag is computed here once so the Gold load and the
analytical queries don't have to re-derive it. We use a window over the
patient's encounter history sorted by start_at, then check the previous
inpatient discharge.
"""
from __future__ import annotations

import argparse

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from pipelines.logging_config import get_logger
from .silver_common import split_by_rule, write_delta, write_quarantine

log = get_logger(__name__)


def _spark() -> SparkSession:
    return (
        SparkSession.builder
        .appName("silver_fact_encounter")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.jars.packages", "io.delta:delta-spark_2.12:3.0.0")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )


# Synthea encounter classes -> our normalised values
CLASS_PAIRS = [
    ("ambulatory",  "ambulatory"),
    ("wellness",    "wellness"),
    ("emergency",   "emergency"),
    ("inpatient",   "inpatient"),
    ("outpatient",  "ambulatory"),
    ("urgentcare",  "emergency"),
    ("snf",         "inpatient"),
    ("home",        "ambulatory"),
    ("virtual",     "ambulatory"),
]


def _class_map():
    # Built lazily (not at import time) because F.lit() needs an active
    # SparkContext, which doesn't exist until _spark() has run inside main().
    return F.create_map([F.lit(x) for pair in CLASS_PAIRS for x in pair])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-root", required=True)
    parser.add_argument("--silver-root", required=True)
    parser.add_argument("--quarantine-root", required=True)
    args = parser.parse_args(argv)

    spark = _spark()
    try:
        bronze_path = f"{args.bronze_root.rstrip('/')}/synthea_encounters"
        df = spark.read.parquet(bronze_path)
        log.info("loaded from bronze",
                 extra={"object_name": "fact_encounter", "rows_read": df.count(), "layer": "silver"})

        df = (
            df.select(
                F.col("Id").alias("encounter_bk"),
                F.col("PATIENT").alias("patient_bk"),
                F.col("PROVIDER").alias("provider_bk"),
                F.col("ORGANIZATION").alias("organization_bk"),
                F.coalesce(_class_map()[F.lower(F.col("ENCOUNTERCLASS"))],
                           F.lit("ambulatory")).alias("encounter_class"),
                F.col("DESCRIPTION").alias("encounter_type"),
                F.col("REASONCODE").alias("reason_code"),
                F.col("REASONDESCRIPTION").alias("reason_description"),
                F.to_timestamp("START").alias("start_at"),
                F.to_timestamp("STOP").alias("end_at"),
                F.col("BASE_ENCOUNTER_COST").cast("decimal(12,2)").alias("base_cost_usd"),
                F.col("TOTAL_CLAIM_COST").cast("decimal(12,2)").alias("total_cost_usd"),
                F.col("PAYER_COVERAGE").cast("decimal(12,2)").alias("payer_coverage_usd"),
                F.col("_ingest_ts"),
            )
        )

        # --- Derivations ---
        df = (
            df.withColumn("length_of_stay_hours",
                          F.when(F.col("end_at").isNotNull(),
                                 (F.unix_timestamp("end_at") - F.unix_timestamp("start_at")) / 3600)
                           .cast("decimal(10,2)"))
              .withColumn("is_inpatient", (F.col("encounter_class") == "inpatient").cast("boolean"))
              .withColumn("is_emergency", (F.col("encounter_class") == "emergency").cast("boolean"))
              .withColumn("out_of_pocket_usd",
                          (F.coalesce("total_cost_usd", F.lit(0)) - F.coalesce("payer_coverage_usd", F.lit(0)))
                              .cast("decimal(12,2)"))
        )

        # --- 30-day readmission flag ---
        # Definition: an inpatient admission within 30 days after another inpatient
        # discharge for the same patient counts as a readmission.
        w_pat = Window.partitionBy("patient_bk").orderBy("start_at")
        df = (
            df.withColumn("_prev_inpatient_end",
                          F.lag(
                              F.when(F.col("is_inpatient"), F.col("end_at")).otherwise(F.lit(None))
                          ).over(w_pat))
              .withColumn(
                  "is_readmission_30d",
                  (F.col("is_inpatient") &
                   F.col("_prev_inpatient_end").isNotNull() &
                   ((F.unix_timestamp("start_at") - F.unix_timestamp("_prev_inpatient_end")) / 86400 <= 30)
                  ).cast("boolean"))
              .drop("_prev_inpatient_end")
        )

        # --- DQ rules ---
        rules = [
            ("encounter_id_present", F.col("encounter_bk").isNotNull()),
            ("patient_id_present",   F.col("patient_bk").isNotNull()),
            ("start_at_present",     F.col("start_at").isNotNull()),
            ("end_after_start",
                F.col("end_at").isNull() | (F.col("end_at") >= F.col("start_at"))),
            ("non_negative_cost",
                F.col("total_cost_usd").isNull() | (F.col("total_cost_usd") >= 0)),
        ]

        clean = df
        rejected_all = None
        for name, rule in rules:
            res = split_by_rule(clean, rule, name)
            res.report()
            clean = res.clean
            rejected_all = res.rejected if rejected_all is None else rejected_all.unionByName(res.rejected)

        # Dedupe by encounter_bk - latest ingest wins.
        w_enc = Window.partitionBy("encounter_bk").orderBy(F.col("_ingest_ts").desc())
        clean = (clean.withColumn("_rn", F.row_number().over(w_enc))
                       .where(F.col("_rn") == 1)
                       .drop("_rn"))

        silver_path = f"{args.silver_root.rstrip('/')}/fact_encounter"
        # Partition by start month to keep file counts reasonable.
        clean = clean.withColumn("start_year_month",
                                 F.date_format("start_at", "yyyy-MM"))
        write_delta(clean, silver_path, mode="overwrite", partition_by=["start_year_month"])
        log.info("wrote fact_encounter",
                 extra={"object_name": "fact_encounter", "rows_written": clean.count(), "layer": "silver"})

        if rejected_all is not None:
            quarantine_path = f"{args.quarantine_root.rstrip('/')}/fact_encounter"
            write_quarantine(rejected_all, quarantine_path)
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
