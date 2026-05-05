"""Tests for src.generators.simulate_vitals."""
from src.generators.simulate_vitals import _build_devices, _sample
from src.generators.common import seed_all


def test_build_devices_count():
    seed_all(1)
    devices = _build_devices(10)
    assert len(devices) == 10
    # All assigned to active hospitals (not clinics).
    for d in devices:
        assert d.device_id.startswith("DEV-HSP-")


def test_sample_returns_clipped_values():
    seed_all(2)
    devices = _build_devices(1)
    dev = devices[0]
    rec = _sample(dev, now=0.0)
    assert 30 <= rec["heart_rate_bpm"] <= 200
    assert 70 <= rec["spo2_pct"] <= 100
    assert 70 <= rec["systolic_bp"] <= 220
    assert 33 <= rec["temperature_c"] <= 41.5


def test_sample_carries_device_metadata():
    seed_all(3)
    devices = _build_devices(1)
    dev = devices[0]
    rec = _sample(dev, now=0.0)
    assert rec["device_id"] == dev.device_id
    assert rec["patient_id"] == dev.patient_id
    assert rec["hospital_code"] == dev.hospital_code


def test_anomaly_triggers_eventually():
    """Forcing high RNG draws should kick off an anomaly within a few ticks."""
    seed_all(123)
    devices = _build_devices(5)
    saw_anomaly = False
    for _ in range(2000):
        for d in devices:
            r = _sample(d, now=0.0)
            if r["anomaly_flag"]:
                saw_anomaly = True
                break
        if saw_anomaly:
            break
    assert saw_anomaly, "anomaly should fire at least once over 10K samples"
