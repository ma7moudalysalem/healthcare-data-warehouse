"""Lightweight Event Hubs stream consumer -> Azure SQL (no Spark).

A pure-Python alternative to vitals_eventhub_to_sql.py for environments where a
Spark container can't be built/run. Reads the vital-signs stream from Azure
Event Hubs, aggregates to 1-minute-per-device buckets in memory, and upserts
them into dw.fact_vital_signs_minute every few seconds so the dashboard's
"Live Vital Signs" page reflects the live stream.

Env: EVENT_HUB_CONNECTION_STRING, EVENT_HUB_NAME, HCDW_SQL_SERVER/DB/USER/PASSWORD
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime

import pyodbc
from azure.eventhub import EventHubConsumerClient

HOSP_SK = {"HSP-CAI-01": 1, "HSP-CAI-02": 2, "HSP-GIZ-01": 3, "HSP-ALX-01": 4, "HSP-MNF-01": 5}
N_PATIENTS = 2000

_buckets: dict = {}
_lock = threading.Lock()


def _patient_sk(dev: str) -> int:
    return (int(hashlib.md5(dev.encode()).hexdigest()[:12], 16) % N_PATIENTS) + 1


def _vital_sk(dev: str, minute_iso: str) -> int:
    return 1_000_000 + int(hashlib.md5(f"{dev}|{minute_iso}".encode()).hexdigest()[:15], 16) % (10**17)


def _sql_conn():
    cs = ("DRIVER={ODBC Driver 18 for SQL Server};"
          f"SERVER={os.environ['HCDW_SQL_SERVER']};DATABASE={os.environ['HCDW_SQL_DB']};"
          f"UID={os.environ['HCDW_SQL_USER']};PWD={os.environ['HCDW_SQL_PASSWORD']};"
          "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60")
    return pyodbc.connect(cs, autocommit=False)


def on_event(partition_context, event):
    if event is None:
        return
    try:
        e = json.loads(event.body_as_str())
    except Exception:  # noqa: BLE001
        return
    ts = datetime.fromisoformat(e["event_time"].replace("Z", "+00:00"))
    minute = ts.replace(second=0, microsecond=0, tzinfo=None)
    key = (e["device_id"], minute)
    with _lock:
        b = _buckets.get(key)
        if b is None:
            b = {"hospital_code": e.get("hospital_code"), "bed_number": e.get("bed_number"),
                 "n": 0, "hr": [], "spo2": [], "sys": [], "dia": [], "rr": [], "temp": [],
                 "anom": 0, "kind": None}
            _buckets[key] = b
        b["n"] += 1
        b["hr"].append(e["heart_rate_bpm"])
        b["spo2"].append(e["spo2_pct"])
        b["sys"].append(e["systolic_bp"])
        b["dia"].append(e["diastolic_bp"])
        b["rr"].append(e["respiratory_rate"])
        b["temp"].append(e["temperature_c"])
        if e.get("anomaly_flag"):
            b["anom"] += 1
            if not b["kind"]:
                b["kind"] = e.get("anomaly_kind")


def _flush_loop():
    while True:
        time.sleep(15)
        with _lock:
            snapshot = list(_buckets.items())
            # prune buckets older than 6 minutes
            cutoff = datetime.utcnow().replace(tzinfo=None)
            for k in [k for k in _buckets if (cutoff - k[1]).total_seconds() > 360]:
                _buckets.pop(k, None)
        if not snapshot:
            continue
        try:
            cn = _sql_conn()
            cur = cn.cursor()
            for (dev, minute), b in snapshot:
                if not b["hr"]:
                    continue
                avg = lambda xs: round(sum(xs) / len(xs), 2)  # noqa: E731
                cur.execute("DELETE FROM dw.fact_vital_signs_minute WHERE device_id=? AND minute_start_utc=?",
                            dev, minute)
                cur.execute(
                    "INSERT INTO dw.fact_vital_signs_minute (vital_sk, patient_sk, hospital_sk, device_id, "
                    "bed_number, minute_start_utc, date_sk, sample_count, heart_rate_avg, heart_rate_max, "
                    "heart_rate_min, spo2_avg, spo2_min, systolic_avg, diastolic_avg, respiratory_rate_avg, "
                    "temperature_c_avg, temperature_c_max, anomaly_event_count, primary_anomaly_kind) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    _vital_sk(dev, minute.isoformat()), _patient_sk(dev),
                    HOSP_SK.get(b["hospital_code"], 1), dev, b["bed_number"], minute,
                    int(minute.strftime("%Y%m%d")), b["n"],
                    avg(b["hr"]), round(max(b["hr"]), 1), round(min(b["hr"]), 1),
                    avg(b["spo2"]), round(min(b["spo2"]), 1),
                    avg(b["sys"]), avg(b["dia"]), avg(b["rr"]),
                    avg(b["temp"]), round(max(b["temp"]), 2), b["anom"], b["kind"])
            cn.commit()
            cn.close()
            print(f"[consumer] upserted {len(snapshot)} device-minutes", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[consumer] flush error: {exc}", flush=True)


def main() -> int:
    conn = os.environ["EVENT_HUB_CONNECTION_STRING"]
    name = os.environ.get("EVENT_HUB_NAME", "vitals-stream")
    threading.Thread(target=_flush_loop, daemon=True).start()
    client = EventHubConsumerClient.from_connection_string(
        conn, consumer_group="$Default", eventhub_name=name)
    print("[consumer] receiving from Event Hubs…", flush=True)
    with client:
        client.receive(on_event=on_event, starting_position="-1")  # -1 = latest
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
