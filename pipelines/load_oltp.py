"""Load Synthea CSVs + claims JSONL into the OLTP SQL Server database.

This is the operational loader - it lands the raw feeds in the source schema
defined by `sql/ddl/01_oltp_source_schema.sql` so ADF can copy from a real
relational source the way it would in production. Don't confuse it with the
Bronze->Silver->Gold loaders under `pipelines/silver/` and `pipelines/gold/`,
which read from the data lake.

Usage:
    python -m pipelines.load_oltp --truncate            # wipe + load everything
    python -m pipelines.load_oltp --only patients,encounters

Environment variables (see .env.example):
    MSSQL_HOST, MSSQL_PORT, MSSQL_DB, MSSQL_USER, MSSQL_SA_PASSWORD,
    MSSQL_DRIVER
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW = PROJECT_ROOT / "data" / "raw"
SYNTHEA = RAW / "synthea"

# Synthea -> our schema column maps. Synthea changes the casing every couple
# of releases, so we lowercase before mapping.
PATIENT_MAP = {
    "id": "patient_id",
    "first": "first_name",
    "last": "last_name",
    "birthdate": "date_of_birth",
    "deathdate": "deceased_date",
    "marital": "marital_status",
    "race": "race",
    "ethnicity": "ethnicity",
    "gender": "gender",
    "address": "address_line",
    "city": "city",
    "state": "governorate",
    "zip": "postal_code",
}

# Egyptian governorate remap. Each Synthea state maps to one of the
# governorates the hospital network covers, in proportion to the bed share.
GOVERNORATE_POOL = [
    "Cairo", "Cairo", "Cairo", "Giza", "Giza",
    "Alexandria", "Alexandria", "Menoufia", "Sharqia", "Dakahlia",
    "Qalyubia", "Gharbia", "Beheira",
]


def _connect():
    try:
        import pyodbc
    except ImportError as e:  # pragma: no cover
        raise SystemExit("pyodbc is required. Install requirements.txt.") from e

    driver = os.environ.get("MSSQL_DRIVER", "ODBC Driver 18 for SQL Server")
    host = os.environ.get("MSSQL_HOST", "localhost")
    port = os.environ.get("MSSQL_PORT", "1433")
    db = os.environ.get("MSSQL_DB", "healthcare_oltp")
    user = os.environ.get("MSSQL_USER", "sa")
    pwd = os.environ.get("MSSQL_SA_PASSWORD", "YourStrong!Passw0rd")

    conn = pyodbc.connect(
        f"DRIVER={{{driver}}};SERVER={host},{port};DATABASE={db};"
        f"UID={user};PWD={pwd};TrustServerCertificate=Yes",
        autocommit=False,
    )
    conn.timeout = 60
    return conn


@contextmanager
def cursor():
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.fast_executemany = True
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _truncate_in_dependency_order(cur) -> None:
    # FKs prevent simple TRUNCATE; delete from leaves up.
    statements = [
        "DELETE FROM billing.claim_line",
        "DELETE FROM billing.claim",
        "DELETE FROM clinical.procedure_event",
        "DELETE FROM clinical.medication",
        "DELETE FROM clinical.condition",
        "DELETE FROM clinical.encounter",
        "DELETE FROM clinical.provider",
        "DELETE FROM clinical.patient",
    ]
    for stmt in statements:
        cur.execute(stmt)


def _df_synthea(filename: str) -> pd.DataFrame:
    path = SYNTHEA / filename
    if not path.exists():
        raise SystemExit(
            f"{path} not found. Run `python -m src.synthea.run_synthea` first."
        )
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    return df


def load_patients(cur, df: pd.DataFrame) -> int:
    rows = []
    rng = random.Random(20240212)
    for _, r in df.iterrows():
        gov = rng.choice(GOVERNORATE_POOL)
        rows.append((
            uuid.UUID(r["id"]),
            f"MRN-{rng.randint(10**8, 10**9 - 1)}",
            r["first"],
            r["last"],
            pd.to_datetime(r["birthdate"]).date(),
            (r.get("gender") or "U")[:1].upper(),
            r.get("marital"),
            r.get("race"),
            r.get("ethnicity"),
            r.get("address"),
            gov,                       # city: re-use governorate as city for clinics
            gov,                       # governorate
            str(r.get("zip") or "")[:15] or None,
            "Egypt",
            None,                      # phone (Synthea doesn't expose)
            pd.to_datetime(r["deathdate"]).date() if pd.notna(r.get("deathdate")) else None,
        ))
    cur.executemany(
        """INSERT INTO clinical.patient
            (patient_id, mrn, first_name, last_name, date_of_birth, gender,
             marital_status, race, ethnicity, address_line, city, governorate,
             postal_code, country, phone, deceased_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return len(rows)


def load_providers(cur) -> int:
    path = RAW / "providers.json"
    if not path.exists():
        print(f"  skip providers: {path} not found", file=sys.stderr)
        return 0
    with path.open("r", encoding="utf-8") as f:
        providers = json.load(f)

    rows = [(
        p["npi"],
        p["first_name"],
        p["last_name"],
        p.get("credential"),
        p.get("specialty"),
        p["primary_facility_code"],
        p.get("license_number"),
        datetime.fromisoformat(p["license_expiry"]).date() if p.get("license_expiry") else None,
        datetime.fromisoformat(p["hire_date"]).date() if p.get("hire_date") else None,
        1 if p.get("is_active") else 0,
        p.get("phone"),
        p.get("email"),
    ) for p in providers]

    cur.executemany(
        """INSERT INTO clinical.provider
            (provider_npi, first_name, last_name, credential, specialty,
             primary_facility, license_number, license_expiry, hire_date,
             is_active, phone, email)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return len(rows)


# Synthea encounter classes -> our normalized values.
ENC_CLASS_MAP = {
    "ambulatory": "ambulatory",
    "wellness":   "wellness",
    "emergency":  "emergency",
    "inpatient":  "inpatient",
    "outpatient": "ambulatory",
    "urgentcare": "emergency",
    "snf":        "inpatient",
    "home":       "ambulatory",
    "virtual":    "ambulatory",
}


def load_encounters(cur, df: pd.DataFrame, hospital_codes: list[str]) -> int:
    rng = random.Random(20240213)
    rows = []
    for _, r in df.iterrows():
        ec = ENC_CLASS_MAP.get(str(r.get("encounterclass", "")).lower(), "ambulatory")
        rows.append((
            uuid.UUID(r["id"]),
            uuid.UUID(r["patient"]),
            None,                                  # provider_npi - sparsely populated, set later
            rng.choice(hospital_codes),
            ec,
            r.get("description"),
            r.get("reasoncode") if pd.notna(r.get("reasoncode")) else None,
            r.get("reasondescription") if pd.notna(r.get("reasondescription")) else None,
            pd.to_datetime(r["start"]).to_pydatetime(),
            pd.to_datetime(r["stop"]).to_pydatetime() if pd.notna(r.get("stop")) else None,
            float(r["base_encounter_cost"]) if pd.notna(r.get("base_encounter_cost")) else None,
            float(r["total_claim_cost"]) if pd.notna(r.get("total_claim_cost")) else None,
            float(r["payer_coverage"]) if pd.notna(r.get("payer_coverage")) else None,
            None,
        ))
    cur.executemany(
        """INSERT INTO clinical.encounter
            (encounter_id, patient_id, provider_npi, hospital_code,
             encounter_class, encounter_type, reason_code, reason_description,
             start_at, end_at, base_cost_usd, total_cost_usd, payer_coverage_usd,
             discharge_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return len(rows)


def load_conditions(cur, df: pd.DataFrame) -> int:
    rows = [(
        uuid.UUID(r["encounter"]),
        uuid.UUID(r["patient"]),
        r["code"],
        r.get("description"),
        pd.to_datetime(r["start"]).date(),
        pd.to_datetime(r["stop"]).date() if pd.notna(r.get("stop")) else None,
    ) for _, r in df.iterrows()]
    cur.executemany(
        """INSERT INTO clinical.condition
            (encounter_id, patient_id, icd10_code, description, onset_date, abated_date)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return len(rows)


def load_medications(cur, df: pd.DataFrame) -> int:
    rows = [(
        uuid.UUID(r["encounter"]),
        uuid.UUID(r["patient"]),
        str(r["code"]),
        r.get("description"),
        pd.to_datetime(r["start"]).date(),
        pd.to_datetime(r["stop"]).date() if pd.notna(r.get("stop")) else None,
        float(r["dispenses"]) if pd.notna(r.get("dispenses")) else 1,
        float(r["totalcost"]) if pd.notna(r.get("totalcost")) else None,
    ) for _, r in df.iterrows()]
    cur.executemany(
        """INSERT INTO clinical.medication
            (encounter_id, patient_id, rxnorm_code, description, start_date,
             stop_date, dispenses, total_cost_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return len(rows)


def load_procedures(cur, df: pd.DataFrame) -> int:
    rows = [(
        uuid.UUID(r["encounter"]),
        uuid.UUID(r["patient"]),
        str(r["code"]),
        r.get("description"),
        pd.to_datetime(r["start"]).to_pydatetime(),
        float(r["base_cost"]) if pd.notna(r.get("base_cost")) else None,
    ) for _, r in df.iterrows()]
    cur.executemany(
        """INSERT INTO clinical.procedure_event
            (encounter_id, patient_id, cpt_code, description, performed_at, base_cost_usd)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return len(rows)


def load_claims(cur) -> int:
    path = RAW / "claims.jsonl"
    if not path.exists():
        print(f"  skip claims: {path} not found", file=sys.stderr)
        return 0

    # Map carrier name -> payer_id
    cur.execute("SELECT payer_id, payer_name FROM ref.payer")
    payer_lookup = {name: pid for pid, name in cur.fetchall()}

    claims = []
    lines = []
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            c = json.loads(raw_line)
            payer_id = payer_lookup.get(c["carrier"])
            claims.append((
                uuid.UUID(c["claim_id"]),
                c["claim_number"],
                uuid.UUID(c["encounter_id"]) if c.get("encounter_id") else None,
                uuid.UUID(c["patient_id"]) if c.get("patient_id") else None,
                c.get("provider_npi"),
                c.get("hospital_code"),
                payer_id,
                c.get("policy_number"),
                c.get("primary_diagnosis_code"),
                pd.to_datetime(c["service_date"]).date(),
                pd.to_datetime(c["submission_date"]).date() if c.get("submission_date") else None,
                pd.to_datetime(c["decision_date"]).date() if c.get("decision_date") else None,
                c["status"],
                c.get("denial_reason"),
                float(c["billed_amount"]),
                float(c["allowed_amount"]),
                float(c["paid_amount"]),
                float(c["patient_responsibility"]),
                c.get("currency", "EGP"),
                json.dumps(c, ensure_ascii=False),
            ))
            for i, item in enumerate(c.get("line_items", []), start=1):
                lines.append((
                    uuid.UUID(c["claim_id"]),
                    i,
                    item.get("cpt_code"),
                    item.get("description"),
                    int(item.get("units", 1)),
                    float(item["billed_amount"]),
                ))

    if claims:
        cur.executemany(
            """INSERT INTO billing.claim
                (claim_id, claim_number, encounter_id, patient_id, provider_npi,
                 hospital_code, payer_id, policy_number, primary_diagnosis_code,
                 service_date, submission_date, decision_date, status,
                 denial_reason, billed_amount, allowed_amount, paid_amount,
                 patient_responsibility, currency, raw_payload)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            claims,
        )
    if lines:
        cur.executemany(
            """INSERT INTO billing.claim_line
                (claim_id, line_number, cpt_code, description, units, billed_amount)
               VALUES (?, ?, ?, ?, ?, ?)""",
            lines,
        )
    return len(claims)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load Synthea + claims into OLTP.")
    parser.add_argument("--truncate", action="store_true",
                        help="DELETE all rows before loading.")
    parser.add_argument("--only", default=None,
                        help="Comma-separated list of tables to load.")
    args = parser.parse_args(argv)

    only = set(args.only.split(",")) if args.only else None

    print("Connecting to OLTP database ...", file=sys.stderr)
    with cursor() as cur:
        if args.truncate:
            print("Truncating tables ...", file=sys.stderr)
            _truncate_in_dependency_order(cur)

        cur.execute("SELECT hospital_code FROM ref.hospital WHERE is_active = 1")
        hospital_codes = [row[0] for row in cur.fetchall()]
        if not hospital_codes:
            raise SystemExit("ref.hospital is empty - run 02_oltp_seed_reference.sql first.")

        if not only or "patients" in only:
            df = _df_synthea("patients.csv")
            n = load_patients(cur, df)
            print(f"  patients : {n:,}", file=sys.stderr)
        if not only or "providers" in only:
            n = load_providers(cur)
            print(f"  providers: {n:,}", file=sys.stderr)
        if not only or "encounters" in only:
            df = _df_synthea("encounters.csv")
            n = load_encounters(cur, df, hospital_codes)
            print(f"  encounters: {n:,}", file=sys.stderr)
        if not only or "conditions" in only:
            df = _df_synthea("conditions.csv")
            n = load_conditions(cur, df)
            print(f"  conditions: {n:,}", file=sys.stderr)
        if not only or "medications" in only:
            df = _df_synthea("medications.csv")
            n = load_medications(cur, df)
            print(f"  medications: {n:,}", file=sys.stderr)
        if not only or "procedures" in only:
            df = _df_synthea("procedures.csv")
            n = load_procedures(cur, df)
            print(f"  procedures: {n:,}", file=sys.stderr)
        if not only or "claims" in only:
            n = load_claims(cur)
            print(f"  claims    : {n:,}", file=sys.stderr)

    print("Done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
