"""Build small Parquet fixtures so the Streamlit app runs without Synapse.

Drops three files into dashboards/streamlit/demo_data/ that match the
column shapes of dw.vw_encounter_enriched, dw.vw_claim_enriched and
dw.vw_vital_signs_minute. The numbers are seeded so screenshots taken
across machines look identical.

Run once:
    python dashboards/streamlit/build_demo_data.py
"""
from __future__ import annotations

import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "demo_data"
OUT.mkdir(exist_ok=True)

SEED = 20260101
random.seed(SEED)

HOSPITALS = [
    ("Cairo Central Hospital", "Cairo", 320, "hospital"),
    ("Nile Heart Institute", "Cairo", 180, "hospital"),
    ("Giza Specialty Hospital", "Giza", 240, "hospital"),
    ("Alexandria Bayside Medical", "Alexandria", 280, "hospital"),
    ("Menoufia Regional Medical", "Menoufia", 150, "hospital"),
]

DIAGNOSES = [
    ("I10", "Essential hypertension"),
    ("E11.9", "Type 2 diabetes mellitus"),
    ("J45.909", "Asthma, unspecified"),
    ("N39.0", "UTI, site not specified"),
    ("M54.5", "Low back pain"),
    ("R51", "Headache"),
    ("J18.9", "Pneumonia, unspecified"),
    ("F32.9", "Major depressive disorder"),
    ("E78.5", "Hyperlipidemia"),
    ("I25.10", "Atherosclerotic heart disease"),
]
PAYERS = ["Misr Insurance", "Allianz Egypt", "AXA Egypt", "Bupa Global",
          "MetLife Egypt", "Self-Pay", "Health Insurance Org. (HIO)"]
ENC_CLASSES = ["ambulatory", "emergency", "inpatient", "wellness"]
CLASS_WEIGHTS = [0.55, 0.18, 0.20, 0.07]


def _build_encounters(n: int = 4000) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=180)
    rows = []
    for i in range(n):
        h = random.choice(HOSPITALS)
        ec = random.choices(ENC_CLASSES, weights=CLASS_WEIGHTS, k=1)[0]
        d = start + timedelta(seconds=random.randint(0, int((end - start).total_seconds())))
        los = (
            None if ec == "ambulatory"
            else round(random.uniform(2, 8), 2) if ec == "emergency"
            else round(random.uniform(36, 144), 2) if ec == "inpatient"
            else round(random.uniform(0.5, 1.5), 2)
        )
        dx = random.choice(DIAGNOSES)
        rows.append({
            "encounter_sk": i + 1,
            "encounter_id": str(uuid.uuid4()),
            "encounter_class": ec,
            "encounter_date": d.date(),
            "encounter_year": d.year,
            "encounter_month": d.month,
            "encounter_month_name": d.strftime("%B"),
            "encounter_day_of_week": d.strftime("%A"),
            "length_of_stay_hours": los,
            "is_inpatient": ec == "inpatient",
            "is_emergency": ec == "emergency",
            "is_readmission_30d": ec == "inpatient" and random.random() < 0.11,
            "discharge_status": random.choice(["routine", "transfer", "ama", None]),
            "total_cost_usd": round(random.uniform(50, 25_000), 2),
            "payer_coverage_usd": round(random.uniform(40, 22_000), 2),
            "out_of_pocket_usd": round(random.uniform(0, 3_000), 2),
            "patient_id": str(uuid.uuid4()),
            "patient_name": f"Patient {i:05d}",
            "age_band": random.choice(["0-17", "18-34", "35-49", "50-64", "65-79", "80+"]),
            "gender": random.choice(["M", "F"]),
            "patient_governorate": h[1],
            "hospital_code": "HSP-XXX",
            "hospital_name": h[0],
            "facility_type": h[3],
            "hospital_governorate": h[1],
            "bed_count": h[2],
            "provider_name": (
                f"Dr. {random.choice(['Salem', 'Hassan', 'Gamal', 'Tarek', 'Reem'])}"
                f" {random.choice(['Ali', 'Adel', 'Ibrahim'])}"
            ),
            "provider_specialty": random.choice([
                "Internal Medicine", "Cardiology", "Family Medicine", "Emergency Medicine",
            ]),
            "primary_icd10_code": dx[0],
            "primary_diagnosis": dx[1],
            "diagnosis_chapter": "Various",
        })
    return pd.DataFrame(rows)


