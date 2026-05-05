# Healthcare Data Warehouse & Analytics Platform

End-to-End Data Engineering Solution for Hospital Network Analytics

**Batch ETL + Real-Time Patient Vitals Monitoring + Clinical BI Dashboards**

## Overview

A unified data analytics platform for a hospital network operating 5 hospitals and 20+ clinics across Egypt. The platform consolidates scattered patient records, insurance claims, pharmacy data, and real-time vital signs into a centralized data warehouse for clinical and operational analytics.

### Key Highlights

- Synthetic clinical data generated with **Synthea** (realistic patient records)
- **Medallion Architecture** (Bronze/Silver/Gold) on Microsoft Azure
- Real-time **IoT vital signs streaming** with anomaly detection alerts
- **Star Schema** with SCD Type 2 for patient and provider dimensions
- **Power BI dashboards** for hospital utilization, readmission rates, cost analysis
- Data governance awareness and role-based access patterns

## Architecture

The platform follows the **Medallion Architecture** deployed on Microsoft Azure:

| Layer | Purpose | Azure Service | Data Format |
|-------|---------|---------------|-------------|
| Bronze (Raw) | Ingest raw data as-is | Azure Data Lake Gen2 | CSV, JSON, Parquet |
| Silver (Validated) | Cleaned, deduplicated, schema-enforced | Databricks (PySpark) | Delta Lake (partitioned) |
| Gold (Business) | Star schema, aggregated KPIs | Azure Synapse Analytics | Synapse dedicated SQL pool |
| Speed Layer | Real-time vital signs processing | Event Hubs + Spark Streaming | Delta Lake (append mode) |

### Data Flow

**Batch Path:** Synthea CSV/JSON → Azure Data Lake (Bronze) → ADF Copy Activities → Databricks PySpark (Silver) → Databricks transforms (Gold) → Synapse Analytics → Power BI

**Stream Path:** IoT Vital Signs Simulator → Azure Event Hubs → Spark Structured Streaming → Anomaly Detection → Delta Lake + Alerts → Power BI / Streamlit

## Data Sources

| # | Source | Format | Volume |
|---|--------|--------|--------|
| 1 | Patients | CSV (Synthea) | 100K patients |
| 2 | Encounters | CSV (Synthea) | 500K encounters |
| 3 | Conditions | CSV (Synthea) | 300K conditions |
| 4 | Medications | CSV (Synthea) | 400K prescriptions |
| 5 | Claims & Billing | JSON (Custom) | 200K claims |
| 6 | Vital Signs (IoT) | JSON (Stream) | Continuous |

## Project Structure

```
healthcare-data-warehouse/
├── src/
│   ├── generators/          # generate_claims.py, simulate_vitals.py, provider_api.py
│   └── synthea/             # Synthea configuration and generation scripts
├── notebooks/               # EDA notebook, Databricks PySpark notebooks
├── sql/
│   ├── ddl/                 # CREATE TABLE, indexes, constraints
│   ├── queries/             # Analytical queries (10+)
│   └── stored_procedures/   # Stored procedures
├── pipelines/
│   └── adf_templates/       # ADF ARM templates, pipeline documentation
├── dashboards/              # Power BI .pbix, Streamlit app, screenshots
├── docs/
│   ├── architecture/        # Architecture diagrams
│   └── data_dictionary/     # Data dictionary, final report
├── tests/                   # pytest unit tests, SQL validation scripts
├── docker/                  # Dockerfile, docker-compose.yml
├── data/
│   ├── raw/                 # Raw source data (not tracked in git)
│   ├── cleaned/             # Cleaned Parquet files (not tracked)
│   └── gold/                # Gold layer exports (not tracked)
└── config/                  # Configuration files
```

## Technology Stack

| Category | Technologies & Tools |
|----------|---------------------|
| Languages | Python 3.11+, SQL (T-SQL), PySpark, DAX |
| Cloud Platform | Microsoft Azure: Data Lake Gen2, Data Factory, Synapse Analytics, Databricks, Event Hubs, Key Vault |
| Databases | SQL Server (source OLTP), Azure Synapse dedicated SQL pool (OLAP warehouse) |
| Data Formats | CSV, JSON, Parquet, Delta Lake |
| Data Generation | Synthea (synthetic patient data), Faker (claims), custom Python simulators (vitals) |
| Processing | Apache Spark (via Databricks), Spark Structured Streaming, Azure Data Factory |
| Medical Standards | ICD-10 (diagnosis codes), SNOMED CT (clinical terms), RxNorm (medications) |
| Visualization | Power BI Desktop + Service, Streamlit (optional), matplotlib, seaborn, plotly |
| DevOps | Git, GitHub, GitHub Actions (CI/CD), Docker, Docker Compose |
| Monitoring | Azure Monitor, Log Analytics, Azure Alerts, Application Insights |

