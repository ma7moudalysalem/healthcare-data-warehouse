# Deployment — full stack on Azure

An end-to-end, multi-tier deployment of the healthcare data warehouse on an
**"Azure for Students"** subscription. Every designed layer has a running
counterpart; the expensive Synapse/Databricks/Event-Hubs services are swapped
for budget equivalents (see the substitutions table).

## Live endpoints

| Service | URL |
|---|---|
| **Clinical dashboard** (Streamlit) | https://hcdw-dashboard.jollysea-eb0cfa5c.westeurope.azurecontainerapps.io/ |
| **Provider API** (Flask) | https://hcdw-provider-api.jollysea-eb0cfa5c.westeurope.azurecontainerapps.io/ |

The dashboard reads the three `dw.*` reporting views **live** from Azure SQL.
The Provider API is a standalone backend serving `/health`, `/api/providers`,
`/api/providers/<npi>`.

## Architecture (as deployed)

```
 Synthea CSV + claims.jsonl + providers.json      (data sources; Synthea = Java)
                 │  bronze → silver → gold  (PySpark + Delta; runs on Linux/CI
                 ▼                           and via docker/Dockerfile.pipeline)
        ┌──────────────────────┐
        │   Azure SQL Database  │  dw star schema: dim_* + fact_* + 3 views
        │   (Basic, northeurope)│  populated by pipelines/gold/seed_warehouse.py
        └──────────┬───────────┘
     reads dw.vw_* │
        ┌──────────▼───────────┐        ┌──────────────────────┐
        │  Streamlit dashboard  │        │   Provider API (Flask)│
        │  (Container App)      │        │   (Container App)     │
        └──────────────────────┘        └──────────────────────┘
```

## Design → deployed substitutions (why)

| Designed (proposal) | Deployed | Reason |
|---|---|---|
| Synapse dedicated SQL pool | **Azure SQL Database (Basic)** | Synapse ≈ $900/mo; DDL ported to T-SQL in `sql/ddl/azuresql/` |
| Databricks | **PySpark** (local/CI + `Dockerfile.pipeline`) | Databricks not free; Spark code unchanged |
| ADF orchestration | Python scripts (`scripts/deploy_all.sh`) | ADF adds cost/complexity |
| Event Hubs + Spark streaming | vitals seeded into `fact_vital_signs_minute` | continuous stream compute is the costly part |
| Power BI | **Streamlit** on Container Apps | Power BI Pro not free |

> **Note on the gold load.** The repo's Spark `pipelines/gold/gold_load.py` is an
> MVP that leaves `provider_sk` / `primary_diagnosis_sk` / `payer_sk` NULL and
> never builds `dim_date` / `dim_diagnosis` / `dim_payer` / vitals. Loading it
> verbatim gives a half-empty dashboard. `pipelines/gold/seed_warehouse.py`
> completes that enrichment and produces a fully cross-referenced star schema so
> every dashboard page renders. The Spark batch/stream pipeline still runs
> end-to-end (see `docker/Dockerfile.pipeline`) as the data-engineering artifact.

## Azure resources

| Resource | Name | Region | Notes |
|---|---|---|---|
| Resource group | `rg-healthcare-dw` | westeurope | |
| Container Registry | `hcdwacr44ba4327` | westeurope | Basic, admin-enabled (~$5/mo) |
| Container Apps env | `hcdw-env` | westeurope | |
| Container App — dashboard | `hcdw-dashboard` | westeurope | image `healthcare-dashboard:db1`, 0.5 vCPU/1 GiB, min-replicas 0 |
| Container App — provider API | `hcdw-provider-api` | westeurope | image `healthcare-provider-api:v1`, 0.25 vCPU/0.5 GiB, min-replicas 0 |
| SQL logical server | `hcdw-sqlne-44ba4327` | northeurope | admin `hcdwadmin` |
| SQL database | `healthcare` | northeurope | Basic tier (~$5/mo) |

## Cost (all within student credit)

- **Azure SQL (Basic):** ~$5/mo — always-on.
- **Container Registry (Basic):** ~$5/mo — always-on.
- **Container Apps:** both apps `min-replicas 0` (scale to zero); monthly free grant covers demo traffic ≈ $0.
- **Total ≈ $10/mo.** Cold start after idle ~10–30s.

## Reproduce / redeploy

Prereqs: `az login`, **Docker Desktop running** (ACR Tasks are blocked on student
subs, so images build locally). One command builds and deploys the whole stack:

```bash
bash scripts/deploy_all.sh
```

Individual pieces:
```bash
# apply the warehouse schema + views
HCDW_SQL_SERVER=hcdw-sqlne-44ba4327.database.windows.net HCDW_SQL_DB=healthcare \
HCDW_SQL_USER=hcdwadmin HCDW_SQL_PASSWORD=... \
  python scripts/apply_sql.py sql/ddl/azuresql/warehouse_azuresql.sql

# (re)populate the star schema
python -m pipelines.gold.seed_warehouse --patients 2000 --encounters 6000 --claims 4000 --vital-minutes 6000

# run the real Spark batch pipeline (Linux container)
docker build -f docker/Dockerfile.pipeline -t hcdw-pipeline:v1 .
docker run --rm -v "$PWD:/work" -w /work hcdw-pipeline:v1 \
  python -m pipelines.bronze.bronze_ingest --source synthea --input data/raw/synthea --layer-root data/bronze
```

## Tear down (stop all charges)

```bash
az group delete -n rg-healthcare-dw --yes --no-wait
```
