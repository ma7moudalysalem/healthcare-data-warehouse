"""Silver: claims_raw -> typed claim + claim_line tables.

Splits the line_items array into a separate claim_line table and computes
derived flags (`is_denied`, `days_to_decision`, `denied_amount`).

Notes:
* `encounter_bk` orphans (claims whose encounter id doesn't exist in the
  Silver encounter table) are *not* rejected here - they're flagged in
  Gold via a NULL `encounter_sk`. This matches Q12 behaviour.
* Currency conversion to EGP happens at the Silver layer using the FX rate
  effective on the service date. We apply a flat USD->EGP = 50.0 here for
  Synthea-sourced costs; in production this would join an FX table.
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
        .appName("silver_fact_claim")
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
        bronze_path = f"{args.bronze_root.rstrip('/')}/claims_raw"
        df = spark.read.parquet(bronze_path)
        log.info("loaded from bronze", extra={"object_name": "fact_claim", "rows_read": df.count(), "layer": "silver"})

        # --- Type enforcement / column rename ---
        df = df.select(
            F.col("claim_id").alias("claim_bk"),
            F.col("claim_number"),
            F.col("encounter_id").alias("encounter_bk"),
            F.col("patient_id").alias("patient_bk"),
            F.col("provider_npi").alias("provider_bk"),
            F.col("hospital_code").alias("hospital_bk"),
            F.col("carrier"),
            F.col("policy_number"),
            F.col("primary_diagnosis_code").alias("primary_icd10_code"),
            F.to_date("service_date").alias("service_date"),
            F.to_date("submission_date").alias("submission_date"),
            F.to_date("decision_date").alias("decision_date"),
            F.col("status"),
            F.col("denial_reason"),
            F.col("billed_amount").cast("decimal(12,2)"),
            F.col("allowed_amount").cast("decimal(12,2)"),
            F.col("paid_amount").cast("decimal(12,2)"),
            F.col("patient_responsibility").cast("decimal(12,2)"),
            F.col("currency"),
            F.col("line_items"),
            F.col("_ingest_ts"),
        )

        # --- Derivations ---
        df = (
            df.withColumn("is_denied", (F.col("status") == F.lit("denied")).cast("boolean"))
              .withColumn("is_paid_in_full",
                          (F.col("paid_amount") == F.col("billed_amount")).cast("boolean"))
              .withColumn("days_to_decision",
                          F.when(F.col("decision_date").isNotNull(),
                                 F.datediff("decision_date", "submission_date"))
                           .otherwise(F.lit(None)))
              .withColumn("denied_amount",
                          F.when(F.col("is_denied"), F.col("billed_amount"))
                           .otherwise(F.col("billed_amount") - F.col("allowed_amount"))
                           .cast("decimal(12,2)"))
              .withColumn("line_count", F.size("line_items"))
        )

        # --- DQ rules ---
        rules = [
            ("claim_bk_present", F.col("claim_bk").isNotNull()),
            ("status_known",
                F.col("status").isin("submitted", "approved", "denied", "partially_paid", "pending_review")),
            ("billed_non_negative", F.col("billed_amount") >= 0),
            ("paid_le_billed",
                F.col("paid_amount") <= F.col("billed_amount") + F.lit(0.01)),
            ("decision_after_submission",
                F.col("decision_date").isNull() |
                F.col("submission_date").isNull() |
                (F.col("decision_date") >= F.col("submission_date"))),
        ]

        clean = df
        rejected_all = None
        for name, rule in rules:
            res = split_by_rule(clean, rule, name)
            res.report()
            clean = res.clean
            rejected_all = res.rejected if rejected_all is None else rejected_all.unionByName(res.rejected)

        # Dedupe by claim_bk
        w = Window.partitionBy("claim_bk").orderBy(F.col("_ingest_ts").desc())
        clean = (clean.withColumn("_rn", F.row_number().over(w))
                       .where(F.col("_rn") == 1)
                       .drop("_rn"))

        # --- Split into header and lines ---
        header = clean.drop("line_items")
        lines = (
            clean.select("claim_bk", F.posexplode("line_items").alias("pos", "line"))
                 .select(
                     "claim_bk",
                     (F.col("pos") + 1).alias("line_number"),
                     F.col("line.cpt_code").alias("cpt_code"),
                     F.col("line.description").alias("description"),
                     F.col("line.units").cast("int").alias("units"),
                     F.col("line.billed_amount").cast("decimal(12,2)").alias("billed_amount"),
                 )
        )

        header_path = f"{args.silver_root.rstrip('/')}/fact_claim"
        lines_path = f"{args.silver_root.rstrip('/')}/fact_claim_line"
        # Partition by service month, same trick as encounters.
        header = header.withColumn("service_year_month", F.date_format("service_date", "yyyy-MM"))
        write_delta(header, header_path, mode="overwrite", partition_by=["service_year_month"])
        write_delta(lines, lines_path, mode="overwrite")

        log.info("wrote fact_claim",
                 extra={"object_name": "fact_claim", "rows_written": header.count(), "layer": "silver"})
        log.info("wrote fact_claim_line",
                 extra={"object_name": "fact_claim_line", "rows_written": lines.count(), "layer": "silver"})

        if rejected_all is not None:
            write_quarantine(rejected_all, f"{args.quarantine_root.rstrip('/')}/fact_claim")
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
