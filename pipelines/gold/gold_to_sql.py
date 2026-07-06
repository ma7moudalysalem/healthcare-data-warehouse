"""Gold -> Azure SQL: load pipelines/gold/gold_load.py's parquet staging
output directly into the live dw.* tables, replacing pipelines/gold/
seed_warehouse.py as the warehouse's data source.

The original design (sql/stored_procedures/sp_merge_dim_*_scd2.sql) assumes
an ADF Copy activity lands the staging parquet into SQL Server stg.* tables
and a NEXT VALUE FOR ...sk_seq sequence issues surrogate keys. Azure SQL
Database Basic tier never got that ADF orchestration deployed, and the
warehouse's actual DDL (sql/ddl/azuresql/warehouse_azuresql.sql) has no
sequence objects - it uses deterministic MD5-hash surrogate keys instead
(same scheme gold_load.py already uses for facts). This loader applies that
same scheme directly from Python, so it works against the schema that is
actually deployed.

dim_hospital is type-1 (no history): every run replaces it wholesale.
dim_patient / dim_provider are true SCD2: unchanged business keys are left
alone, changed attributes close the current version and open a new one.
fact_encounter / fact_claim are full-refresh, since gold_load.py always
rebuilds them from the complete Silver tables (there is no incremental/
partial case to reconcile).

gold_load.py now stages dim_payer and dim_diagnosis, and this loader populates
them (type-1 full refresh) so payer_sk / primary_diagnosis_sk resolve on every
fact row. provider_sk still lands NULL: encounter/claim provider business keys
(Synthea provider UUIDs / random claim NPIs) do not map to the provider_api
registry that dim_provider is built from, so hashing them would produce orphan
keys - wiring it needs the generators to draw providers from that registry first.

Run:
    HCDW_SQL_SERVER=... HCDW_SQL_DB=... HCDW_SQL_USER=... HCDW_SQL_PASSWORD=... \\
        python -m pipelines.gold.gold_to_sql --gold-root data/gold
"""
from __future__ import annotations

import argparse
import hashlib
import os

import pandas as pd

from pipelines.logging_config import get_logger

log = get_logger(__name__)


def _connect():
    import pymssql  # lazy: keeps the pure-pandas loader functions importable/testable without the driver
    return pymssql.connect(
        server=os.environ["HCDW_SQL_SERVER"], user=os.environ["HCDW_SQL_USER"],
        password=os.environ["HCDW_SQL_PASSWORD"], database=os.environ["HCDW_SQL_DB"],
        port=1433, tds_version="7.4")


def _read(gold_root: str, name: str) -> pd.DataFrame:
    return pd.read_parquet(f"{gold_root.rstrip('/')}/staging/{name}")


def _n(x):
    """None-ify pandas/NumPy NaN/NaT so pymssql binds a real SQL NULL."""
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return x


def _int(x):
    x = _n(x)
    return int(x) if x is not None else None


def _float(x):
    x = _n(x)
    return float(x) if x is not None else None


def _bit(x):
    x = _n(x)
    return int(bool(x)) if x is not None else None


def _sk(business_key: str) -> int:
    """Deterministic surrogate key: same MD5-hash scheme gold_load.py's Spark
    code uses (F.conv(F.substring(F.md5(col), 1, 12), 16, 10)), so a
    dimension's key here always matches the value already baked into
    fact_encounter/fact_claim's *_sk columns.
    """
    return int(hashlib.md5(business_key.encode("utf-8")).hexdigest()[:12], 16)


