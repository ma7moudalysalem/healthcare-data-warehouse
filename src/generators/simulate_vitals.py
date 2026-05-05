"""Continuously emit synthetic patient vital signs to Azure Event Hubs.

Each "device" (we simulate ~50 by default) represents a bedside monitor
sending heart rate, SpO2, blood pressure, respiratory rate and temperature
readings. The generator drifts each device's baseline slowly over time and
occasionally injects an anomaly (sudden tachycardia, hypoxia spike, etc.) so
the streaming anomaly detector has something to fire on.

If the EVENT_HUB_CONNECTION_STRING env var is missing the script falls back to
stdout, which is convenient for local testing without provisioning Azure.

Usage:
    python -m src.generators.simulate_vitals --devices 50 --rate 1.0
    python -m src.generators.simulate_vitals --devices 5 --rate 5.0 --duration 60
"""
from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

from .common import HOSPITAL_NETWORK, seed_all


@dataclass
class Device:
    device_id: str
    patient_id: str
    hospital_code: str
    bed_number: str
    # Physiological baselines, individualized per device.
    hr_baseline: float = 75.0
    spo2_baseline: float = 98.0
    sbp_baseline: float = 120.0
    dbp_baseline: float = 78.0
    rr_baseline: float = 16.0
    temp_baseline: float = 36.8
    # Every device has a small chance to "go anomalous" each tick, and once
    # that happens the anomaly persists for a few seconds.
    anomaly_until: float = field(default=0.0)
    anomaly_kind: str | None = None


_VITAL_BOUNDS = {
    "heart_rate_bpm": (30, 200),
    "spo2_pct": (70, 100),
    "systolic_bp": (70, 220),
    "diastolic_bp": (40, 130),
    "respiratory_rate": (6, 40),
    "temperature_c": (33.0, 41.5),
}


def _build_devices(n: int) -> list[Device]:
    devs = []
    hospitals = [h for h in HOSPITAL_NETWORK if not h.is_clinic]
    for i in range(n):
        h = random.choice(hospitals)
        devs.append(Device(
            device_id=f"DEV-{h.code}-{i:03d}",
            patient_id=str(uuid.uuid4()),
            hospital_code=h.code,
            bed_number=f"{random.choice('ABCDE')}-{random.randint(1, 40):02d}",
            hr_baseline=random.uniform(62, 88),
            spo2_baseline=random.uniform(95, 99),
            sbp_baseline=random.uniform(110, 135),
            dbp_baseline=random.uniform(70, 85),
            rr_baseline=random.uniform(12, 20),
            temp_baseline=random.uniform(36.4, 37.2),
        ))
    return devs


def _maybe_start_anomaly(dev: Device, now: float) -> None:
    if dev.anomaly_until > now:
        return
    # ~0.4% chance per tick to start a new anomaly.
    if random.random() < 0.004:
        dev.anomaly_kind = random.choice([
            "tachycardia", "bradycardia", "hypoxia", "hypertension", "fever",
        ])
        dev.anomaly_until = now + random.uniform(5, 25)


