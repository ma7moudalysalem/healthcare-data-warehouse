"""Azure OpenAI helpers for the dashboard's AI Assistant.

Three capabilities:
  * natural-language -> SQL over the dw.* reporting views (Arabic or English),
  * data-grounded chat / RAG over the warehouse schema,
  * KPI-driven recommendations.

Config comes from env (set on the container):
    AOAI_ENDPOINT, AOAI_KEY, AOAI_DEPLOYMENT, AOAI_API_VERSION
"""
from __future__ import annotations

import os
import re

# ---- schema the model is allowed to query (kept in sync with 11_warehouse_views) ----
SCHEMA_DOC = """
You may ONLY query these three Azure SQL views (T-SQL dialect):

dw.vw_encounter_enriched(
  encounter_sk, encounter_id, encounter_class, encounter_date, encounter_year,
  encounter_month, encounter_month_name, encounter_day_of_week,
  length_of_stay_hours, is_inpatient, is_emergency, is_readmission_30d,
  discharge_status, total_cost_usd, payer_coverage_usd, out_of_pocket_usd,
  patient_id, patient_name, age_band, gender, patient_governorate,
  hospital_code, hospital_name, facility_type, hospital_governorate, bed_count,
  provider_name, provider_specialty, primary_icd10_code, primary_diagnosis,
  diagnosis_chapter)

dw.vw_claim_enriched(
  claim_sk, claim_number, status, is_denied, is_paid_in_full, days_to_decision,
  line_count, billed_amount, allowed_amount, paid_amount, denied_amount,
  patient_responsibility, currency, service_date, service_year, service_month,
  decision_date, payer_name, is_government_payer, hospital_name, facility_type,
  patient_age_band, patient_gender, patient_governorate, primary_icd10_code,
  primary_diagnosis)

dw.vw_vital_signs_minute(
  minute_start_utc, device_id, bed_number, patient_id, patient_name,
  hospital_name, hospital_governorate, heart_rate_avg, heart_rate_min,
  heart_rate_max, spo2_avg, spo2_min, systolic_avg, diastolic_avg,
  respiratory_rate_avg, temperature_c_avg, temperature_c_max, sample_count,
  anomaly_event_count, primary_anomaly_kind)

Notes: BIT columns (is_denied, is_inpatient, ...) are 0/1. Money is USD except
claims which are EGP. Use T-SQL syntax (TOP (n), DATEADD, GETUTCDATE()).
"""

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|exec|execute|merge|truncate|grant|revoke|"
    r"sp_|xp_|into|;\s*\S)", re.IGNORECASE)


def is_configured() -> bool:
    return bool(os.environ.get("AOAI_ENDPOINT") and os.environ.get("AOAI_KEY"))


def _client():
    from openai import AzureOpenAI
    return AzureOpenAI(
        azure_endpoint=os.environ["AOAI_ENDPOINT"],
        api_key=os.environ["AOAI_KEY"],
        api_version=os.environ.get("AOAI_API_VERSION", "2024-10-21"),
    )


def _create(messages: list[dict], max_tokens: int):
    """gpt-5 reasoning models burn tokens on hidden reasoning; keep it low so the
    visible answer isn't starved, and always give a generous completion budget."""
    client = _client()
    dep = os.environ.get("AOAI_DEPLOYMENT", "gpt5mini")
    try:
        return client.chat.completions.create(
            model=dep, messages=messages, max_completion_tokens=max_tokens,
            reasoning_effort="low")
    except Exception:  # older API versions reject reasoning_effort
        return client.chat.completions.create(
            model=dep, messages=messages, max_completion_tokens=max_tokens)


def _complete(messages: list[dict], max_tokens: int = 2500) -> str:
    for mt in (max_tokens, max(max_tokens, 4000)):
        resp = _create(messages, mt)
        txt = (resp.choices[0].message.content or "").strip()
        if txt:
            return txt
    return "⚠️ The model returned an empty response. Please try again."


def nl_to_sql(question: str) -> str:
    """Turn a natural-language question (Arabic or English) into a safe SELECT."""
    sys_prompt = (
        "You are a T-SQL analyst for a hospital data warehouse on Azure SQL. "
        "Translate the user's question (Arabic or English) into ONE read-only "
        "T-SQL SELECT statement over the allowed views. Rules:\n"
        "- SELECT only. Never modify data.\n"
        "- Always include TOP (n) to cap rows (default TOP (100)).\n"
        "- Use only the columns/views documented below.\n"
        "- Return ONLY the SQL, no markdown, no explanation.\n" + SCHEMA_DOC
    )
    sql = _complete(
        [{"role": "system", "content": sys_prompt},
         {"role": "user", "content": question}],
        max_tokens=2500,
    )
    sql = re.sub(r"^```[a-zA-Z]*|```$", "", sql).strip()
    # keep first statement only
    sql = sql.split(";")[0].strip()
    return sql


def is_safe_sql(sql: str) -> tuple[bool, str]:
    low = sql.strip().lower()
    if not low.startswith("select"):
        return False, "Only SELECT statements are allowed."
    if "dw.vw_" not in low:
        return False, "Query must target the dw.vw_* reporting views."
    if _FORBIDDEN.search(sql):
        return False, "Query contains a forbidden keyword."
    return True, ""


def narrate(question: str, sql: str, sample_rows: str) -> str:
    """Explain the query result to the user in their own language."""
    return _complete([
        {"role": "system", "content": "You are a concise healthcare BI analyst. "
         "Answer in the SAME language as the question. 3-5 sentences. Use the data."},
        {"role": "user", "content":
            f"Question: {question}\nSQL: {sql}\nResult sample (CSV):\n{sample_rows}\n"
            "Summarise the answer and one insight."},
    ], max_tokens=2000)


def recommendations(kpi_summary: str) -> str:
    return _complete([
        {"role": "system", "content":
            "You are a hospital operations advisor. Given KPI figures, give 3-5 "
            "specific, actionable recommendations. Answer in Arabic and English "
            "(short). Focus on readmissions, ED load, claim denials, and cost."},
        {"role": "user", "content": kpi_summary},
    ], max_tokens=4000)


def chat(history: list[dict]) -> str:
    """General grounded chat / RAG over the schema + provided context."""
    sys = {"role": "system", "content":
           "You are the assistant for a Healthcare Data Warehouse. Answer questions "
           "about the platform, its data model, and clinical/operational metrics. "
           "Answer in the user's language. If asked for numbers, suggest using the "
           "'Ask the data' box.\n" + SCHEMA_DOC}
    return _complete([sys] + history, max_tokens=2500)
