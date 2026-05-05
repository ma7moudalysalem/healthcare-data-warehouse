"""Gold: read Silver Delta tables and stage them for Synapse loading.

Approach:
* Each dimension's Silver table is rewritten as a "staging" parquet file
  with the SCD2-input columns the merge proc expects.
* For facts, we look up the surrogate keys against the *current* dim
  versions and write a parquet ready for `COPY INTO dw.fact_*`.
* Synapse-side, ADF triggers `sp_merge_dim_*` then `COPY INTO` the facts,
  and finally `sp_refresh_kpi_daily`. That orchestration lives in the
  ADF templates under `pipelines/adf_templates/`.

This module focuses on the Spark-side prep. It does not connect to Synapse
itself - the ADF Copy activities handle that to keep credentials out of
the notebook.
"""
from __future__ import annotations

import argparse
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


def _spark() -> SparkSession:
    return (
        SparkSession.builder
        .appName("gold_load")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.jars.packages", "io.delta:delta-spark_2.12:3.0.0")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )


def _dim_patient_staging(spark: SparkSession, silver_root: str, gold_root: str) -> None:
    src = spark.read.format("delta").load(f"{silver_root}/dim_patient")
    out = src.select(
        "patient_bk",
        F.lit(None).cast("string").alias("mrn"),  # not surfaced from Synthea; OLTP loader sets one
        "first_name", "last_name", "date_of_birth", "age_band",
        "gender", "marital_status", "race", "ethnicity",
        "governorate", "city", "is_deceased",
    )
    out.write.mode("overwrite").parquet(f"{gold_root}/staging/dim_patient_incoming")
    print(f"  staged dim_patient: {out.count():,} rows", file=sys.stderr)


def _dim_provider_staging(spark: SparkSession, silver_root: str, gold_root: str) -> None:
    """Provider needs primary_facility_sk, but we only have hospital_bk in Silver.
    The Synapse-side merge will re-resolve via a join on hospital_bk in the proc;
    here we just write hospital_bk and let the proc figure it out.

    NOTE: For the simplified MVP path (no full ADF orchestration), the
    sp_merge_dim_provider_scd2 proc accepts primary_facility_sk; we resolve
    it here by joining staging dim_hospital that gold_load wrote earlier.
    """
    src = spark.read.format("delta").load(f"{silver_root}/dim_provider")
    hosp = spark.read.parquet(f"{gold_root}/staging/dim_hospital_incoming")  # produced by _dim_hospital_staging
    joined = (
        src.join(hosp.select(F.col("hospital_bk"), F.col("hospital_sk").alias("primary_facility_sk")),
                 on="hospital_bk", how="left")
           .select(
               "provider_bk", "full_name", "credential", "specialty",
               "primary_facility_sk", "license_expiry", "hire_date", "is_active",
           )
    )
    joined.write.mode("overwrite").parquet(f"{gold_root}/staging/dim_provider_incoming")
    print(f"  staged dim_provider: {joined.count():,} rows", file=sys.stderr)


def _dim_hospital_staging(spark: SparkSession, gold_root: str, hospital_seed_path: str) -> None:
    """Hospitals are seeded in the OLTP database; we read the same seed here
    and assign deterministic surrogate keys (hospital_bk hash) so subsequent
    fact loads can join.
    """
    df = spark.read.option("header", True).csv(hospital_seed_path)
    df = df.select(
        F.col("hospital_code").alias("hospital_bk"),
        F.col("hospital_name"),
        F.when(F.col("is_clinic") == "1", F.lit("clinic")).otherwise(F.lit("hospital")).alias("facility_type"),
        F.col("city"),
        F.col("governorate"),
        F.col("bed_count").cast("int"),
        F.lit(True).alias("is_active"),
        # Deterministic surrogate key from natural key.
        F.conv(F.substring(F.md5(F.col("hospital_code")), 1, 12), 16, 10).cast("bigint").alias("hospital_sk"),
    )
    df.write.mode("overwrite").parquet(f"{gold_root}/staging/dim_hospital_incoming")
    print(f"  staged dim_hospital: {df.count():,} rows", file=sys.stderr)


def _fact_encounter_staging(spark: SparkSession, silver_root: str, gold_root: str) -> None:
    enc = spark.read.format("delta").load(f"{silver_root}/fact_encounter")
    pat = spark.read.parquet(f"{gold_root}/staging/dim_patient_incoming") \
                    .withColumn("patient_sk",
                                F.conv(F.substring(F.md5(F.col("patient_bk")), 1, 12), 16, 10).cast("bigint")) \
                    .select("patient_bk", "patient_sk")
    hosp = spark.read.parquet(f"{gold_root}/staging/dim_hospital_incoming") \
                     .select("hospital_bk", "hospital_sk")

    # Synthea encounters reference an "ORGANIZATION" id, not our hospital_code.
    # The OLTP loader assigns a hospital_code at random; we re-derive the same
    # mapping here by salting the organization id into our hospital pool.
    hosp_codes = [r["hospital_bk"] for r in hosp.collect()]
    hosp_count = len(hosp_codes)
    hosp_codes_lit = F.array(*[F.lit(c) for c in hosp_codes])

    enc = enc.withColumn(
        "hospital_bk",
        hosp_codes_lit[
            F.abs(F.crc32(F.col("organization_bk"))) % F.lit(hosp_count)
        ],
    )

    fact = (
        enc.join(pat, on="patient_bk", how="inner")
           .join(hosp, on="hospital_bk", how="inner")
           .withColumn("encounter_sk",
                       F.conv(F.substring(F.md5(F.col("encounter_bk")), 1, 12), 16, 10).cast("bigint"))
           .withColumn("start_date_sk", F.date_format("start_at", "yyyyMMdd").cast("int"))
           .withColumn("end_date_sk",
                       F.when(F.col("end_at").isNotNull(), F.date_format("end_at", "yyyyMMdd").cast("int")))
           .withColumn("silver_loaded_at", F.col("_ingest_ts"))
           .withColumn("gold_loaded_at", F.current_timestamp())
           .select(
               "encounter_sk", "encounter_bk", "patient_sk",
               F.lit(None).cast("bigint").alias("provider_sk"),       # provider mapping done in M5 enrichment
               "hospital_sk",
               F.lit(None).cast("bigint").alias("primary_diagnosis_sk"),
               "start_date_sk", "end_date_sk",
               "encounter_class", "length_of_stay_hours",
               "base_cost_usd", "total_cost_usd", "payer_coverage_usd",
               "out_of_pocket_usd",
               "is_inpatient", "is_emergency", "is_readmission_30d",
               F.lit(None).cast("string").alias("discharge_status"),
               "silver_loaded_at", "gold_loaded_at",
           )
    )
    fact.write.mode("overwrite").parquet(f"{gold_root}/staging/fact_encounter")
    print(f"  staged fact_encounter: {fact.count():,} rows", file=sys.stderr)


def _fact_claim_staging(spark: SparkSession, silver_root: str, gold_root: str) -> None:
    claims = spark.read.format("delta").load(f"{silver_root}/fact_claim")

    # Deterministic surrogate keys from natural keys (same hash trick as elsewhere).
    out = (
        claims.withColumn("claim_sk",
                          F.conv(F.substring(F.md5(F.col("claim_bk")), 1, 12), 16, 10).cast("bigint"))
              .withColumn("encounter_sk",
                          F.when(F.col("encounter_bk").isNotNull(),
                                 F.conv(F.substring(F.md5(F.col("encounter_bk")), 1, 12), 16, 10).cast("bigint")))
              .withColumn("patient_sk",
                          F.when(F.col("patient_bk").isNotNull(),
                                 F.conv(F.substring(F.md5(F.col("patient_bk")), 1, 12), 16, 10).cast("bigint")))
              .withColumn("hospital_sk",
                          F.when(F.col("hospital_bk").isNotNull(),
                                 F.conv(F.substring(F.md5(F.col("hospital_bk")), 1, 12), 16, 10).cast("bigint")))
              .withColumn("service_date_sk", F.date_format("service_date", "yyyyMMdd").cast("int"))
              .withColumn("submission_date_sk",
                          F.when(F.col("submission_date").isNotNull(),
                                 F.date_format("submission_date", "yyyyMMdd").cast("int")))
              .withColumn("decision_date_sk",
                          F.when(F.col("decision_date").isNotNull(),
                                 F.date_format("decision_date", "yyyyMMdd").cast("int")))
              .withColumn("silver_loaded_at", F.col("_ingest_ts"))
              .withColumn("gold_loaded_at", F.current_timestamp())
              .select(
                  "claim_sk", F.col("claim_bk").alias("claim_bk"), "claim_number",
                  "encounter_sk", "patient_sk",
                  F.lit(None).cast("bigint").alias("provider_sk"),
                  "hospital_sk",
                  F.lit(None).cast("bigint").alias("payer_sk"),
                  F.lit(None).cast("bigint").alias("primary_diagnosis_sk"),
                  "service_date_sk", "submission_date_sk", "decision_date_sk",
                  "days_to_decision",
                  "status", "is_denied", "is_paid_in_full",
                  "line_count",
                  "billed_amount", "allowed_amount", "paid_amount",
                  "denied_amount", "patient_responsibility",
                  "currency",
                  "silver_loaded_at", "gold_loaded_at",
              )
    )
    out.write.mode("overwrite").parquet(f"{gold_root}/staging/fact_claim")
    print(f"  staged fact_claim: {out.count():,} rows", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--silver-root", required=True)
    parser.add_argument("--gold-root", required=True)
    parser.add_argument("--hospital-seed-csv", required=True,
                        help="Path to hospital_seed.csv (columns: hospital_code, "
                             "hospital_name, city, governorate, bed_count, is_clinic).")
    parser.add_argument("--only", default=None,
                        help="comma list: dim_patient,dim_hospital,dim_provider,fact_encounter,fact_claim")
    args = parser.parse_args(argv)

    only = set(args.only.split(",")) if args.only else None
    silver = args.silver_root.rstrip("/")
    gold = args.gold_root.rstrip("/")

    spark = _spark()
    try:
        # Order matters - facts depend on dims being staged first.
        if not only or "dim_hospital" in only:
            _dim_hospital_staging(spark, gold, args.hospital_seed_csv)
        if not only or "dim_patient" in only:
            _dim_patient_staging(spark, silver, gold)
        if not only or "dim_provider" in only:
            _dim_provider_staging(spark, silver, gold)
        if not only or "fact_encounter" in only:
            _fact_encounter_staging(spark, silver, gold)
        if not only or "fact_claim" in only:
            _fact_claim_staging(spark, silver, gold)
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
