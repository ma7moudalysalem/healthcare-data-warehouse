"""Generate synthetic insurance claims that line up with Synthea encounters.

We don't have a billing module bundled with Synthea, so the warehouse needs
something to populate `fact_claims`. This script produces ~200K JSON claims
keyed by encounter_id and patient_id, with carrier mix and denial rates that
roughly match the figures the project proposal used for sizing.

Usage:
    python -m src.generators.generate_claims --count 200000 --out data/raw/claims.json

The script is deterministic given a seed (HCDW_SEED env var) so reruns produce
the same file. That matters for reproducible CI runs.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

from .common import (
    CLAIM_STATUSES,
    CPT_PROCEDURES,
    DENIAL_REASONS,
    HOSPITAL_NETWORK,
    ICD10_CODES,
    INSURANCE_CARRIERS,
    RAW_DIR,
    ensure_dirs,
    pick_weighted,
    seed_all,
)

fake = Faker()


# Carrier market share - rough numbers from the project proposal.
CARRIER_WEIGHTS = [0.27, 0.18, 0.16, 0.12, 0.13, 0.14]
STATUS_WEIGHTS = [0.10, 0.62, 0.11, 0.09, 0.08]  # submitted, approved, denied, partial, pending


def _generate_one(claim_idx: int, start_date: datetime, end_date: datetime) -> dict:
    hospital = random.choice(HOSPITAL_NETWORK)
    carrier = pick_weighted(INSURANCE_CARRIERS, CARRIER_WEIGHTS)
    status = pick_weighted(CLAIM_STATUSES, STATUS_WEIGHTS)

    # Each claim has 1-4 line items. The total billed is the sum of line item
    # charges, and the allowed amount depends on status.
    n_items = random.choices([1, 2, 3, 4], weights=[0.45, 0.30, 0.18, 0.07])[0]
    line_items = []
    billed_total = 0.0
    for _ in range(n_items):
        cpt_code, cpt_desc, base_charge = random.choice(CPT_PROCEDURES)
        # Real billing has variable contracted rates; jitter +/- 15%.
        charge = round(base_charge * random.uniform(0.85, 1.15), 2)
        billed_total += charge
        line_items.append({
            "cpt_code": cpt_code,
            "description": cpt_desc,
            "billed_amount": charge,
            "units": 1,
        })

    if status == "approved":
        allowed = round(billed_total * random.uniform(0.78, 0.95), 2)
        paid = allowed
        patient_responsibility = round(billed_total - paid, 2)
        denial_reason = None
    elif status == "denied":
        allowed = 0.0
        paid = 0.0
        patient_responsibility = round(billed_total, 2)
        denial_reason = random.choice([d for d in DENIAL_REASONS if d])
    elif status == "partially_paid":
        allowed = round(billed_total * random.uniform(0.40, 0.70), 2)
        paid = allowed
        patient_responsibility = round(billed_total - paid, 2)
        denial_reason = None
    else:  # submitted / pending_review
        allowed = 0.0
        paid = 0.0
        patient_responsibility = 0.0
        denial_reason = None

    diagnosis_code, diagnosis_desc = random.choice(ICD10_CODES)
    service_date = start_date + timedelta(
        seconds=random.randint(0, int((end_date - start_date).total_seconds()))
    )

    submission_lag = timedelta(days=random.randint(0, 14))
    decision_lag = timedelta(days=random.randint(2, 35)) if status not in ("submitted", "pending_review") else None

    return {
        "claim_id": str(uuid.uuid4()),
        "claim_number": f"CLM-{service_date.year}-{claim_idx:08d}",
        # Patient + encounter ids reference Synthea output. They're random
        # uuids here; the Silver join will surface unmatched claims as a DQ
        # signal.
        "patient_id": str(uuid.uuid4()),
        "encounter_id": str(uuid.uuid4()),
        "provider_npi": fake.numerify(text="##########"),
        "hospital_code": hospital.code,
        "carrier": carrier,
        "policy_number": fake.bothify(text="??-########", letters="ABCDEFGH"),
        "service_date": service_date.date().isoformat(),
        "submission_date": (service_date + submission_lag).date().isoformat(),
        "decision_date": (
            (service_date + submission_lag + decision_lag).date().isoformat()
            if decision_lag else None
        ),
        "status": status,
        "denial_reason": denial_reason,
        "primary_diagnosis_code": diagnosis_code,
        "primary_diagnosis_description": diagnosis_desc,
        "billed_amount": round(billed_total, 2),
        "allowed_amount": allowed,
        "paid_amount": paid,
        "patient_responsibility": patient_responsibility,
        "currency": "EGP",
        "line_items": line_items,
    }


def generate(count: int, output_path: Path) -> Path:
    ensure_dirs()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    end = datetime(2026, 1, 1)
    start = end - timedelta(days=730)  # 2 years of history

    # Stream JSON Lines so we don't blow up memory on 200K records.
    with output_path.open("w", encoding="utf-8") as f:
        for i in range(1, count + 1):
            rec = _generate_one(i, start, end)
            f.write(json.dumps(rec, ensure_ascii=False))
            f.write("\n")
            if i % 25000 == 0:
                print(f"  ... {i:,} claims written", file=sys.stderr)

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic insurance claims (JSONL).")
    parser.add_argument("--count", type=int, default=200_000)
    parser.add_argument(
        "--out",
        type=Path,
        default=RAW_DIR / "claims.jsonl",
        help="Output path. Default: data/raw/claims.jsonl",
    )
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    if args.seed is not None:
        seed_all(args.seed)
    else:
        seed_all()

    print(f"Generating {args.count:,} claims -> {args.out}", file=sys.stderr)
    out = generate(args.count, args.out)
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"Done. {size_mb:.1f} MB on disk.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
