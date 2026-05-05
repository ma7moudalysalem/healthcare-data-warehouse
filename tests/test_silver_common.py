"""Tests for pipelines.silver.silver_common.

These run only if PySpark is importable. The CI marks PySpark as optional
to keep the unit-test step on a small runner; the Spark tests run on the
nightly job.
"""
import importlib

import pytest

pyspark = pytest.importorskip("pyspark")


@pytest.fixture(scope="module")
def spark():
    from pyspark.sql import SparkSession
    s = (
        SparkSession.builder
        .master("local[2]")
        .appName("hcdw-tests")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    yield s
    s.stop()


def test_governorate_remap_is_deterministic(spark):
    from pyspark.sql import functions as F
    from pipelines.silver.silver_common import remap_to_governorate

    df = spark.createDataFrame([("Massachusetts",), ("California",), ("New York",)], ["state"])
    a = df.select(remap_to_governorate(F.col("state")).alias("g")).collect()
    b = df.select(remap_to_governorate(F.col("state")).alias("g")).collect()
    assert [r["g"] for r in a] == [r["g"] for r in b]


def test_age_band_buckets(spark):
    from pyspark.sql import functions as F
    from pipelines.silver.silver_common import age_band

    df = spark.createDataFrame(
        [(d,) for d in ["2020-01-01", "2010-06-15", "1990-01-01", "1975-01-01", "1955-01-01", "1940-01-01"]],
        ["dob_str"],
    ).withColumn("dob", F.to_date("dob_str"))
    df = df.withColumn("ab", age_band(F.col("dob"), F.lit("2026-05-01").cast("date")))
    bands = [r["ab"] for r in df.collect()]
    expected = ["0-17", "0-17", "35-49", "50-64", "65-79", "80+"]
    assert bands == expected


def test_split_by_rule_partitions_correctly(spark):
    from pyspark.sql import functions as F
    from pipelines.silver.silver_common import split_by_rule

    df = spark.createDataFrame([(1, "ok"), (2, None), (3, "ok"), (4, None)], ["id", "v"])
    res = split_by_rule(df, F.col("v").isNotNull(), "v_present")
    assert res.total == 4
    assert res.rejected_count == 2
    assert res.clean.count() == 2
    rule_col = [r["_rejected_rule"] for r in res.rejected.collect()]
    assert rule_col == ["v_present", "v_present"]