def _build_claims(n: int = 3500) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=180)
    rows = []
    statuses = ["approved", "denied", "partially_paid", "submitted", "pending_review"]
    weights = [0.62, 0.10, 0.09, 0.10, 0.09]
    for i in range(n):
        h = random.choice(HOSPITALS)
        py = random.choice(PAYERS)
        d = start + timedelta(seconds=random.randint(0, int((end - start).total_seconds())))
        st_ = random.choices(statuses, weights=weights, k=1)[0]
        billed = round(random.uniform(50, 5000), 2)
        if st_ == "approved":
            allowed = round(billed * random.uniform(0.78, 0.95), 2)
            paid = allowed
        elif st_ == "denied":
            allowed, paid = 0.0, 0.0
        elif st_ == "partially_paid":
            allowed = round(billed * random.uniform(0.4, 0.7), 2)
            paid = allowed
        else:
            allowed, paid = 0.0, 0.0
        dx = random.choice(DIAGNOSES)
        rows.append({
            "claim_sk": i + 1,
            "claim_number": f"CLM-{d.year}-{i:08d}",
            "status": st_,
            "is_denied": st_ == "denied",
            "is_paid_in_full": paid == billed and billed > 0,
            "days_to_decision": random.randint(2, 30) if st_ in ("approved", "denied", "partially_paid") else None,
            "line_count": random.choice([1, 2, 3, 4]),
            "billed_amount": billed,
            "allowed_amount": allowed,
            "paid_amount": paid,
            "denied_amount": billed - allowed if st_ != "approved" else 0.0,
            "patient_responsibility": round(billed - paid, 2),
            "currency": "EGP",
            "service_date": d.date(),
            "service_year": d.year,
            "service_month": d.month,
            "decision_date": (d + timedelta(days=random.randint(2, 30))).date() if st_ != "submitted" else None,
            "payer_name": py,
            "is_government_payer": py == "Health Insurance Org. (HIO)",
            "hospital_name": h[0],
            "facility_type": h[3],
            "patient_age_band": random.choice(["0-17", "18-34", "35-49", "50-64", "65-79", "80+"]),
            "patient_gender": random.choice(["M", "F"]),
            "patient_governorate": h[1],
            "primary_icd10_code": dx[0],
            "primary_diagnosis": dx[1],
        })
    return pd.DataFrame(rows)


def _build_vitals(n_minutes: int = 1440) -> pd.DataFrame:
    """24h of minute-level summaries across 50 devices."""
    devices = [(f"DEV-{i:03d}", f"Bed {chr(65 + i % 5)}-{i:02d}",
                random.choice(HOSPITALS), str(uuid.uuid4()),
                f"Patient {i:05d}") for i in range(50)]
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    rows = []
    for d_id, bed, hosp, pat_id, pat_name in devices:
        for i in range(n_minutes // 50):
            ts = end - timedelta(minutes=random.randint(0, n_minutes))
            anomaly = random.random() < 0.04
            kind = random.choice([
                "tachycardia", "bradycardia", "hypoxia", "hypertension", "fever",
            ]) if anomaly else None
            rows.append({
                "minute_start_utc": ts,
                "device_id": d_id,
                "bed_number": bed,
                "patient_id": pat_id,
                "patient_name": pat_name,
                "hospital_name": hosp[0],
                "hospital_governorate": hosp[1],
                "sample_count": random.randint(50, 60),
                "heart_rate_avg": round(random.gauss(80 if not anomaly else 145, 5), 1),
                "heart_rate_max": round(random.gauss(85, 5), 1),
                "heart_rate_min": round(random.gauss(75, 5), 1),
                "spo2_avg": round(random.gauss(96 if not anomaly else 86, 1), 1),
                "spo2_min": round(random.gauss(95 if not anomaly else 84, 1), 1),
                "systolic_avg": round(random.gauss(120 if not anomaly else 175, 8), 1),
                "diastolic_avg": round(random.gauss(78, 5), 1),
                "respiratory_rate_avg": round(random.gauss(16, 1.5), 1),
                "temperature_c_avg": round(random.gauss(36.8 if not anomaly else 39.6, 0.2), 2),
                "temperature_c_max": round(random.gauss(36.9 if not anomaly else 39.8, 0.2), 2),
                "anomaly_event_count": random.randint(1, 12) if anomaly else 0,
                "primary_anomaly_kind": kind,
            })
    return pd.DataFrame(rows)


def main() -> int:
    print("Building demo datasets ...", file=sys.stderr)
    enc = _build_encounters()
    enc.to_parquet(OUT / "vw_encounter_enriched.parquet", index=False)
    print(f"  encounters: {len(enc):,}", file=sys.stderr)

    cl = _build_claims()
    cl.to_parquet(OUT / "vw_claim_enriched.parquet", index=False)
    print(f"  claims    : {len(cl):,}", file=sys.stderr)

    vs = _build_vitals()
    vs.to_parquet(OUT / "vw_vital_signs_minute.parquet", index=False)
    print(f"  vitals    : {len(vs):,}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
