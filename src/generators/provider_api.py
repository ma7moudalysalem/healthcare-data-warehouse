"""Mock external Provider Reference API.

In production a hospital network would pull provider/credentialing data from
a HRIS or a payer's eligibility service. For the warehouse demo we expose a
small Flask service that returns deterministic provider records by NPI.

The same data is also dumped to data/raw/providers.json on startup so the
batch ETL has a static source to consume.

Run:
    python -m src.generators.provider_api
    curl http://localhost:5000/api/providers/1234567890
"""
from __future__ import annotations

import json
import os
import random
from datetime import date, timedelta

from faker import Faker
from flask import Flask, abort, jsonify

from .common import HOSPITAL_NETWORK, RAW_DIR, ensure_dirs, seed_all

app = Flask(__name__)
fake = Faker()

SPECIALTIES = [
    "Internal Medicine", "Family Medicine", "Cardiology", "Pediatrics",
    "Emergency Medicine", "Obstetrics & Gynecology", "Orthopedics",
    "Radiology", "Anesthesiology", "Psychiatry", "Dermatology",
    "Endocrinology", "Gastroenterology", "Neurology", "Oncology",
]


def _build_provider(npi: str | None = None) -> dict:
    npi = npi or fake.numerify("##########")
    hospital = random.choice(HOSPITAL_NETWORK)
    hire_year = random.randint(2005, 2024)
    return {
        "npi": npi,
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "credential": random.choice(["MD", "DO", "MBBS", "PhD-MD"]),
        "specialty": random.choice(SPECIALTIES),
        "primary_facility_code": hospital.code,
        "facility_name": hospital.name,
        "city": hospital.city,
        "license_number": fake.bothify("EG-#######"),
        "license_state": "EG",
        "license_expiry": (date.today() + timedelta(days=random.randint(60, 1100))).isoformat(),
        "hire_date": date(hire_year, random.randint(1, 12), random.randint(1, 28)).isoformat(),
        "is_active": random.random() > 0.06,
        "phone": fake.phone_number(),
        "email": fake.unique.company_email(),
    }


# Build a fixed registry on startup so /providers/<npi> stays stable across calls.
PROVIDER_REGISTRY: dict[str, dict] = {}


def _bootstrap_registry(n: int = 800) -> None:
    seed_all()
    fake.unique.clear()
    while len(PROVIDER_REGISTRY) < n:
        p = _build_provider()
        PROVIDER_REGISTRY[p["npi"]] = p

    # Persist for the batch loaders.
    ensure_dirs()
    out = RAW_DIR / "providers.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(list(PROVIDER_REGISTRY.values()), f, ensure_ascii=False, indent=2)


@app.route("/health")
def health():
    return {"status": "ok", "providers": len(PROVIDER_REGISTRY)}


@app.route("/api/providers")
def list_providers():
    # Paginated listing - the ETL pulls everything, but a real client wouldn't.
    # Keep the response under control: 100 per page.
    page = int(request_arg("page", 1))
    page_size = min(int(request_arg("page_size", 100)), 500)
    items = list(PROVIDER_REGISTRY.values())
    start = (page - 1) * page_size
    end = start + page_size
    return jsonify({
        "page": page,
        "page_size": page_size,
        "total": len(items),
        "items": items[start:end],
    })


@app.route("/api/providers/<npi>")
def get_provider(npi: str):
    p = PROVIDER_REGISTRY.get(npi)
    if not p:
        abort(404, description=f"NPI {npi} not found")
    return jsonify(p)


def request_arg(key: str, default):
    from flask import request
    val = request.args.get(key)
    if val is None or val == "":
        return default
    return val


def main() -> int:
    _bootstrap_registry()
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    print(f"Provider API ready: http://{host}:{port}/api/providers ({len(PROVIDER_REGISTRY)} providers)")
    print(f"Static dump written to {RAW_DIR / 'providers.json'}")
    app.run(host=host, port=port, debug=debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
