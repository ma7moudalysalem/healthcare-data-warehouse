"""Unit tests for the pure-pandas Gold -> Azure SQL loader functions.

These exercise the dim_payer / dim_diagnosis loaders (added when gold_load.py
started staging those two dims) without a live database: a fake cursor captures
the DELETE + INSERT the loader issues, and we assert the staging parquet is
mapped onto the dw.* columns correctly (including NULL handling).
"""
from __future__ import annotations

import pandas as pd

from pipelines.gold import gold_to_sql


class _FakeCursor:
    def __init__(self):
        self.executed = []        # list of (sql, params)
        self.executed_many = []   # list of (sql, rows)

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def executemany(self, sql, rows):
        self.executed_many.append((sql, list(rows)))


def _write_staging(gold_root, name, df):
    staging = gold_root / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    df.to_parquet(staging / name)


def test_load_dim_payer_maps_columns_and_refreshes(tmp_path):
    _write_staging(tmp_path, "dim_payer_incoming", pd.DataFrame([
        {"payer_name": "Allianz Egypt", "is_government": False, "is_active": True, "payer_sk": 111},
        {"payer_name": "HIO", "is_government": True, "is_active": True, "payer_sk": 222},
    ]))
    cur = _FakeCursor()

    n = gold_to_sql.load_dim_payer(cur, str(tmp_path))

    assert n == 2
    # type-1 full refresh: a DELETE must precede the insert
    assert cur.executed[0][0].strip().upper().startswith("DELETE FROM DW.DIM_PAYER")
    sql, rows = cur.executed_many[0]
    assert "INSERT INTO dw.dim_payer" in sql
    assert sql.count("%s") == 5
    # (payer_sk, payer_bk=NULL, payer_name, is_government_bit, is_active_bit)
    assert (111, None, "Allianz Egypt", 0, 1) in rows
    assert (222, None, "HIO", 1, 1) in rows


def test_load_dim_diagnosis_maps_columns_and_nulls(tmp_path):
    _write_staging(tmp_path, "dim_diagnosis_incoming", pd.DataFrame([
        {"icd10_code": "I10", "description": "Essential hypertension",
         "chapter": "Diseases of the circulatory system", "diagnosis_sk": 900},
        {"icd10_code": "Z99", "description": None, "chapter": "Unclassified", "diagnosis_sk": 901},
    ]))
    cur = _FakeCursor()

    n = gold_to_sql.load_dim_diagnosis(cur, str(tmp_path))

    assert n == 2
    assert cur.executed[0][0].strip().upper().startswith("DELETE FROM DW.DIM_DIAGNOSIS")
    sql, rows = cur.executed_many[0]
    assert "INSERT INTO dw.dim_diagnosis" in sql
    assert sql.count("%s") == 4
    assert (900, "I10", "Essential hypertension", "Diseases of the circulatory system") in rows
    # NaN/None description must bind as a real SQL NULL, not the string "nan"
    assert (901, "Z99", None, "Unclassified") in rows
