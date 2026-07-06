# Architecture Overview

> **As-designed vs as-deployed.** This document describes the *target* architecture
> (Synapse / Databricks / ADF / Event Hubs / Power BI). The graded system is deployed on an
> *Azure for Students* budget with substitutions: **Azure SQL** for Synapse, **PySpark** for
> Databricks, **Python loaders** for ADF, **Streamlit** for Power BI. See
> [`DEPLOYMENT.md`](../../DEPLOYMENT.md) for what actually runs live.

## End-to-end data flow

```
                        +------------------+
   IoT bedside monitors |  Vital sim       |
   (~50 devices)        |  src/generators/ |
                        |  simulate_vitals |
                        +--------+---------+
                                 |  JSON @ 1Hz/device
                                 v
                        +------------------+        +-----------------------+
                        | Azure Event Hubs |------->| Spark Structured       |
                        |  vitals-stream   |        | Streaming (Databricks) |
                        +------------------+        | pipelines/streaming/   |
                                                    | vitals_streaming.py    |
                                                    +-----+-----------+------+
                                                          |           |
                                                          v           v
                                                   bronze/        silver/
                                                   vitals_stream  vitals_minute
                                                                       |
                                                                       v
                                                              dw.fact_vital_signs_minute
                                                              (hourly mirror via ADF)

  +---------+   nightly    +---------+        +-----------------+
  | Synthea |------------> | OLTP    |        | Provider API    |
  | CSVs    |              | SQL     |<-------| (Flask)         |
  +---------+              | Server  |        +-----------------+
                           +----+----+                ^
                                |                     |
                                | ADF Copy            |
                                v                     |
                         +-------------+              |
                         | Bronze ADLS |--------------+
                         | (Parquet)   |
                         +------+------+
                                |
                                | Databricks Silver (PySpark + Delta)
                                v
                         +-------------+
                         | Silver ADLS |
                         | (Delta)     |    DQ rules + governorate remap +
                         +------+------+    SCD2 inputs + readmission flag
                                |
                                | Databricks Gold staging
                                v
                         +-------------+
                         | Gold ADLS   |
                         | (Parquet)   |
                         +------+------+
                                |
                                | ADF Copy + Synapse Stored Procs
                                v
                         +-----------------+         +-----------+
                         | Synapse SQL Pool|<------->| Power BI  |
                         | dw.dim_*, fact_*|         | / Streamlit|
                         +-----------------+         +-----------+
```

## Layer responsibilities

### Bronze
* Faithful copy of source feeds, **no transformation**.
* Parquet (Snappy), partitioned by `_ingest_date`.
* Append-only - re-deliveries write a new partition rather than overwriting.
* Implemented in `pipelines/bronze/bronze_ingest.py`.

### Silver
* Schema enforcement (no `inferSchema`).
* DQ rules; rejects -> `silver_quarantine/<table>` with `_rejected_rule`.
* Egyptian governorate remap on patient addresses.
* Derived business attributes: `age_band`, `is_readmission_30d`,
  `length_of_stay_hours`, `is_denied`, `derived_anomaly_kind`.
* Output is **Delta** (append + merge support).
* Implemented in `pipelines/silver/silver_*.py`.

### Gold
* Surrogate-key assignment (Synapse sequences).
* SCD Type 2 merge for `dim_patient` and `dim_provider`
  (`sp_merge_dim_*_scd2`).
* Daily KPI aggregate refresh (`sp_refresh_kpi_daily`).
* Reporting views (`vw_encounter_enriched`, `vw_claim_enriched`,
  `vw_vital_signs_minute`).

## Why Medallion?

The classic alternative is a single ETL stage from OLTP to a star schema.
That works at small scale but bites later because:

* DQ regressions are hard to debug without a raw layer to compare against.
* A schema change in the source breaks the entire ETL atomically.
* Re-runs are expensive because the transformations are coupled.

Medallion costs an extra storage tier (Bronze + Silver) but buys
re-playable Bronze, schema isolation in Silver, and a Gold layer that the
business contract sits on without knowing or caring about source-system
quirks.

## Streaming vs. batch boundaries

* Vitals are streaming-first because the dashboard's "Active alerts" tile
  needs <1-minute latency. Batch would mean a 24h delay on patient-safety
  signals.
* Everything else (encounters, claims, prescriptions) is batch because the
  source systems themselves are batch (nightly close, file deliveries).
* The stream and batch worlds meet at the warehouse: vitals land in Synapse
  via an hourly Copy, the rest via the nightly orchestrator.

## Distribution choices on Synapse

Documented per-table in [er_diagram_warehouse.md](er_diagram_warehouse.md#distribution-and-storage-choices-synapse-dedicated-sql-pool).
Short version: REPLICATE small dims, HASH facts on the column most queries
filter/join on (`patient_sk` for encounters, `encounter_sk` for claims).

## Security and governance (notes for the final report)

* RBAC at Synapse level: `bi_reader` for dashboards, `analyst_full` for ad
  hoc, `etl_writer` for ADF service principals. SQL-side roles with column
  masking on `dim_patient.full_name` for the analyst role.
* PII columns in Silver are tagged via Microsoft Purview classifications.
* Audit trail: `dw.load_audit` for ETL runs, `sys.dm_pdw_exec_requests` for
  Synapse query history.
* No real PII enters the system. Synthea is fully synthetic and the
  Egyptian governorate remap further detaches residual US demographics.
