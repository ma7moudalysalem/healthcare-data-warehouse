# Data Quality Report

How the platform enforces, measures, and monitors data quality across the
medallion pipeline. Quality is enforced at the **Silver** layer: every source
feed is validated rule-by-rule, clean rows flow forward, and failing rows are
**quarantined** (never silently dropped) for audit.

## 1. Where quality is enforced

| Layer | Role in data quality |
|-------|----------------------|
| Bronze | Faithful copy of the source — no cleansing. Carries lineage metadata (`_ingest_ts`, `_source_file`, `_run_id`, `_ingest_date`). |
| **Silver** | **Schema enforcement + DQ rules + quarantine + dedup + normalization.** This is the quality gate. |
| Gold | Conformed star schema. Assumes Silver already cleaned the data; adds the orphan-claim monitor (Q12) as a post-load check. |

The rule engine is `pipelines/silver/silver_common.py::split_by_rule`, which
splits a DataFrame by a boolean expression into **clean** (rule = TRUE) and
**rejected** (rule = FALSE *or* NULL) sets. Rejected rows are tagged with
`_rejected_rule` and `_rejected_at` and written by `write_quarantine` to a
Delta table, append-only, partitioned by `_quarantine_date` and `_rejected_rule`
so every failure is traceable to the rule and day that caught it.

## 2. Rule catalogue (16 rules)

| Entity | Rule | Rejects rows where… |
|--------|------|---------------------|
| `dim_patient` | `dob_present` | date of birth is null |
| `dim_patient` | `gender_valid` | gender not in {M, F, U} |
| `dim_patient` | `dob_not_in_future` | date of birth is after today |
| `dim_provider` | `npi_present` | NPI (business key) is null |
| `dim_provider` | `npi_10_digits` | NPI is not exactly 10 digits |
| `dim_provider` | `name_present` | first or last name is null |
| `fact_encounter` | `encounter_id_present` | encounter business key is null |
| `fact_encounter` | `patient_id_present` | patient business key is null |
| `fact_encounter` | `start_at_present` | encounter start timestamp is null |
| `fact_encounter` | `end_after_start` | end is before start (nulls allowed) |
| `fact_encounter` | `non_negative_cost` | total cost is negative |
| `fact_claim` | `claim_bk_present` | claim business key is null |
| `fact_claim` | `status_known` | status not in the 5 known values |
| `fact_claim` | `billed_non_negative` | billed amount is negative |
| `fact_claim` | `paid_le_billed` | paid amount exceeds billed (+1¢ tolerance) |
| `fact_claim` | `decision_after_submission` | decision date precedes submission date |

Source: `pipelines/silver/silver_dim_patient.py`, `silver_dim_provider.py`,
`silver_fact_encounter.py`, `silver_fact_claim.py`.

## 3. Beyond rules: normalization & de-duplication

* **De-duplication.** Each dimension/fact keeps only the latest record per
  business key via a `row_number()` window ordered by `_ingest_ts` descending —
  re-ingesting the same key does not create duplicates.
* **Governorate remap.** Synthea emits US addresses; `remap_to_governorate`
  deterministically maps every patient to an Egyptian governorate (MD5-bucketed),
  so the mapping is stable across re-runs and never churns the SCD2 history.
* **Derived quality columns.** `age_band`, `is_readmission_30d` (30-day window),
  `is_denied`, and `days_to_decision` are computed in Silver so downstream
  consumers never re-derive them inconsistently.

## 4. Referential integrity & the orphan-claim monitor

Real claims feeds arrive detached from the encounter that generated them, so the
schema **deliberately allows** `fact_claim.encounter_sk` to be NULL and the
seed models ~20% of claims as orphans. Rather than hide this, a dedicated
monitor — `sql/queries/12_dq_orphan_claims.sql` — reports the orphan rate so it
can be tracked over time (and wired to an alert in production). All other fact
foreign keys **do** resolve: as deployed, 100% of `fact_encounter` and
`fact_claim` rows resolve to real `dim_patient`, `dim_provider`, `dim_hospital`,
`dim_payer`, and `dim_diagnosis` members.

## 5. Profiling findings (from EDA)

Baseline profiling of the raw inputs (`notebooks/01_eda_synthea.ipynb`) is what
seeded the rules above. Representative findings:

* No negative `billed_amount` values in the claims feed (still guarded by
  `billed_non_negative`).
* Claim denial rate ≈ 10–12%, varying by payer — expected, not a defect.
* Referential integrity from `conditions` → `encounters` holds in Synthea output.
* Pre-remap patient addresses are US demographics (the reason for the
  governorate remap in Silver).

## 6. As-deployed note

DQ rules and quarantine run in the **PySpark Silver** stage
(`docker/Dockerfile.pipeline` / CI). The live Azure SQL warehouse is loaded by
`pipelines/gold/seed_warehouse.py`, which produces a fully cross-referenced star
schema (every FK resolves); the orphan-claim monitor (Q12) then runs against the
deployed `dw.*` tables. See [`DEPLOYMENT.md`](../DEPLOYMENT.md).
