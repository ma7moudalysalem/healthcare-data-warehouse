"""Tests for src.generators.generate_claims."""
import json
import os
from pathlib import Path

from src.generators.generate_claims import _generate_one, generate
from src.generators.common import seed_all


def test_generate_one_has_required_fields():
    seed_all(42)
    from datetime import datetime
    rec = _generate_one(1, datetime(2025, 1, 1), datetime(2026, 1, 1))
    expected = {
        "claim_id", "claim_number", "patient_id", "encounter_id",
        "provider_npi", "hospital_code", "carrier", "service_date",
        "status", "billed_amount", "allowed_amount", "paid_amount",
        "patient_responsibility", "currency", "line_items",
    }
    missing = expected - rec.keys()
    assert not missing, f"missing fields: {missing}"


def test_generate_one_status_invariants():
    """Each terminal status implies a specific shape of money fields."""
    seed_all(123)
    from datetime import datetime
    for _ in range(200):
        r = _generate_one(1, datetime(2025, 1, 1), datetime(2026, 1, 1))
        if r["status"] == "approved":
            assert r["paid_amount"] > 0
            assert r["paid_amount"] == r["allowed_amount"]
        elif r["status"] == "denied":
            assert r["paid_amount"] == 0
            assert r["allowed_amount"] == 0
            assert r["denial_reason"] is not None
        elif r["status"] == "partially_paid":
            assert 0 < r["paid_amount"] < r["billed_amount"]


def test_generate_writes_jsonl(tmp_path: Path):
    seed_all(7)
    out = tmp_path / "claims.jsonl"
    generate(50, out)
    assert out.exists()
    with out.open() as f:
        lines = [json.loads(line) for line in f]
    assert len(lines) == 50
    assert all("claim_id" in r for r in lines)
    # Carrier mix should include at least 3 distinct carriers in 50 draws.
    assert len({r["carrier"] for r in lines}) >= 3


def test_generate_is_deterministic_with_seed(tmp_path: Path):
    seed_all(99)
    a = tmp_path / "a.jsonl"
    generate(20, a)
    seed_all(99)
    b = tmp_path / "b.jsonl"
    generate(20, b)
    assert a.read_text() == b.read_text()
