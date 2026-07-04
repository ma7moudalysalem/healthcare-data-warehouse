"""Custom professional web frontend for the Healthcare Data Warehouse.

A single Flask app that (a) serves a bespoke single-page UI (Inter + ECharts +
Leaflet — a real product look, not a data-app framework) and (b) exposes JSON
endpoints that read the same Azure SQL `dw` star schema via pymssql, plus AI
routes proxied to Azure OpenAI. Self-bootstraps its deps so it runs on a stock
`python:3.11-slim` container with no image build.

Env: HCDW_SQL_*, AOAI_ENDPOINT/KEY/DEPLOYMENT/API_VERSION
"""
import subprocess
import sys

subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                       "--root-user-action=ignore", "flask", "pymssql", "requests", "tzdata"])

import os  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import pymssql  # noqa: E402
import requests  # noqa: E402
from flask import Flask, jsonify, request  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    CAIRO = ZoneInfo("Africa/Cairo")
except Exception:  # noqa: BLE001
    from datetime import timedelta
    CAIRO = timezone(timedelta(hours=3))

app = Flask(__name__)

HOSP_COORDS = {
    "Cairo Central Hospital": (30.0626, 31.2497),
    "Nile Heart Institute": (30.0900, 31.3600),
    "Giza Specialty Hospital": (29.9800, 31.1200),
    "Alexandria Bayside Medical": (31.2001, 29.9187),
    "Menoufia Regional Medical": (30.5590, 31.0110),
}
CLINIC_SPECS = ["Dental", "Pediatric", "Dermatology", "Ophthalmology", "Internal Medicine",
                "Family Medicine", "Orthopedic", "ENT", "Cardiology", "Women's Health"]


def _spec(name, ftype):
    if ftype == "hospital":
        return "Hospital"
    for s in CLINIC_SPECS:
        if s in name:
            return s
    return "Clinic"


