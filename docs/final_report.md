# Healthcare Data Warehouse - Final Report

**Mahmoud Ali AbdelMaksoud Salem** (Team Lead) - DEPI Microsoft Data
Engineer Track, Group MNF4_AIS5_S1.

## 1. Problem statement

A network of 5 hospitals and 20 clinics across Egypt operates on a patchwork
of source systems: each hospital's EHR runs locally, claims come back from
seven different payers in a mix of CSV and XML, and bedside monitors only
expose vendor-specific dashboards. Clinical leadership cannot answer
basic questions across the network: *what is our 30-day readmission rate by
specialty? which payer is denying the most claims and why? how many vital
sign alerts went unanswered last night?*

This project builds an end-to-end data platform that consolidates these
feeds into a single warehouse, exposes a star schema for analysts, and
streams patient vitals into a live dashboard that surfaces anomalies inside
60 seconds.

## 2. Architecture summary

Medallion architecture on Microsoft Azure - see
[`docs/architecture/overview.md`](architecture/overview.md) for the full
diagram. Layers:

* **Bronze** (Azure Data Lake Gen2, Parquet) - faithful copy of source
  feeds, append-only, partitioned by `_ingest_date`.
* **Silver** (Delta Lake on ADLS) - schema enforcement, DQ rules with
  quarantine, governorate remap, derived columns (`age_band`,
  `is_readmission_30d`, `derived_anomaly_kind`).
* **Gold** (Synapse dedicated SQL pool) - star schema with SCD2 patient
  and provider dimensions, daily KPI rollup, three reporting views.

A separate **streaming path** lifts vital signs from Event Hubs through
Spark Structured Streaming into Bronze + Silver Delta, mirrored hourly
into Synapse so Power BI / Streamlit can hit the same model.

## 2a. As-deployed on Azure (budget substitutions)

The architecture above is the *target design*. The delivered system is deployed live on an
**Azure for Students** subscription, where the enterprise services were substituted for budget
equivalents **without changing the medallion architecture or the star schema**:

* **Azure SQL Database (Basic)** stands in for the Synapse dedicated SQL pool — the same `dw`
  star schema (T-SQL DDL in `sql/ddl/azuresql/`), populated by
  `pipelines/gold/seed_warehouse.py`.
* **PySpark** (locally / in CI and via `docker/Dockerfile.pipeline`) stands in for Databricks;
  the Bronze -> Silver -> Gold Spark code is unchanged.
* **Streamlit on Azure Container Apps** stands in for Power BI, reading the three `dw.vw_*`
  reporting views live.
* Vital-signs streaming runs through Azure Event Hubs into a lightweight Python consumer that
  upserts `dw.fact_vital_signs_minute`.

Live endpoints and the full resource/cost breakdown are in
[`DEPLOYMENT.md`](../DEPLOYMENT.md). Everything from Section 3 onward describes the design; the
deployed system realises it within the student-subscription budget.

## 3. Deliverables by milestone

| Milestone | Output | Where |
|-----------|--------|-------|
| 1. Data Collection & EDA | Synthea config + runner; 200K-row claims generator; vitals simulator; Provider API; OLTP DDL + seed; OLTP loader; EDA notebook; ER diagram | `src/synthea/`, `src/generators/`, `sql/ddl/01_*.sql`, `pipelines/load_oltp.py`, `notebooks/01_eda_synthea.ipynb`, `docs/architecture/er_diagram_oltp.md` |
| 2. Modeling & Warehouse | Synapse star schema with SCD2 dims; sequences + staging tables; SCD2 merge procs; daily KPI proc; 12 analytical queries; data dictionary; reporting views | `sql/ddl/10..12_*.sql`, `sql/stored_procedures/`, `sql/queries/`, `docs/data_dictionary/data_dictionary.md`, `docs/architecture/er_diagram_warehouse.md` |
| 3. Pipelines | Bronze ingest job; four Silver transforms; Gold staging; Spark streaming for vitals; ADF JSON for nightly + hourly orchestration; daily trigger | `pipelines/bronze/`, `pipelines/silver/`, `pipelines/gold/`, `pipelines/streaming/`, `pipelines/adf_templates/` |
| 4. BI dashboards | Streamlit 3-page app (with demo data); Power BI design notes; full DAX measure set; RLS roles; container | `dashboards/streamlit/`, `dashboards/powerbi/`, `docker/Dockerfile.streamlit` |
| 5. DevOps & report | CI workflow (lint + unit + Spark + SQL + markdown); pytest suite (~30 tests); Makefile; monitoring + runbook; this report | `.github/workflows/ci.yml`, `tests/`, `Makefile`, `docs/monitoring.md`, `docs/final_report.md` |