def _hash_patient(r) -> str:
    dob = r.date_of_birth.isoformat() if _n(r.date_of_birth) is not None else ""
    parts = [
        r.first_name or "", r.last_name or "", dob, r.age_band or "",
        r.gender or "", r.marital_status or "", r.race or "",
        r.ethnicity or "", r.governorate or "", r.city or "",
        "1" if r.is_deceased else "0",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest().upper()


def _hash_provider(r) -> str:
    facility_sk = _n(r.primary_facility_sk)
    parts = [
        r.full_name or "", r.credential or "", r.specialty or "",
        str(int(facility_sk)) if facility_sk is not None else "",
        r.license_expiry.isoformat() if _n(r.license_expiry) is not None else "",
        r.hire_date.isoformat() if _n(r.hire_date) is not None else "",
        "1" if r.is_active else "0",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest().upper()


def load_dim_hospital(cur, gold_root: str) -> int:
    df = _read(gold_root, "dim_hospital_incoming")
    cur.execute("DELETE FROM dw.dim_hospital")
    rows = [
        (_int(r.hospital_sk), r.hospital_bk, r.hospital_name, r.facility_type,
         r.city, r.governorate, _int(r.bed_count), _bit(r.is_active),
         _float(r.lat), _float(r.lon))
        for r in df.itertuples(index=False)
    ]
    cur.executemany(
        "INSERT INTO dw.dim_hospital "
        "(hospital_sk, hospital_bk, hospital_name, facility_type, city, governorate, "
        " bed_count, is_active, lat, lon) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        rows,
    )
    log.info("loaded dim_hospital", extra={"layer": "gold_to_sql", "object_name": "dim_hospital",
                                            "rows_written": len(rows)})
    return len(rows)


def load_dim_patient_scd2(cur, gold_root: str, load_ts) -> int:
    df = _read(gold_root, "dim_patient_incoming")

    cur.execute("SELECT patient_bk, record_hash FROM dw.dim_patient WHERE is_current = 1")
    current = {bk: h for bk, h in cur.fetchall()}

    to_close, to_insert = [], []
    for r in df.itertuples(index=False):
        new_hash = _hash_patient(r)
        existing_hash = current.get(r.patient_bk)
        if existing_hash == new_hash:
            continue  # unchanged - no-op
        if existing_hash is not None:
            to_close.append(r.patient_bk)
        full_name = " ".join(p for p in [r.first_name, r.last_name] if p)
        to_insert.append((
            _sk(r.patient_bk), r.patient_bk, r.mrn, r.first_name, r.last_name, full_name,
            r.date_of_birth, r.age_band, r.gender, r.marital_status, r.race, r.ethnicity,
            r.governorate, r.city, _bit(r.is_deceased),
            load_ts, None, 1, new_hash,
        ))

    if to_close:
        cur.executemany(
            "UPDATE dw.dim_patient SET effective_to = %s, is_current = 0 "
            "WHERE patient_bk = %s AND is_current = 1",
            [(load_ts, bk) for bk in to_close],
        )
    if to_insert:
        cur.executemany(
            "INSERT INTO dw.dim_patient "
            "(patient_sk, patient_bk, mrn, first_name, last_name, full_name, date_of_birth, "
            " age_band, gender, marital_status, race, ethnicity, governorate, city, "
            " is_deceased, effective_from, effective_to, is_current, record_hash) "
            "VALUES (%s,CAST(%s AS UNIQUEIDENTIFIER),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            to_insert,
        )
    log.info("loaded dim_patient", extra={"layer": "gold_to_sql", "object_name": "dim_patient",
                                           "rows_read": len(df), "rows_written": len(to_insert)})
    return len(to_insert)


def load_dim_provider_scd2(cur, gold_root: str, load_ts) -> int:
    df = _read(gold_root, "dim_provider_incoming")

    cur.execute("SELECT provider_bk, record_hash FROM dw.dim_provider WHERE is_current = 1")
    current = {bk: h for bk, h in cur.fetchall()}

    to_close, to_insert = [], []
    for r in df.itertuples(index=False):
        new_hash = _hash_provider(r)
        existing_hash = current.get(r.provider_bk)
        if existing_hash == new_hash:
            continue
        if existing_hash is not None:
            to_close.append(r.provider_bk)
        facility_sk = _int(r.primary_facility_sk)
        to_insert.append((
            _sk(r.provider_bk), r.provider_bk, r.full_name, r.credential, r.specialty,
            facility_sk, r.license_expiry, r.hire_date, _bit(r.is_active),
            load_ts, None, 1, new_hash,
        ))

    if to_close:
        cur.executemany(
            "UPDATE dw.dim_provider SET effective_to = %s, is_current = 0 "
            "WHERE provider_bk = %s AND is_current = 1",
            [(load_ts, bk) for bk in to_close],
        )
    if to_insert:
        cur.executemany(
            "INSERT INTO dw.dim_provider "
            "(provider_sk, provider_bk, full_name, credential, specialty, primary_facility_sk, "
            " license_expiry, hire_date, is_active, effective_from, effective_to, is_current, "
            " record_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            to_insert,
        )
    log.info("loaded dim_provider", extra={"layer": "gold_to_sql", "object_name": "dim_provider",
                                            "rows_read": len(df), "rows_written": len(to_insert)})
    return len(to_insert)


def load_dim_payer(cur, gold_root: str) -> int:
    """Type-1 full refresh. gold_load stages the distinct claim carriers with an
    MD5 payer_sk; the schema's payer_bk is unused here (no integer natural key),
    so it lands NULL.
    """
    df = _read(gold_root, "dim_payer_incoming")
    cur.execute("DELETE FROM dw.dim_payer")
    rows = [
        (_int(r.payer_sk), None, r.payer_name, _bit(r.is_government), _bit(r.is_active))
        for r in df.itertuples(index=False)
    ]
    cur.executemany(
        "INSERT INTO dw.dim_payer (payer_sk, payer_bk, payer_name, is_government, is_active) "
        "VALUES (%s,%s,%s,%s,%s)",
        rows,
    )
    log.info("loaded dim_payer", extra={"layer": "gold_to_sql", "object_name": "dim_payer",
                                        "rows_written": len(rows)})
    return len(rows)


def load_dim_diagnosis(cur, gold_root: str) -> int:
    """Type-1 full refresh. gold_load stages the distinct claim ICD-10 codes,
    chaptered via the standard ICD-10-CM ranges, with an MD5 diagnosis_sk.
    """
    df = _read(gold_root, "dim_diagnosis_incoming")
    cur.execute("DELETE FROM dw.dim_diagnosis")
    rows = [
        (_int(r.diagnosis_sk), r.icd10_code, _n(r.description), _n(r.chapter))
        for r in df.itertuples(index=False)
    ]
    cur.executemany(
        "INSERT INTO dw.dim_diagnosis (diagnosis_sk, icd10_code, description, chapter) "
        "VALUES (%s,%s,%s,%s)",
        rows,
    )
    log.info("loaded dim_diagnosis", extra={"layer": "gold_to_sql", "object_name": "dim_diagnosis",
                                            "rows_written": len(rows)})
    return len(rows)


def load_fact_encounter(cur, gold_root: str) -> int:
    df = _read(gold_root, "fact_encounter")
    cur.execute("DELETE FROM dw.fact_encounter")
    rows = [
        (_int(r.encounter_sk), r.encounter_bk, _int(r.patient_sk), _int(r.provider_sk),
         _int(r.hospital_sk), _int(r.primary_diagnosis_sk), _int(r.start_date_sk),
         _int(r.end_date_sk), r.encounter_class, _float(r.length_of_stay_hours),
         _float(r.base_cost_usd), _float(r.total_cost_usd), _float(r.payer_coverage_usd),
         _float(r.out_of_pocket_usd), _bit(r.is_inpatient), _bit(r.is_emergency),
         _bit(r.is_readmission_30d), r.discharge_status, r.silver_loaded_at, r.gold_loaded_at)
        for r in df.itertuples(index=False)
    ]
    cur.executemany(
        "INSERT INTO dw.fact_encounter "
        "(encounter_sk, encounter_bk, patient_sk, provider_sk, hospital_sk, primary_diagnosis_sk, "
        " start_date_sk, end_date_sk, encounter_class, length_of_stay_hours, base_cost_usd, "
        " total_cost_usd, payer_coverage_usd, out_of_pocket_usd, is_inpatient, is_emergency, "
        " is_readmission_30d, discharge_status, silver_loaded_at, gold_loaded_at) "
        "VALUES (%s,CAST(%s AS UNIQUEIDENTIFIER),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        rows,
    )
    log.info("loaded fact_encounter", extra={"layer": "gold_to_sql", "object_name": "fact_encounter",
                                              "rows_written": len(rows)})
    return len(rows)


def load_fact_claim(cur, gold_root: str) -> int:
    df = _read(gold_root, "fact_claim")
    cur.execute("DELETE FROM dw.fact_claim")
    rows = [
        (_int(r.claim_sk), r.claim_bk, r.claim_number, _int(r.encounter_sk), _int(r.patient_sk),
         _int(r.provider_sk), _int(r.hospital_sk), _int(r.payer_sk), _int(r.primary_diagnosis_sk),
         _int(r.service_date_sk), _int(r.submission_date_sk), _int(r.decision_date_sk),
         _int(r.days_to_decision), r.status, _bit(r.is_denied), _bit(r.is_paid_in_full),
         _int(r.line_count), _float(r.billed_amount), _float(r.allowed_amount),
         _float(r.paid_amount), _float(r.denied_amount), _float(r.patient_responsibility),
         r.currency, r.silver_loaded_at, r.gold_loaded_at)
        for r in df.itertuples(index=False)
    ]
    cur.executemany(
        "INSERT INTO dw.fact_claim "
        "(claim_sk, claim_bk, claim_number, encounter_sk, patient_sk, provider_sk, hospital_sk, "
        " payer_sk, primary_diagnosis_sk, service_date_sk, submission_date_sk, decision_date_sk, "
        " days_to_decision, status, is_denied, is_paid_in_full, line_count, billed_amount, "
        " allowed_amount, paid_amount, denied_amount, patient_responsibility, currency, "
        " silver_loaded_at, gold_loaded_at) "
        "VALUES (%s,CAST(%s AS UNIQUEIDENTIFIER),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        rows,
    )
    log.info("loaded fact_claim", extra={"layer": "gold_to_sql", "object_name": "fact_claim",
                                          "rows_written": len(rows)})
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold-root", required=True)
    parser.add_argument("--only", default=None,
                        help="comma list: dim_hospital,dim_patient,dim_provider,dim_payer,"
                             "dim_diagnosis,fact_encounter,fact_claim")
    args = parser.parse_args(argv)
    only = set(args.only.split(",")) if args.only else None

    cn = _connect()
    try:
        cur = cn.cursor()
        load_ts = pd.Timestamp.utcnow().tz_localize(None).replace(microsecond=0)

        # Order matters: dims before facts, hospital before provider (FK-ish join).
        if not only or "dim_hospital" in only:
            load_dim_hospital(cur, args.gold_root)
            cn.commit()
        if not only or "dim_patient" in only:
            load_dim_patient_scd2(cur, args.gold_root, load_ts)
            cn.commit()
        if not only or "dim_provider" in only:
            load_dim_provider_scd2(cur, args.gold_root, load_ts)
            cn.commit()
        if not only or "dim_payer" in only:
            load_dim_payer(cur, args.gold_root)
            cn.commit()
        if not only or "dim_diagnosis" in only:
            load_dim_diagnosis(cur, args.gold_root)
            cn.commit()
        if not only or "fact_encounter" in only:
            load_fact_encounter(cur, args.gold_root)
            cn.commit()
        if not only or "fact_claim" in only:
            load_fact_claim(cur, args.gold_root)
            cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