def q(sql, params=()):
    cn = pymssql.connect(server=os.environ["HCDW_SQL_SERVER"], user=os.environ["HCDW_SQL_USER"],
                         password=os.environ["HCDW_SQL_PASSWORD"], database=os.environ["HCDW_SQL_DB"],
                         port=1433, tds_version="7.4")
    cur = cn.cursor(as_dict=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cn.close()
    return rows


def _cairo(dt):
    if not isinstance(dt, datetime):
        return dt
    return dt.replace(tzinfo=timezone.utc).astimezone(CAIRO).strftime("%H:%M")


# --------------------------------------------------------------------------- AI
def _aoai(messages, max_tokens=2500):
    ep = os.environ["AOAI_ENDPOINT"].rstrip("/")
    dep = os.environ.get("AOAI_DEPLOYMENT", "gpt5mini")
    ver = os.environ.get("AOAI_API_VERSION", "2024-10-21")
    url = f"{ep}/openai/deployments/{dep}/chat/completions?api-version={ver}"
    hdr = {"Content-Type": "application/json", "api-key": os.environ["AOAI_KEY"]}
    for mt in (max_tokens, max(max_tokens, 4000)):
        body = {"messages": messages, "max_completion_tokens": mt, "reasoning_effort": "low"}
        r = requests.post(url, headers=hdr, json=body, timeout=90)
        if r.status_code >= 400:
            body.pop("reasoning_effort", None)
            r = requests.post(url, headers=hdr, json=body, timeout=90)
        txt = (r.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        if txt:
            return txt
    return "The model returned an empty response. Please try again."


SCHEMA_DOC = """Only these Azure SQL views (T-SQL): dw.vw_encounter_enriched(encounter_class,
encounter_date,is_inpatient,is_emergency,is_readmission_30d,total_cost_usd,patient_name,age_band,
gender,patient_governorate,hospital_name,provider_name,provider_specialty,primary_icd10_code,
primary_diagnosis), dw.vw_claim_enriched(status,is_denied,billed_amount,paid_amount,service_date,
payer_name,hospital_name,primary_diagnosis), dw.vw_vital_signs_minute(minute_start_utc,patient_name,
hospital_name,heart_rate_avg,spo2_avg,systolic_avg,anomaly_event_count,primary_anomaly_kind)."""

import re  # noqa: E402
_FORBID = re.compile(r"\b(insert|update|delete|drop|alter|create|exec|merge|truncate|grant|into)\b", re.I)


@app.route("/api/ai/ask", methods=["POST"])
def ai_ask():
    qn = (request.json or {}).get("q", "").strip()
    if not qn:
        return jsonify(error="empty question"), 400
    sql = _aoai([{"role": "system", "content": "Return ONE read-only T-SQL SELECT (always TOP (n)) over the "
                  "allowed views. SQL only, no markdown.\n" + SCHEMA_DOC},
                 {"role": "user", "content": qn}], 2500)
    sql = re.sub(r"^```[a-z]*|```$", "", sql).strip().split(";")[0].strip()
    if not sql.lower().startswith("select") or "dw.vw_" not in sql.lower() or _FORBID.search(sql):
        return jsonify(sql=sql, error="Unsafe or invalid query blocked.")
    try:
        rows = q(sql)
    except Exception as e:  # noqa: BLE001
        return jsonify(sql=sql, error=str(e)[:200])
    import csv
    import io
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows[:15])
    ans = _aoai([{"role": "system", "content": "Concise healthcare BI analyst. Answer in the question's "
                  "language, 3-4 sentences, use the data."},
                 {"role": "user", "content": f"Q: {qn}\nSQL: {sql}\nData:\n{buf.getvalue()}"}], 2000)
    return jsonify(sql=sql, rows=rows[:200], answer=ans)


@app.route("/api/ai/recommend", methods=["POST"])
def ai_reco():
    k = q("SELECT COUNT(*) n, SUM(CAST(is_inpatient AS INT)) inp, SUM(CAST(is_readmission_30d AS INT)) rm "
          "FROM dw.vw_encounter_enriched")[0]
    c = q("SELECT COUNT(*) n, SUM(CAST(is_denied AS INT)) d, SUM(billed_amount) b, SUM(paid_amount) p "
          "FROM dw.vw_claim_enriched")[0]
    s = (f"Encounters={k['n']}, inpatient={k['inp']}, readmit30d={k['rm']}, claims={c['n']}, "
         f"denial={100*c['d']/max(c['n'],1):.1f}%, collection={100*(c['p'] or 0)/max(c['b'] or 1,1):.1f}%.")
    return jsonify(text=_aoai([{"role": "system", "content": "Hospital operations advisor. Give 4-5 specific "
                   "actionable recommendations in Arabic and English (short) on readmissions, ED load, "
                   "denials, cost."}, {"role": "user", "content": s}], 4000), kpis=s)


@app.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    hist = (request.json or {}).get("messages", [])
    sysm = {"role": "system", "content": "Assistant for a Healthcare Data Warehouse platform. Answer in the "
            "user's language.\n" + SCHEMA_DOC}
    return jsonify(text=_aoai([sysm] + hist, 2500))


# ----------------------------------------------------------------------- data
def _filt():
    h = request.args.get("hospital", "All")
    try:
        days = int(request.args.get("days", "365"))
    except Exception:  # noqa: BLE001
        days = 365
    return h, days


def _where(h, days, datecol):
    w = [datecol + " >= DATEADD(DAY, %s, CAST(SYSUTCDATETIME() AS DATE))"]
    p = [-abs(days)]
    if h and h != "All":
        w.append("hospital_name = %s")
        p.append(h)
    return " WHERE " + " AND ".join(w), tuple(p)


@app.route("/api/overview")
def api_overview():
    h, days = _filt()
    we, pe = _where(h, days, "encounter_date")
    wc, pc = _where(h, days, "service_date")
    enc = q("SELECT encounter_date, encounter_class, is_inpatient, is_emergency, is_readmission_30d, "
            "hospital_name, total_cost_usd, primary_icd10_code, primary_diagnosis "
            "FROM dw.vw_encounter_enriched" + we, pe)
    clm = q("SELECT status, is_denied, billed_amount, paid_amount FROM dw.vw_claim_enriched" + wc, pc)
    n = len(enc)
    inp = sum(r["is_inpatient"] for r in enc)
    rm = sum(r["is_readmission_30d"] for r in enc)
    denial = 100 * sum(r["is_denied"] for r in clm) / max(len(clm), 1)
    billed = sum(r["billed_amount"] for r in clm) or 1
    coll = 100 * (sum(r["paid_amount"] for r in clm) or 0) / billed
    daily = {}
    for r in enc:
        daily[str(r["encounter_date"])] = daily.get(str(r["encounter_date"]), 0) + 1
    byh = {}
    for r in enc:
        byh[r["hospital_name"]] = byh.get(r["hospital_name"], 0) + 1
    cls = {}
    for r in enc:
        cls[r["encounter_class"]] = cls.get(r["encounter_class"], 0) + 1
    dx = {}
    for r in enc:
        if r["primary_diagnosis"]:
            dx[r["primary_diagnosis"]] = dx.get(r["primary_diagnosis"], 0) + 1
    stt = {}
    for r in clm:
        stt[r["status"]] = stt.get(r["status"], 0) + 1
    return jsonify(
        kpis={"encounters": n, "inpatient": inp, "readmission": round(rm / inp * 100, 1) if inp else 0,
              "denial": round(denial, 1), "collection": round(coll, 1)},
        daily=sorted([{"date": k, "v": v} for k, v in daily.items()], key=lambda x: x["date"]),
        by_hospital=sorted([{"name": k, "v": v} for k, v in byh.items()], key=lambda x: -x["v"]),
        classes=[{"name": k, "v": v} for k, v in cls.items()],
        status=[{"name": k.replace("_", " ").title(), "v": v} for k, v in stt.items()],
        top_dx=sorted([{"name": k, "v": v} for k, v in dx.items()], key=lambda x: -x["v"])[:8])


@app.route("/api/revenue")
def api_revenue():
    h, days = _filt()
    wc, pc = _where(h, days, "service_date")
    clm = q("SELECT status, is_denied, billed_amount, paid_amount, payer_name, service_date "
            "FROM dw.vw_claim_enriched" + wc, pc)
    pay = {}
    for r in clm:
        p = pay.setdefault(r["payer_name"], {"claims": 0, "denied": 0})
        p["claims"] += 1
        p["denied"] += r["is_denied"]
    by_payer = sorted([{"payer": k, "claims": v["claims"],
                        "denial": round(100 * v["denied"] / v["claims"], 1)} for k, v in pay.items()],
                      key=lambda x: -x["denial"])
    mon = {}
    for r in clm:
        m = str(r["service_date"])[:7]
        d = mon.setdefault(m, {"billed": 0, "paid": 0})
        d["billed"] += r["billed_amount"] or 0
        d["paid"] += r["paid_amount"] or 0
    monthly = sorted([{"month": k, "billed": round(v["billed"]), "paid": round(v["paid"])}
                      for k, v in mon.items()], key=lambda x: x["month"])
    stt = {}
    for r in clm:
        stt[r["status"]] = stt.get(r["status"], 0) + 1
    return jsonify(by_payer=by_payer, monthly=monthly,
                   status=[{"name": k.replace("_", " ").title(), "v": v} for k, v in stt.items()])


@app.route("/api/hospitals")
def api_hospitals():
    _, days = _filt()
    we, pe = _where("All", days, "encounter_date")
    wc, pc = _where("All", days, "service_date")
    enc = q("SELECT hospital_name, hospital_governorate, bed_count, total_cost_usd, is_readmission_30d "
            "FROM dw.vw_encounter_enriched" + we, pe)
    clm = q("SELECT hospital_name, is_denied FROM dw.vw_claim_enriched" + wc, pc)
    coords = {r["hospital_name"]: (float(r["lat"]) if r["lat"] is not None else 27.0,
                                   float(r["lon"]) if r["lon"] is not None else 30.5, r["facility_type"])
              for r in q("SELECT hospital_name, lat, lon, facility_type FROM dw.dim_hospital")}
    h = {}
    for r in enc:
        d = h.setdefault(r["hospital_name"], {"gov": r["hospital_governorate"], "beds": r["bed_count"],
                                              "enc": 0, "cost": 0, "rm": 0})
        d["enc"] += 1
        d["cost"] += r["total_cost_usd"] or 0
        d["rm"] += r["is_readmission_30d"]
    den = {}
    for r in clm:
        x = den.setdefault(r["hospital_name"], [0, 0])
        x[0] += 1
        x[1] += r["is_denied"]
    out = []
    for name, d in h.items():
        lat, lon, ftype = coords.get(name, (27.0, 30.5, "hospital"))
        dd = den.get(name, [1, 0])
        out.append({"name": name, "gov": d["gov"], "beds": d["beds"], "encounters": d["enc"],
                    "avg_cost": round(d["cost"] / d["enc"]) if d["enc"] else 0,
                    "readmit": round(100 * d["rm"] / d["enc"], 1) if d["enc"] else 0,
                    "denial": round(100 * dd[1] / dd[0], 1), "lat": lat, "lon": lon,
                    "type": ftype, "specialty": _spec(name, ftype)})
    return jsonify(sorted(out, key=lambda x: -x["encounters"]))


@app.route("/api/hospital")
def api_hospital():
    name = request.args.get("name", "")
    rows = q("SELECT primary_icd10_code, primary_diagnosis, COUNT(*) c FROM dw.vw_encounter_enriched "
             "WHERE hospital_name=%s AND primary_diagnosis IS NOT NULL "
             "GROUP BY primary_icd10_code, primary_diagnosis ORDER BY c DESC", (name,))
    return jsonify(top_dx=[{"code": r["primary_icd10_code"], "dx": r["primary_diagnosis"], "c": r["c"]}
                           for r in rows[:8]])


@app.route("/api/vitals")
def api_vitals():
    h, _ = _filt()
    extra, p = "", []
    if h and h != "All":
        extra, p = " AND hospital_name = %s", [h]
    vs = q("SELECT TOP (400) minute_start_utc, patient_name, hospital_name, primary_anomaly_kind, "
           "heart_rate_avg, spo2_avg, systolic_avg, temperature_c_max, anomaly_event_count "
           "FROM dw.vw_vital_signs_minute WHERE minute_start_utc >= DATEADD(HOUR,-24,SYSUTCDATETIME())"
           + extra + " ORDER BY minute_start_utc DESC", tuple(p))
    devices = len({r["patient_name"] for r in vs})
    anom = sum(1 for r in vs if (r["anomaly_event_count"] or 0) > 0)
    alerts = [{"time": _cairo(r["minute_start_utc"]), "patient": r["patient_name"],
               "hospital": r["hospital_name"], "kind": r["primary_anomaly_kind"],
               "hr": r["heart_rate_avg"], "spo2": r["spo2_avg"], "sys": r["systolic_avg"],
               "temp": r["temperature_c_max"]} for r in vs if (r["anomaly_event_count"] or 0) > 0][:25]
    return jsonify(devices=devices, anomaly_minutes=anom, total=len(vs), alerts=alerts,
                   updated=datetime.now(timezone.utc).astimezone(CAIRO).strftime("%H:%M:%S"))


@app.route("/api/health")
def api_health():
    counts = q("SELECT 'Patients' t, COUNT(*) n FROM dw.dim_patient "
               "UNION ALL SELECT 'Providers', COUNT(*) FROM dw.dim_provider "
               "UNION ALL SELECT 'Encounters', COUNT(*) FROM dw.fact_encounter "
               "UNION ALL SELECT 'Claims', COUNT(*) FROM dw.fact_claim "
               "UNION ALL SELECT 'Vital minutes', COUNT(*) FROM dw.fact_vital_signs_minute")
    return jsonify(counts=counts, db="Azure SQL — live")


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/")
def index():
    return INDEX_HTML


INDEX_HTML = r"""__INDEX_HTML__"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