## 4. Numbers at a glance

* **Data volumes:** 100K patients (Synthea), ~500K encounters,
  ~300K conditions, ~400K medications, 200K custom claims (JSONL),
  ~50 streaming devices @ 1 Hz = ~4.3M vital events/day.
* **Storage estimate:** Bronze ~22 GB, Silver ~14 GB (Delta-compacted),
  Gold ~6 GB, partitioned vitals fact ~1.2 GB/quarter.
* **Synapse distribution:** 4 small replicated dims, 3 large hash dims,
  4 hash facts. Vitals fact partitioned by date_sk.
* **DQ:** 12 silver-side rules, automated quarantine, daily orphan-claim
  query (Q12) wired into Azure Monitor.
* **Tests:** ~30 pytest cases across generators, simulator, provider API,
  Silver helpers, SQL files; CI runs in <5 minutes on a small runner.

## 5. Sample analytical results (demo data)

Numbers below are from `dashboards/streamlit/demo_data` - the seeded demo
fixtures, not real Synthea output. They give a sense of the questions the
warehouse can answer.

* **Top diagnosis network-wide:** Essential hypertension (I10),
  ~17% of encounters.
* **30-day readmission rate (network):** 11.2% on inpatient discharges,
  with Cairo Central highest at 13.5%.
* **Average inpatient LOS:** 78 hours (3.25 days).
* **Claim denial rate:** 10% (count) / 9.2% (dollars), denial-rate
  variance across payers from 7.1% to 13.4%.
* **Live vital alerts:** ~4% of minutes flag at least one anomaly,
  driven mostly by the simulated tachycardia and hypoxia events.

## 6. Data privacy

No real patient data is used at any point. Synthea synthesises every
clinical attribute, the claims generator is fully synthetic JSON, and the
governorate remap further detaches any residual US demographic signal from
Synthea. The architecture demonstrates the patterns that would be required
in production (column masking on `dim_patient.full_name`, RBAC at the
Synapse SQL level, Purview classifications on PII columns) without ever
processing protected health information.

## 7. Things we'd do differently

* **Direct Lake instead of Synapse Copy.** When this project started,
  Microsoft Fabric's Direct Lake mode wasn't GA in the region we tested
  in. With Direct Lake, Power BI could read the Silver Delta tables
  directly and the Synapse mirror would disappear, simplifying the daily
  pipeline.
* **Soft delete handling on dim_patient.** Right now we treat absence
  from staging as "no change", but real operational systems will issue
  hard deletes that need a SCD2 close + deceased flag. The proc has a
  hook for this; we ran out of demo time before exercising it.
* **More granular RLS.** The two roles in the report cover the project's
  audience but production needs per-clinic restrictions and PHI redaction
  at the column level. The Synapse-side membership table is in place
  (see Power BI report design); rolling it out is mostly DevOps work.

## 8. References

* Synthea: <https://github.com/synthetichealth/synthea>
* Microsoft Medallion architecture:
  <https://learn.microsoft.com/azure/databricks/lakehouse/medallion>
* Azure Data Factory connector for Synapse Copy:
  <https://learn.microsoft.com/azure/data-factory/connector-azure-sql-data-warehouse>
* Spark Structured Streaming + Event Hubs:
  <https://learn.microsoft.com/azure/event-hubs/event-hubs-spark-connector>
