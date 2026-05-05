"""Silver: provider_registry -> typed dim_provider table.

Most provider attributes come from the API; we keep the original facility
code so Gold can resolve it to a hospital surrogate key.
"""
from __future__ import annotations

import argparse
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from .silver_common import split_by_rule, write_delta, write_quarantine


def _spark() -> SparkSession:
    return (
        SparkSession.builder
        .appName("silver_dim_provider")
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
        bronze_path = f"{args.bronze_root.rstrip('/')}/provider_registry"
        df = spark.read.parquet(bronze_path)
        print(f"Loaded {df.count():,} providers from {bronze_path}", file=sys.stderr)

        df = df.select(
            F.col("npi").alias("provider_bk"),
            F.col("first_name"),
            F.col("last_name"),
            F.concat_ws(" ", F.col("first_name"), F.col("last_name")).alias("full_name"),
            F.col("credential"),
            F.col("specialty"),
            F.col("primary_facility_code").alias("hospital_bk"),
            F.col("license_number"),
            F.to_date("license_expiry").alias("license_expiry"),
            F.to_date("hire_date").alias("hire_date"),
            F.col("is_active").cast("boolean"),
            F.col("phone"),
            F.col("email"),
            F.col("_ingest_ts"),
        )

        rules = [
            ("npi_present", F.col("provider_bk").isNotNull()),
            ("npi_10_digits", F.length("provider_bk") == 10),
            ("name_present", F.col("first_name").isNotNull() & F.col("last_name").isNotNull()),
        ]

        clean = df
        rejected_all = None
        for name, rule in rules:
            res = split_by_rule(clean, rule, name)
            res.report()
            clean = res.clean
            rejected_all = res.rejected if rejected_all is None else rejected_all.unionByName(res.rejected)

        w = Window.partitionBy("provider_bk").orderBy(F.col("_ingest_ts").desc())
        clean = (clean.withColumn("_rn", F.row_number().over(w))
                       .where(F.col("_rn") == 1).drop("_rn"))

        silver_path = f"{args.silver_root.rstrip('/')}/dim_provider"
        write_delta(clean, silver_path, mode="overwrite")
        print(f"Wrote {clean.count():,} rows to {silver_path}", file=sys.stderr)

        if rejected_all is not None:
            write_quarantine(rejected_all, f"{args.quarantine_root.rstrip('/')}/dim_provider")
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