## Repository layout (after milestones)

```
healthcare-data-warehouse/
├── src/
│   ├── generators/          # generate_claims.py, simulate_vitals.py, provider_api.py, common.py
│   └── synthea/             # synthea.properties + run_synthea.py wrapper
├── notebooks/               # 01_eda_synthea.ipynb + Databricks driver notebooks
├── sql/
│   ├── ddl/                 # OLTP (01,02) + Synapse star schema (10,11,12)
│   ├── queries/             # 12 analytical queries
│   └── stored_procedures/   # SCD2 merges + daily KPI refresh
├── pipelines/
│   ├── load_oltp.py         # Synthea + claims -> SQL Server
│   ├── bronze/              # Bronze ingest (PySpark, Parquet)
│   ├── silver/              # Silver transforms (Delta) + DQ + governorate remap
│   ├── gold/                # Gold staging for Synapse COPY INTO
│   ├── streaming/           # Spark Structured Streaming for vitals
│   └── adf_templates/       # ADF pipeline JSON + trigger + README
├── dashboards/
│   ├── streamlit/           # 3-page app + demo data builder
│   └── powerbi/             # DAX measures + report design notes
├── docs/
│   ├── architecture/        # OLTP ER + warehouse ER + overview
│   ├── data_dictionary/     # Column-level reference
│   ├── monitoring.md        # Alerts + runbook
│   └── final_report.md      # Project final report
├── tests/                   # pytest suite (~30 cases)
├── docker/                  # Dockerfiles + compose for SQL Server / generator / Streamlit
├── config/                  # hospital_seed.csv (single source of truth for facilities)
└── Makefile                 # convenience targets
```

## Setup & Installation

### Prerequisites

- Python 3.11+
- SQL Server 2022 (or Docker image)
- Docker & Docker Compose
- Java 11+ (for Synthea)
- Azure CLI (for cloud deployment)

### Local Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/ma7moudalysalem/healthcare-data-warehouse.git
   cd healthcare-data-warehouse
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. Start local services with Docker:
   ```bash
   docker-compose -f docker/docker-compose.yml up -d
   ```

### Running Data Generators

```bash
# Generate synthetic claims data (200K rows by default)
python -m src.generators.generate_claims

# Start vital signs simulator (Ctrl+C to stop)
python -m src.generators.simulate_vitals

# Start provider API on :5000 + dump providers.json
python -m src.generators.provider_api

# Synthea (Java 11+ required) - 1K patient smoke run
python -m src.synthea.run_synthea --population 1000
```

### One-shot pipeline run (local Spark)

```bash
make synthea-smoke     # 1K patients
make claims            # 200K claims jsonl
make providers &       # background
make oltp-up oltp-init oltp-load
make bronze silver gold

# Streamlit (demo-mode, no Synapse needed)
make demo-data streamlit
```

## Milestones

| # | Milestone | Duration | Key Deliverables |
|---|-----------|----------|-----------------|
| 1 | Data Collection & EDA | Weeks 1-2 | Synthea config, Python generators, EDA notebook, ER diagram, SQL DDL |
| 2 | Data Modeling & Warehouse | Weeks 3-4 | Star schema, Synapse DDL, analytical queries, SCD2, data dictionary |
| 3 | Pipelines (Batch + Stream) | Weeks 5-7 | ADF pipelines, Databricks ETL, streaming pipeline, Delta Lake tables |
| 4 | BI Dashboards | Week 8 | Power BI (3 pages), DAX measures, optional Streamlit dashboard |
| 5 | DevOps & Presentation | Weeks 9-10 | CI/CD, Docker, Azure Monitor, final report, presentation slides |

## Team

| Name | GitHub |
|------|--------|
| Mahmoud Ali AbdelMaksoud Salem (Team Lead) | [@ma7moudalysalem](https://github.com/ma7moudalysalem) |
| Ahmed Gamal Lotfy Moussa | [@moussakii](https://github.com/moussakii) |
| Hussein Elsayed Mohamady Gabr | [@Hussein-Gabr5757](https://github.com/Hussein-Gabr5757) |
| John Emad Farhat | [@Johnemad791](https://github.com/Johnemad791) |
| Mahmoud Abdelaziz Tolan | [@Mahmoudtolan](https://github.com/Mahmoudtolan) |
| Reem Ashraf Said Abdelbary | [@reemashr](https://github.com/reemashr) |

## Data Privacy Note

This project uses **Synthea** -- an open-source synthetic patient generator -- to create realistic but entirely fictional clinical data. No real patient data is used. The architecture demonstrates data governance best practices (role-based access, data masking patterns, audit logging) that would be required in a production healthcare environment.

## License

This project is developed as part of the DEPI (Digital Egypt Pioneers Initiative) Microsoft Data Engineer Track.
