"""Cloud streaming consumer: Event Hubs -> Azure SQL, self-bootstrapping.

Same logic as vitals_eventhub_consumer.py but (a) uses pymssql (no system ODBC
driver needed) and (b) pip-installs its own deps on start, so it can run on a
stock `python:3.11-slim` Container App with NO custom image build — the whole
script is passed in via the CONSUMER_B64 env var. This is the workaround for a
subscription where ACR Tasks are blocked and local Docker is unavailable.

Env: EVENT_HUB_CONNECTION_STRING, EVENT_HUB_NAME, HCDW_SQL_SERVER/DB/USER/PASSWORD
"""
import subprocess
import sys

# --- self-bootstrap deps (runs on a bare python image) ---
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                       "--root-user-action=ignore", "azure-eventhub", "pymssql"])

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402

import pymssql  # noqa: E402
from azure.eventhub import EventHubConsumerClient  # noqa: E402

HOSP_SK = {"HSP-CAI-01": 1, "HSP-CAI-02": 2, "HSP-GIZ-01": 3, "HSP-ALX-01": 4, "HSP-MNF-01": 5}
N_PATIENTS = 2000
_buckets = {}
_lock = threading.Lock()


def _patient_sk(dev):
    return (int(hashlib.md5(dev.encode()).hexdigest()[:12], 16) % N_PATIENTS) + 1


def _vital_sk(dev, minute_iso):
    return 1_000_000 + int(hashlib.md5(f"{dev}|{minute_iso}".encode()).hexdigest()[:15], 16) % (10**17)


def _conn():
    return pymssql.connect(
        server=os.environ["HCDW_SQL_SERVER"], user=os.environ["HCDW_SQL_USER"],
        password=os.environ["HCDW_SQL_PASSWORD"], database=os.environ["HCDW_SQL_DB"],
        port=1433, tds_version="7.4")


def on_event(ctx, event):
    if event is None:
        return
    try:
        e = json.loads(event.body_as_str())
    except Exception:
        return
    ts = datetime.fromisoformat(e["event_time"].replace("Z", "+00:00"))
    minute = ts.replace(second=0, microsecond=0, tzinfo=None)
    key = (e["device_id"], minute)
    with _lock:
        b = _buckets.get(key)
        if b is None:
            b = {"hc": e.get("hospital_code"), "bed": e.get("bed_number"),
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
            snap = list(_buckets.items())
            cutoff = datetime.utcnow()
            for k in [k for k in _buckets if (cutoff - k[1]).total_seconds() > 360]:
                _buckets.pop(k, None)
        if not snap:
            continue
        try:
            cn = _conn()
            cur = cn.cursor()
            for (dev, minute), b in snap:
                if not b["hr"]:
                    continue
                avg = lambda xs: round(sum(xs) / len(xs), 2)  # noqa: E731
                cur.execute("DELETE FROM dw.fact_vital_signs_minute WHERE device_id=%s AND minute_start_utc=%s",
                            (dev, minute))
                cur.execute(
                    "INSERT INTO dw.fact_vital_signs_minute (vital_sk, patient_sk, hospital_sk, device_id, "
                    "bed_number, minute_start_utc, date_sk, sample_count, heart_rate_avg, heart_rate_max, "
                    "heart_rate_min, spo2_avg, spo2_min, systolic_avg, diastolic_avg, respiratory_rate_avg, "
                    "temperature_c_avg, temperature_c_max, anomaly_event_count, primary_anomaly_kind) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (_vital_sk(dev, minute.isoformat()), _patient_sk(dev), HOSP_SK.get(b["hc"], 1),
                     dev, b["bed"], minute, int(minute.strftime("%Y%m%d")), b["n"],
                     avg(b["hr"]), round(max(b["hr"]), 1), round(min(b["hr"]), 1),
                     avg(b["spo2"]), round(min(b["spo2"]), 1), avg(b["sys"]), avg(b["dia"]),
                     avg(b["rr"]), avg(b["temp"]), round(max(b["temp"]), 2), b["anom"], b["kind"]))
            cn.commit()
            cn.close()
            print(f"[consumer] upserted {len(snap)} device-minutes", flush=True)
        except Exception as exc:
            print(f"[consumer] flush error: {exc}", flush=True)


def main():
    conn = os.environ["EVENT_HUB_CONNECTION_STRING"]
    name = os.environ.get("EVENT_HUB_NAME", "vitals-stream")
    threading.Thread(target=_flush_loop, daemon=True).start()
    client = EventHubConsumerClient.from_connection_string(
        conn, consumer_group="$Default", eventhub_name=name)
    print("[consumer] receiving from Event Hubs...", flush=True)
    with client:
        client.receive(on_event=on_event, starting_position="-1")


main()
