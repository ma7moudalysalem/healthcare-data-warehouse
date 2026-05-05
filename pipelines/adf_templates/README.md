# Azure Data Factory pipeline templates

This folder holds the ARM JSON for the two ADF pipelines that orchestrate the
warehouse:

| File | Purpose |
|------|---------|
| `PL_Daily_Bronze_Silver_Gold.json` | Nightly batch: copy OLTP → Bronze, run Databricks Silver + Gold staging notebooks, `COPY INTO` Synapse facts, refresh KPIs. |
| `PL_Streaming_Vitals_To_Synapse.json` | Hourly mirror of `silver/vitals_minute` Delta into `dw.fact_vital_signs_minute`. The streaming job itself runs continuously on a Databricks job cluster - this pipeline only refreshes the Synapse-side mirror. |
| `trigger_daily.json` | Schedule trigger for the daily pipeline (02:00 UTC). |

## Deploying

These templates assume:

* An ADF instance named `df-healthcare-dw`.
* Linked services `LS_Databricks` (Databricks workspace) and `LS_Synapse`
  (dedicated SQL pool).
* Datasets named per the activity references (e.g. `DS_OLTP_Patient`,
  `DS_Bronze_Patient`, etc). Adapt to your naming.
* ADLS containers `bronze`, `silver`, `gold` and their abfss URIs wired
  via the `BronzeRoot` / `SilverRoot` / `GoldRoot` variables.

Deploy with:

```bash
az datafactory pipeline create \
    --resource-group rg-healthcare-dw \
    --factory-name df-healthcare-dw \
    --name PL_Daily_Bronze_Silver_Gold \
    --pipeline @PL_Daily_Bronze_Silver_Gold.json
```

## Activity dependency graph (daily pipeline)

```
Copy_OLTP_Patient_To_Bronze
    -> Copy_OLTP_Encounter_To_Bronze
        -> Copy_OLTP_Claim_To_Bronze
            -> Databricks_Silver_All
                -> Databricks_Gold_Staging
                    -> Synapse_Merge_Patient_SCD2
                        -> Synapse_Merge_Provider_SCD2
                            -> Synapse_Copy_Fact_Encounter
                                -> Synapse_Copy_Fact_Claim
                                    -> Synapse_Refresh_KPI_Daily
```

The pipeline runs sequentially. The Databricks notebooks fan out internally
- the `silver_run_all` notebook calls `silver_dim_patient`, `silver_dim_provider`,
`silver_fact_encounter`, `silver_fact_claim` in parallel using
`dbutils.notebook.run` with a thread pool.

## Failure handling

* Each Copy activity has 2 retries with a 60-second backoff.
* The Databricks activities have a single retry (PySpark restart is
  expensive).
* On any final failure, ADF Monitor sends an alert through the
  `AG_DataPlatform` action group (email + Teams). This is configured at the
  factory level and isn't part of the pipeline JSON.
