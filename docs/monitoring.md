# Monitoring & alerting

The platform's observability layer is split between three places: ADF
(orchestration health), Azure Monitor / Log Analytics (resource and
query telemetry), and the warehouse's own `dw.load_audit` table (ETL
row-counts and statuses).

## What we watch

| Signal                         | Threshold              | Source                     | Alert routes to |
|--------------------------------|------------------------|----------------------------|-----------------|
| ADF pipeline failure (any)     | 1 occurrence           | Azure Monitor / ADF logs   | data-platform email + Teams |
| Pipeline duration > 90 min     | 90 min                 | Azure Monitor              | data-platform email |
| Bronze rows / day delta        | < 50% of trailing 7d   | `dw.load_audit` query      | data-platform Teams channel |
| Silver rejection rate per rule | > 1%                   | `dw.load_audit`            | data-platform Teams |
| Synapse DWU > 80% sustained    | 30 min                 | Azure Monitor              | platform on-call |
| Streaming vitals lag           | > 2 min watermark drift| Spark structured streaming | clinical on-call |
| Vital sign anomaly (clinical)  | live                   | Streamlit + Power BI tile  | hospital ops |

The data-platform alerts are advisory; the **clinical** alert from the
streaming detector is the only one that pages someone overnight.

## Where the dashboards live

* **Azure Monitor workbook "Healthcare DW - Platform"** - one workbook
  with three tabs (ADF runs, Synapse query stats, ADLS storage growth).
  Pinned to the data-platform Teams channel.
* **Power BI page "Live Vital Signs"** - the clinical-facing tile
  documented in `dashboards/powerbi/report_design.md`.
* **Streamlit `Live Vital Signs` page** - mirror of the Power BI tile,
  used by the on-call hospital operations team because it deep-links
  per-patient.

## Audit log queries

Running rejection rate per Silver rule for the last 7 days:

```sql
SELECT object_name, error_message AS rule, AVG(rows_rejected * 1.0 / rows_read) AS pct
FROM dw.load_audit
WHERE layer = 'silver'
  AND started_at >= DATEADD(DAY, -7, SYSUTCDATETIME())
GROUP BY object_name, error_message
ORDER BY pct DESC;
```

Pipeline run history:

```sql
SELECT TOP 50 layer, object_name, status, started_at, finished_at,
       DATEDIFF(SECOND, started_at, finished_at) AS duration_s,
       rows_written
FROM dw.load_audit
ORDER BY started_at DESC;
```

## Runbook (failing pipeline)

1. Open the failed run in ADF Monitor; copy the activity name and run id.
2. Search Log Analytics for that run id - there's a saved query
   `KQL/adf_run_by_id.kql`.
3. If the failure is in a Databricks notebook, click through to the
   Databricks job run page; the stack trace is in the driver log.
4. Common failures and fixes:
   * **"Schema mismatch" in a Bronze copy** - source DDL changed.
     Update `pipelines/load_oltp.py` mapping and `silver_*` schemas.
   * **DQ rule rejection rate spiked** - look at the
     `silver_quarantine` table partitioned by date + rule_name.
   * **Streaming watermark stuck** - usually a single bad partition;
     the Spark UI will show one task pinned to a partition.
5. After repair, re-run the *single* failed activity from ADF, not the
   whole pipeline.