def _sample(dev: Device, now: float) -> dict:
    _maybe_start_anomaly(dev, now)
    hr = random.gauss(dev.hr_baseline, 3.0)
    spo2 = random.gauss(dev.spo2_baseline, 0.8)
    sbp = random.gauss(dev.sbp_baseline, 4.0)
    dbp = random.gauss(dev.dbp_baseline, 3.0)
    rr = random.gauss(dev.rr_baseline, 1.2)
    temp = random.gauss(dev.temp_baseline, 0.15)

    if dev.anomaly_until > now and dev.anomaly_kind:
        if dev.anomaly_kind == "tachycardia":
            hr += random.uniform(35, 70)
        elif dev.anomaly_kind == "bradycardia":
            hr -= random.uniform(25, 40)
        elif dev.anomaly_kind == "hypoxia":
            spo2 -= random.uniform(8, 18)
        elif dev.anomaly_kind == "hypertension":
            sbp += random.uniform(35, 60)
            dbp += random.uniform(15, 30)
        elif dev.anomaly_kind == "fever":
            temp += random.uniform(1.5, 3.0)
    else:
        dev.anomaly_kind = None

    def _clip(name: str, value: float) -> float:
        lo, hi = _VITAL_BOUNDS[name]
        return max(lo, min(hi, value))

    return {
        "event_id": str(uuid.uuid4()),
        "event_time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "device_id": dev.device_id,
        "patient_id": dev.patient_id,
        "hospital_code": dev.hospital_code,
        "bed_number": dev.bed_number,
        "heart_rate_bpm": round(_clip("heart_rate_bpm", hr), 1),
        "spo2_pct": round(_clip("spo2_pct", spo2), 1),
        "systolic_bp": round(_clip("systolic_bp", sbp), 1),
        "diastolic_bp": round(_clip("diastolic_bp", dbp), 1),
        "respiratory_rate": round(_clip("respiratory_rate", rr), 1),
        "temperature_c": round(_clip("temperature_c", temp), 2),
        "anomaly_flag": dev.anomaly_kind is not None,
        "anomaly_kind": dev.anomaly_kind,
    }


def _stream_forever(devices: list[Device], rate_hz: float, duration_s: float | None) -> Iterator[dict]:
    interval = 1.0 / rate_hz
    started = time.monotonic()
    while True:
        if duration_s is not None and (time.monotonic() - started) >= duration_s:
            return
        loop_start = time.monotonic()
        now = time.time()
        for dev in devices:
            yield _sample(dev, now)
        sleep_for = interval - (time.monotonic() - loop_start)
        if sleep_for > 0:
            time.sleep(sleep_for)


def _make_eventhub_sender():
    """Lazily build an Event Hubs sender. Returns None if not configured."""
    conn = os.environ.get("EVENT_HUB_CONNECTION_STRING")
    name = os.environ.get("EVENT_HUB_NAME", "vitals-stream")
    if not conn:
        return None
    try:
        from azure.eventhub import EventData, EventHubProducerClient
    except ImportError:
        print("azure-eventhub not installed; falling back to stdout.", file=sys.stderr)
        return None

    producer = EventHubProducerClient.from_connection_string(conn, eventhub_name=name)

    def _send(record: dict) -> None:
        batch = producer.create_batch()
        batch.add(EventData(json.dumps(record)))
        producer.send_batch(batch)

    _send.close = producer.close  # type: ignore[attr-defined]
    return _send


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream simulated patient vital signs.")
    parser.add_argument("--devices", type=int, default=50)
    parser.add_argument("--rate", type=float, default=1.0,
                        help="Readings per second per device.")
    parser.add_argument("--duration", type=float, default=None,
                        help="Run for N seconds then exit. Default: forever.")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--stdout", action="store_true",
                        help="Force stdout output even if Event Hubs is configured.")
    args = parser.parse_args()

    if args.seed is not None:
        seed_all(args.seed)
    else:
        seed_all()

    devices = _build_devices(args.devices)
    sender = None if args.stdout else _make_eventhub_sender()

    if sender is None:
        print(f"Streaming to stdout: {args.devices} devices @ {args.rate} Hz", file=sys.stderr)
    else:
        print(f"Streaming to Event Hubs: {args.devices} devices @ {args.rate} Hz", file=sys.stderr)

    stop = {"now": False}

    def _on_signal(_sig, _frm):
        stop["now"] = True

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    try:
        n = 0
        for record in _stream_forever(devices, args.rate, args.duration):
            if stop["now"]:
                break
            if sender is None:
                print(json.dumps(record))
            else:
                sender(record)
            n += 1
            if n % 1000 == 0:
                print(f"  ... {n:,} events emitted", file=sys.stderr)
    finally:
        if sender is not None and hasattr(sender, "close"):
            sender.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
