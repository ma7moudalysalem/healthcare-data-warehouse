"""Shared helpers for the Silver-layer transforms.

Silver is where:
* schema is enforced (typed columns, no `inferSchema`).
* DQ rules run; rejects go to a quarantine path.
* Egyptian governorate remap is applied to Synthea's US addresses.
* Surrogate keys are *not* assigned (those are Gold's job).

Silver outputs are Delta tables. Each transform writes both the clean output
and a quarantine table for rejected rows.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F


# --- Egypt remap pools -------------------------------------------------------
GOVERNORATE_BY_BUCKET: list[tuple[str, str]] = [
    # bucket-key, governorate. Synthea's US state column hashes into one of
    # these so the same source state always maps to the same governorate;
    # avoids spurious SCD2 updates.
    ("0", "Cairo"),       ("1", "Cairo"),       ("2", "Cairo"),
    ("3", "Giza"),        ("4", "Giza"),
    ("5", "Alexandria"),  ("6", "Alexandria"),
    ("7", "Menoufia"),
    ("8", "Sharqia"),
    ("9", "Dakahlia"),
    ("a", "Qalyubia"),    ("b", "Qalyubia"),
    ("c", "Gharbia"),
    ("d", "Beheira"),
    ("e", "Fayoum"),
    ("f", "Minya"),
]

GOV_LOOKUP_KEYS = [k for k, _ in GOVERNORATE_BY_BUCKET]
GOV_LOOKUP_VALS = [v for _, v in GOVERNORATE_BY_BUCKET]


def remap_to_governorate(state_col: Column) -> Column:
    """Deterministically map a free-text state to one of our governorates.

    We md5 the state string, take the last hex character, and look it up in
    the table above. This guarantees that re-runs for the same patient land
    in the same governorate (so SCD2 doesn't get noisy).
    """
    last_hex = F.substring(F.md5(F.coalesce(state_col, F.lit(""))), -1, 1)
    cases = F.when(F.lit(False), F.lit(None))  # placeholder, replaced below
    for k, v in GOVERNORATE_BY_BUCKET:
        cases = cases.when(last_hex == F.lit(k), F.lit(v))
    return cases.otherwise(F.lit("Cairo"))


def age_band(dob_col: Column, asof_col: Column | None = None) -> Column:
    """Age band derived from date_of_birth.

    asof_col defaults to current_date(). Bands match the data dictionary:
    0-17, 18-34, 35-49, 50-64, 65-79, 80+.
    """
    asof = asof_col if asof_col is not None else F.current_date()
    age_years = F.floor(F.datediff(asof, dob_col) / 365.25)
    return (
        F.when(age_years < 18, F.lit("0-17"))
         .when(age_years < 35, F.lit("18-34"))
         .when(age_years < 50, F.lit("35-49"))
         .when(age_years < 65, F.lit("50-64"))
         .when(age_years < 80, F.lit("65-79"))
         .otherwise(F.lit("80+"))
    )


@dataclass
class DQResult:
    clean: DataFrame
    rejected: DataFrame
    rule_name: str
    total: int
    rejected_count: int

    def report(self) -> None:
        pct = (self.rejected_count / self.total * 100) if self.total else 0.0
        print(
            f"  DQ [{self.rule_name}]: {self.rejected_count:,}/{self.total:,} rejected ({pct:.2f}%)",
            file=sys.stderr,
        )


def split_by_rule(df: DataFrame, rule: Column, rule_name: str) -> DQResult:
    """Split a dataframe into (passes, fails) by a boolean rule expression.

    `rule` evaluates to TRUE for rows that should pass, FALSE/NULL for fails.
    """
    total = df.count()
    clean = df.where(rule)
    rejected = (
        df.where(~rule | rule.isNull())
          .withColumn("_rejected_rule", F.lit(rule_name))
          .withColumn("_rejected_at", F.current_timestamp())
    )
    return DQResult(
        clean=clean,
        rejected=rejected,
        rule_name=rule_name,
        total=total,
        rejected_count=rejected.count(),
    )


def write_delta(df: DataFrame, path: str, mode: str = "overwrite",
                partition_by: list[str] | None = None) -> None:
    writer = df.write.format("delta").mode(mode)
    if partition_by:
        writer = writer.partitionBy(*partition_by)
    writer.save(path)


def write_quarantine(df: DataFrame, path: str) -> None:
    """Quarantine writes are append-only and partitioned by date."""
    if len(df.head(1)) == 0:
        return
    df.withColumn("_quarantine_date", F.to_date(F.current_timestamp())) \
      .write.format("delta") \
      .mode("append") \
      .partitionBy("_quarantine_date", "_rejected_rule") \
      .save(path)
