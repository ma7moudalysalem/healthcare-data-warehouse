"""Shared helpers for the synthetic data generators.

The generators are run independently (claims, vitals, provider API), but they
share configuration loading, RNG seeding and a small ICD-10 / RxNorm reference
catalogue. Keeping it here avoids three slightly different copies drifting
apart.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEANED_DIR = DATA_DIR / "cleaned"
GOLD_DIR = DATA_DIR / "gold"

DEFAULT_SEED = int(os.environ.get("HCDW_SEED", "20240212"))


def ensure_dirs() -> None:
    for d in (RAW_DIR, CLEANED_DIR, GOLD_DIR):
        d.mkdir(parents=True, exist_ok=True)


def seed_all(seed: int = DEFAULT_SEED) -> None:
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    try:
        from faker import Faker

        Faker.seed(seed)
    except ImportError:
        pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def deterministic_uuid() -> str:
    """UUID4-shaped string sourced from `random` so seeded runs are reproducible.

    `uuid.uuid4()` reads from os.urandom and ignores random.seed(), which
    breaks deterministic regeneration. Build a v4 UUID by hand using the
    seeded RNG instead.
    """
    bits = random.getrandbits(128)
    # Stamp version (4) and variant (10xx) bits per RFC 4122 sec 4.1.3 / 4.1.1.
    bits &= ~(0xF << 76)
    bits |= 0x4 << 76
    bits &= ~(0xC << 62)
    bits |= 0x8 << 62
    return str(__import__("uuid").UUID(int=bits))


def random_datetime_between(start: datetime, end: datetime) -> datetime:
    delta = end - start
    offset = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=offset)


# A small but realistic catalogue. Real Synthea output uses the full code sets,
# but for the custom claims/vitals generators we only need a representative slice.
ICD10_CODES = [
    ("I10", "Essential (primary) hypertension"),
    ("E11.9", "Type 2 diabetes mellitus without complications"),
    ("J45.909", "Unspecified asthma, uncomplicated"),
    ("N39.0", "Urinary tract infection, site not specified"),
    ("M54.5", "Low back pain"),
    ("R51", "Headache"),
    ("J18.9", "Pneumonia, unspecified organism"),
    ("K21.9", "Gastro-esophageal reflux disease without esophagitis"),
    ("F32.9", "Major depressive disorder, single episode, unspecified"),
    ("E78.5", "Hyperlipidemia, unspecified"),
    ("I25.10", "Atherosclerotic heart disease of native coronary artery"),
    ("N18.3", "Chronic kidney disease, stage 3"),
    ("G43.909", "Migraine, unspecified, not intractable, without status migrainosus"),
    ("R07.9", "Chest pain, unspecified"),
    ("S52.501A", "Unspecified fracture of the lower end of right radius, initial"),
]

RXNORM_DRUGS = [
    ("314076", "Lisinopril 10 MG Oral Tablet"),
    ("860975", "Metformin hydrochloride 500 MG Oral Tablet"),
    ("197361", "Albuterol 0.09 MG/ACTUAT Metered Dose Inhaler"),
    ("197517", "Amoxicillin 500 MG Oral Capsule"),
    ("197805", "Atorvastatin 20 MG Oral Tablet"),
    ("310965", "Ibuprofen 400 MG Oral Tablet"),
    ("198440", "Acetaminophen 500 MG Oral Tablet"),
    ("314231", "Omeprazole 20 MG Oral Capsule"),
    ("313782", "Sertraline 50 MG Oral Tablet"),
    ("866924", "Hydrochlorothiazide 25 MG Oral Tablet"),
]

CPT_PROCEDURES = [
    ("99213", "Office visit, established patient, level 3", 95.00),
    ("99214", "Office visit, established patient, level 4", 145.00),
    ("99221", "Initial hospital care, level 1", 210.00),
    ("99284", "Emergency dept visit, level 4", 320.00),
    ("80053", "Comprehensive metabolic panel", 45.00),
    ("85025", "Complete blood count with differential", 28.00),
    ("71046", "Chest X-ray, 2 views", 110.00),
    ("93000", "Electrocardiogram, complete", 85.00),
    ("70551", "MRI brain without contrast", 825.00),
    ("36415", "Routine venipuncture", 12.00),
]

INSURANCE_CARRIERS = [
    "Misr Insurance",
    "Allianz Egypt",
    "AXA Egypt",
    "Bupa Global",
    "MetLife Egypt",
    "Self-Pay",
]

CLAIM_STATUSES = ["submitted", "approved", "denied", "partially_paid", "pending_review"]

DENIAL_REASONS = [
    "Service not covered under plan",
    "Pre-authorization missing",
    "Diagnosis code does not justify service",
    "Duplicate claim",
    "Patient eligibility lapsed",
    None,  # only used when status != denied
]


@dataclass
class Hospital:
    code: str
    name: str
    city: str
    beds: int
    is_clinic: bool


HOSPITAL_NETWORK: list[Hospital] = [
    Hospital("HSP-CAI-01", "Cairo Central Hospital", "Cairo", 320, False),
    Hospital("HSP-CAI-02", "Nile Heart Institute", "Cairo", 180, False),
    Hospital("HSP-GIZ-01", "Giza Specialty Hospital", "Giza", 240, False),
    Hospital("HSP-ALX-01", "Alexandria Bayside Medical", "Alexandria", 280, False),
    Hospital("HSP-MNF-01", "Menoufia Regional Medical", "Menoufia", 150, False),
] + [
    Hospital(f"CLN-{c[:3].upper()}-{i:02d}", f"{c} Family Clinic {i}", c, 0, True)
    for i, c in enumerate(
        ["Cairo", "Cairo", "Giza", "Giza", "Alexandria", "Alexandria",
         "Menoufia", "Sharqia", "Dakahlia", "Qalyubia",
         "Gharbia", "Beheira", "Aswan", "Luxor", "Suez",
         "Fayoum", "Minya", "Beni Suef", "Asyut", "Sohag"],
        start=1,
    )
]


def hospitals() -> Iterable[Hospital]:
    return iter(HOSPITAL_NETWORK)


def pick_weighted(items: list, weights: list[float]):
    return random.choices(items, weights=weights, k=1)[0]
