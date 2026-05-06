# Healthcare Data Warehouse — Final Production Readiness Review (48-Hour Window)

You are a Senior Data Engineering Partner conducting the FINAL pre-production
audit of the Healthcare Data Warehouse & Analytics Platform before its
production deployment. You have 48 hours. Treat every gap as a blocker.
Verify before asserting. Fix, don't just report.

================================================================================
## CONTEXT (read once, internalize)
================================================================================
- **Product:** Healthcare Data Warehouse & Analytics Platform — End-to-End
  Data Engineering Solution for a 5-hospital, 20+ clinic network across Egypt.
  Batch ETL + Real-Time Patient Vitals Monitoring + Clinical BI Dashboards.
- **Stack:**
  - Data Generation: Synthea (100K patients), custom Faker-based generators
    (claims, vitals, providers)
  - OLTP Source: SQL Server 2022 (Docker)
  - Pipelines: Python 3.11, PySpark, Delta Lake (Medallion Architecture)
  - Cloud: Azure Data Lake Gen2, Azure Databricks, Azure Synapse Analytics,
    Azure Event Hubs, Azure Data Factory
  - Visualization: Power BI (primary), Streamlit (secondary / demo mode)
  - CI/CD: GitHub Actions (lint → unit → Spark tests → SQL lint → docs)
  - Infra: Docker, Docker Compose
- **Data Volumes:**
  - 100K synthetic patients via Synthea
  - 500K encounters, 300K conditions, 400K prescriptions
  - 200K claims (custom generator)
  - Continuous vital signs from IoT simulator (5+ devices)
- **Architecture:** Medallion (Bronze/Silver/Gold) + Speed Layer for streaming
  - Bronze: Raw ingest → Parquet on ADLS Gen2
  - Silver: Cleaned, deduplicated, schema-enforced → Delta Lake (partitioned)
  - Gold: Star schema aggregation → Synapse dedicated SQL pool
  - Speed: Event Hubs → Spark Structured Streaming → anomaly detection
- **Schema:** Star schema with SCD Type 2 for dim_patient and dim_provider,
  12 analytical queries, 3 stored procedures, `dw.load_audit` tracking
- **Medical Standards:** ICD-10, SNOMED CT, RxNorm
- **Key files:**
  - Pipelines: `pipelines/` (load_oltp, bronze, silver, gold, streaming)
  - SQL: `sql/ddl/` (5 DDL files), `sql/queries/` (12 queries),
    `sql/stored_procedures/` (3 SPs)
  - Generators: `src/generators/` (claims, vitals, providers, common)
  - Tests: `tests/` (7 test files)
  - Config: `config/hospital_seed.csv` (single source of truth for facilities)
  - Docker: `docker/` (docker-compose.yml, Dockerfile.generator, Dockerfile.streamlit)
  - CI: `.github/workflows/ci.yml`
  - Dashboards: `dashboards/streamlit/` + `dashboards/powerbi/`
- **Team:** 6-person team (DEPI Microsoft Data Engineer Track)
- **Target environment:** Azure cloud services; local dev via Docker + Makefile

================================================================================
## OPERATING PRINCIPLES
================================================================================
1. **Trust nothing older than 24 hours.** Re-verify file paths, line numbers,
   test counts, and behavior against the live code. Do not cite stale memory.
2. **Fix, don't refactor.** Surface-level changes only. Resist the urge to
   restructure pipelines or SQL outside the scope of a found blocker.
3. **Priority order at every fork:** Data Privacy (HIPAA/PHI) > Data Integrity >
   Pipeline Reliability > Security > Compliance > Performance > Developer Experience.
4. **Every commit is PR-sized**, with an English message referencing the
   blocker class (PHI-, DQ-, SEC-, PIPE-, PERF-, OBS-, REL-, OPS-).
5. **Re-run lint + full test suite after each change.** Any regression below
   the baseline halts work and triggers a report.
6. **No silent suppression.** Don't `|| true`, `# noqa`, or `pragma` to make
   checks pass. Fix the underlying issue.
7. **No partial implementations.** Either ship the fix or document the gap as
   a known limitation in the Risk Register.
8. **Documentation churn is out of scope.** Only update docs if they actively
   misrepresent shipped behavior in a way users would rely on.

================================================================================
## PRE-FLIGHT (do this before any code changes)
================================================================================
- [ ] `git status` clean; capture current commit SHA.
- [ ] `pip install -r requirements.txt` — record any install failures.
- [ ] `flake8 src/ tests/ pipelines/ --max-line-length=120` — record warnings/errors.
- [ ] `pytest tests/ -v --tb=short` — record exact pass/fail/skip counts per file.
- [ ] `pip audit` or `safety check` — capture all known CVEs in dependencies.
- [ ] `pip list --outdated` — capture (informational only; don't bump versions
      casually mid-audit).
- [ ] Verify Docker services start: `docker compose -f docker/docker-compose.yml up -d`
- [ ] Inventory SQL DDL files (`sql/ddl/`) and confirm they apply cleanly on
      a fresh SQL Server instance.
- [ ] Verify Makefile targets: `make lint`, `make test-fast`, `make test` all pass.
- [ ] Snapshot `config/hospital_seed.csv` — confirm it's the authoritative
      facility master data.
- [ ] List all pipeline modules (`pipelines/`) and confirm each has a runnable
      `__main__` entry point.
- [ ] Output a numbered, prioritized Blocking-Issue inventory BEFORE writing
      any fix code. Get implicit approval by ordering, then execute top-down.

================================================================================
## SECTION 1 — Data Privacy & PHI Protection (Zero Tolerance)
================================================================================
Healthcare data carries the highest privacy sensitivity. Even though this
platform uses synthetic data (Synthea), the architecture MUST be hardened
as if real PHI flows through it, because it will in production.

- **PHI inventory:** Identify every field that would be PHI in a real
  deployment: patient name, SSN, DOB, address, phone, email, medical record
  number, insurance ID, diagnosis codes linked to identity. Map where each
  appears across Bronze/Silver/Gold.
- **Synthea artifact sweep:** Verify no real patient data has leaked into
  `config/`, `data/`, test fixtures, or committed notebooks. Synthea output
  directories (`data/raw/synthea/`) must be in `.gitignore`.
- **At-rest encryption:** Azure Data Lake Gen2 (SSE with Microsoft-managed
  or customer-managed keys), Synapse (TDE enabled), SQL Server Docker
  (document that local dev is unencrypted synthetic data only).
- **In-transit encryption:** All Azure connections over TLS 1.2+. SQL Server
  connection strings use `Encrypt=True;TrustServerCertificate=False` in
  non-dev environments.
- **Column-level masking:** Synapse dynamic data masking on PII columns
  (patient name, SSN, phone, address) for non-clinical roles.
- **Row-level security:** If multi-hospital access control is needed,
  Synapse RLS policies scoped by hospital/facility.
- **Access logging:** Every query against PHI tables logged with user
  identity, timestamp, query hash. Azure Synapse auditing enabled.
- **Data retention & disposal:** Define retention periods per data class:
  - Clinical records: per Egyptian health regulations
  - Claims/billing: 5 years (Egyptian Tax Law)
  - Vital signs streaming: 90 days hot, 1 year cold, then purge
  - Audit logs: 7 years
- **Right to deletion:** Even for synthetic data, build the deletion pipeline
  (delete patient by ID across all layers) to prove the architecture supports
  it for real deployments.
- **De-identification:** If any analytics outputs (Gold layer, Power BI
  reports) could re-identify patients, apply k-anonymity or differential
  privacy on aggregations with small cell counts (< 5).
- **Notebook hygiene:** No hardcoded PHI examples, connection strings, or
  credentials in any `.ipynb` or `.py` file.

================================================================================
## SECTION 2 — Data Quality & Pipeline Correctness
================================================================================
- **Schema enforcement at every layer boundary:**
  - Bronze: raw schema preserved as-is, but validate file presence, row
    counts, and file format (CSV/JSON/Parquet) before promoting.
  - Silver: explicit schema definitions in each `silver_*.py` module. Every
    column typed, no `object` or `string` catch-alls for numeric/date fields.
  - Gold: star schema columns match `sql/ddl/10_warehouse_schema.sql` exactly.
    Any mismatch between Gold Parquet output and Synapse DDL is a blocker.
- **Quarantine layer (`data/silver_quarantine/`):**
  - Every rejected row includes: source file, row index, rule name, rejection
    reason, timestamp.
  - Quarantine is append-only; never silently dropped.
  - Verify quarantine is actually populated when bad data is injected (test).
  - Alert when quarantine rate exceeds threshold (see monitoring.md: > 1%).
- **Deduplication:**
  - Patient dedup: by SSN or composite key (name + DOB + gender). Verify the
    chosen strategy in `silver_dim_patient.py`.
  - Encounter dedup: by encounter ID. No duplicate fact rows in Gold.
  - Claims dedup: by claim ID. Verify in `silver_fact_claim.py`.
- **SCD Type 2 correctness (`sp_merge_dim_patient_scd2.sql`,
  `sp_merge_dim_provider_scd2.sql`):**
  - New record: inserted with `is_current = 1`, `effective_from = GETUTCDATE()`,
    `effective_to = NULL`.
  - Changed record: existing row closed (`is_current = 0`,
    `effective_to = GETUTCDATE()`), new row inserted.
  - No change: no new row, no update. Verify via golden test.
  - Edge case: reactivation of a previously closed record.
  - **Test:** Run the SP twice with identical data — zero new rows on second run.
  - **Test:** Run with changed address — exactly one close + one insert.
- **Referential integrity across layers:**
  - Every `encounter_key` in `fact_encounter` must exist in `dim_patient` and
    `dim_provider`.
  - Every `claim_id` in `fact_claim` must reference a valid encounter.
  - Orphan detection: `sql/queries/12_dq_orphan_claims.sql` must return zero
    rows on a clean load. Verify this is part of the pipeline health check.
- **Date/time consistency:**
  - All timestamps stored as UTC in the warehouse.
  - Display layer (Power BI, Streamlit) converts to `Africa/Cairo` (UTC+2).
  - No mixed date formats (ISO 8601 everywhere in data files).
  - Encounter `admission_date <= discharge_date` enforced.
  - Claim `service_date` within encounter date range.
- **Numeric precision:**
  - Money fields (`claim_amount`, `paid_amount`, `copay`, `revenue`):
    `DECIMAL(18,2)` minimum in SQL, `float64` with explicit rounding in Python.
  - No floating-point comparison in business logic (use `decimal` module or
    explicit epsilon).
  - Aggregations: verify SUM/AVG don't lose precision across 200K+ claims.
- **Null handling policy:**
  - Define per column: required (reject if null) vs. optional (pass through
    with default) vs. derived (compute from other columns).
  - No implicit null-to-zero conversions in aggregations.
  - Null `discharge_date` means patient still admitted — verify this is
    handled correctly in length-of-stay calculations.
- **ICD-10 / SNOMED CT / RxNorm validation:**
  - Codes generated by Synthea are valid, but verify the mapping tables in
    `02_oltp_seed_reference.sql` cover all codes that appear in generated data.
  - Any unmapped code should land in quarantine, not silently pass through.
- **Idempotency:** Every pipeline stage must be re-runnable. Running
  `make bronze && make silver && make gold` twice produces identical output.
  Verify via checksum on Gold Parquet files.

================================================================================
## SECTION 3 — Pipeline Reliability & Orchestration
================================================================================
- **Pipeline dependency chain:**
  ```
  Generators → OLTP Load → Bronze Ingest → Silver Transform → Gold Stage → Synapse COPY INTO
                                                                            ↓
  Vital Signs Simulator → Event Hubs → Spark Streaming → Delta Lake → Power BI
  ```
  Verify each link. A failure in Silver must not corrupt Gold or leave
  partial state.
- **Error handling in each pipeline module:**
  - `load_oltp.py`: What happens if SQL Server is unreachable? Connection
    retry with backoff? Graceful failure message?
  - `bronze_ingest.py`: Missing source file → skip with warning or fail?
    Document and test the chosen behavior.
  - `silver_*.py`: Schema mismatch → quarantine the entire batch or
    row-by-row? PySpark exception handling around transforms.
  - `gold_load.py`: Partial write → does it leave corrupt Parquet? Use
    atomic write pattern (write to temp, rename on success).
  - `vitals_streaming.py`: Event Hub connection drop → auto-reconnect with
    checkpointing? Verify Spark Structured Streaming checkpoint directory
    is configured and persisted.
- **Atomicity / transaction boundaries:**
  - OLTP load: `--truncate` flag implies a destructive reload. Verify this
    is wrapped in a transaction or uses staging tables to avoid data loss
    on failure mid-load.
  - Synapse `COPY INTO`: verify it's idempotent (truncate-and-reload or
    merge pattern, not blind append).
- **Backfill / replay:**
  - Can the pipeline re-process a specific date range without re-running
    everything? Parameterize Bronze/Silver/Gold by date partition.
  - Streaming: can the vitals pipeline replay from a specific Event Hub
    offset? Verify checkpoint reset procedure.
- **ADF orchestration (`pipelines/adf_templates/`):**
  - ARM templates deployable via `az deployment group create`? Test on a
    fresh resource group.
  - Pipeline triggers configured: schedule-based for batch, event-based for
    streaming?
  - Retry policies on each ADF activity (at least 2 retries with backoff).
  - Alert on failure wired to monitoring (see Section 10).
- **Local vs. cloud parity:**
  - `Makefile` targets run locally without Azure. Verify all pipeline modules
    have a `--local` or environment-based fallback that uses local filesystem
    instead of ADLS.
  - Spark: local mode (`spark.master=local[*]`) vs. Databricks cluster.
    Verify `SparkSession` builder handles both cleanly.
- **Concurrency / parallelism:**
  - Can Bronze ingest run in parallel for different sources (synthea,
    claims, providers) without conflict? Verify no shared state.
  - Silver transforms: are dim_patient and dim_provider independent of
    fact_encounter and fact_claim? If yes, parallelize. If not, document
    the dependency order.
- **Logging discipline:**
  - Every pipeline stage logs: start time, end time, rows read, rows
    written, rows quarantined, errors.
  - Logs go to `dw.load_audit` table AND structured stdout for local runs.
  - No PII in log messages (no patient names, SSNs, or raw record dumps).

================================================================================
## SECTION 4 — Security
================================================================================
- **Secrets sweep:**
  - No connection strings, Azure keys, SAS tokens, or passwords in source
    code. Verify via `git log -p | grep` for patterns: `Password=`,
    `AccountKey=`, `SharedAccessSignature=`, `DefaultEndpointsProtocol=`,
    `sa_password`, `MSSQL_SA_PASSWORD` (in code, not in `.env.example`).
  - `.env` file is in `.gitignore`. `.env.example` contains placeholders only.
  - Azure Key Vault referenced in production config (ADF linked services,
    Databricks secret scopes).
- **SQL injection:**
  - `load_oltp.py`: uses SQLAlchemy ORM or parameterized queries? No raw
    string interpolation in SQL statements.
  - Stored procedures: no dynamic SQL built from user input (unlikely in a
    warehouse, but verify).
- **Docker security:**
  - SQL Server container: `MSSQL_SA_PASSWORD` set via environment variable,
    not hardcoded in `docker-compose.yml`.
  - No `privileged: true` on any container.
  - Base images pinned to specific versions (not `latest`).
  - Non-root user where possible.
- **Network security (Azure):**
  - ADLS Gen2: firewall rules, private endpoints, no public blob access.
  - Synapse: managed VNet, private endpoints, IP firewall.
  - Databricks: VNet injection, NSG rules.
  - Event Hubs: managed identity auth, not connection strings in code.
- **RBAC:**
  - Azure AD groups for: Data Engineers, Data Analysts, Clinical Users,
    Hospital Ops, Platform Admin.
  - Principle of least privilege: analysts get read-only on Gold; engineers
    get write on Bronze/Silver; no one gets owner on production resources.
  - Synapse workspace roles mapped to AD groups.
  - Databricks workspace scoped to cluster policies.
- **Managed Identity:**
  - ADF, Databricks, Synapse should use managed identity to access ADLS,
    Key Vault, Event Hubs — not service principals with client secrets
    where avoidable.
- **API security (provider_api.py):**
  - Flask development server must NOT be exposed in production. Document
    that this is a local-dev-only utility.
  - If exposed: add authentication, rate limiting, input validation.
- **Dependency vulnerabilities:**
  - Run `pip audit` or `safety check` against `requirements.txt`.
  - Flag any CVE in pandas, pyarrow, pyspark, flask, sqlalchemy, or
    azure-* packages.
  - Verify `Faker` is not imported in production pipeline code (it's a
    generator dependency only).

================================================================================
## SECTION 5 — SQL & Warehouse Schema
================================================================================
- **OLTP schema (`01_oltp_source_schema.sql`):**
  - All tables have primary keys, appropriate indexes, and foreign keys.
  - `NVARCHAR` for Arabic-capable text fields (patient names, addresses,
    facility names).
  - `DATETIME2` for all timestamps (not `DATETIME`).
  - Constraints: `CHECK` on status fields, `NOT NULL` on required columns.
- **Seed data (`02_oltp_seed_reference.sql`):**
  - Reference tables (governorates, facility types, payer types, ICD-10
    codes) seeded idempotently (merge or `IF NOT EXISTS` before insert).
  - No test/dummy data that shouldn't exist in production.
  - `config/hospital_seed.csv` is the single source of truth for facility
    master data — verify it's loaded into the OLTP and propagated to
    dim_facility in Gold.
- **Warehouse schema (`10_warehouse_schema.sql`):**
  - Star schema with fact tables: `fact_encounter`, `fact_claim`,
    `fact_vital_sign`, `fact_daily_kpi`.
  - Dimension tables: `dim_patient`, `dim_provider`, `dim_facility`,
    `dim_date`, `dim_diagnosis`, `dim_payer`.
  - SCD Type 2 columns on `dim_patient` and `dim_provider`: `effective_from`,
    `effective_to`, `is_current`, `version`.
  - Surrogate keys (`_key` suffix) distinct from natural keys (`_id` suffix).
  - Distribution strategy (Synapse): HASH on high-cardinality join keys
    (`patient_key`, `encounter_key`), REPLICATE on small dimensions.
  - Clustered columnstore index on fact tables for analytical workloads.
- **Warehouse views (`11_warehouse_views.sql`):**
  - Views expose business-friendly names and join patterns.
  - No business logic in views that should be in stored procedures.
- **Sequences & staging (`12_warehouse_sequences_staging.sql`):**
  - Staging tables used by `COPY INTO` from Gold Parquet.
  - Sequences for surrogate key generation. Verify no gaps on normal load
    (gaps after rollback are acceptable).
- **Analytical queries (`sql/queries/01-12`):**
  - Each query runs without error on a populated warehouse.
  - Results are reasonable (no negative counts, no division by zero, no
    Cartesian products).
  - Query 02 (readmission rate): verify the 30-day window logic handles
    edge cases (same-day readmission, transfer between facilities).
  - Query 06 (ED throughput): verify it handles encounters with no
    discharge timestamp (still in ED).
  - Query 12 (DQ orphan claims): returns zero rows on a clean pipeline run.
- **Stored procedures:**
  - `sp_merge_dim_patient_scd2.sql`: verify MERGE statement handles all
    three cases (INSERT, UPDATE existing, no-change). Test with golden data.
  - `sp_merge_dim_provider_scd2.sql`: same verification.
  - `sp_refresh_kpi_daily.sql`: verify it's idempotent (re-running for the
    same date overwrites, not duplicates).
- **Indexes:**
  - Fact tables: index on date columns used in range filters
    (`admission_date`, `claim_date`).
  - Dimension tables: index on natural keys used in lookups
    (`patient_id`, `provider_npi`, `facility_code`).
  - Staging tables: minimal indexing (bulk load target).

================================================================================
## SECTION 6 — Data Generation & Reproducibility
================================================================================
- **Synthea:**
  - `src/synthea/run_synthea.py`: verify it invokes Synthea JAR with correct
    population size, output format (CSV), and Egypt-relevant config
    (demographics, disease prevalence).
  - `synthea.properties`: verify locale, output directory, and enabled
    modules.
  - Reproducibility: same seed → same output. Verify `--seed` parameter
    is supported and documented.
- **Claims generator (`src/generators/generate_claims.py`):**
  - Uses `Faker` with a fixed seed for reproducibility.
  - 200K rows with realistic distributions: claim amounts (EGP), status
    (approved/denied/pending), payer types, service dates within encounter
    ranges.
  - Output: JSONL format, one claim per line, UTF-8 encoded.
  - No duplicate claim IDs.
- **Provider API (`src/generators/provider_api.py`):**
  - Flask API serves facility and provider data from `hospital_seed.csv`.
  - Output: `providers.json` dumped to `data/raw/`.
  - Verify API handles Arabic characters in facility names correctly
    (UTF-8 throughout).
- **Vital signs simulator (`src/generators/simulate_vitals.py`):**
  - Generates realistic vital signs: heart rate, blood pressure, SpO2,
    temperature, respiratory rate.
  - Anomaly injection: periodic out-of-range values for testing the
    streaming anomaly detector.
  - Output: JSON to stdout (local) or Event Hubs (cloud).
  - Rate limiting: configurable `--rate` and `--devices` parameters.
- **Common utilities (`src/generators/common.py`):**
  - Shared constants, distributions, seed management.
  - Verify the single-seed reproducibility claim from recent commits
    (`982f241 make generators reproducible from a single seed`).
  - Run generators twice with same seed → diff output → zero differences.

================================================================================
## SECTION 7 — Testing Coverage
================================================================================
- Re-establish baseline; do not lose a single passing test.
- **Current test files:**
  - `test_generate_claims.py`: claims generator output validation
  - `test_simulate_vitals.py`: vitals generator output validation
  - `test_provider_api.py`: Flask API response validation
  - `test_silver_common.py`: Silver layer PySpark transforms (requires Java)
  - `test_sql_files.py`: SQL file syntax/existence validation
  - `test_project_structure.py`: project layout validation
- **Mandatory additional coverage (if missing):**
  - SCD Type 2 merge logic: golden tests with known input/output pairs.
  - Bronze ingest: handles missing file, empty file, corrupt file, schema
    drift.
  - Silver transforms: deduplication correctness, null handling, data type
    casting, quarantine population.
  - Gold load: output matches warehouse schema exactly (column names, types,
    order).
  - End-to-end: `make demo` succeeds on a clean checkout with only Docker
    and Python installed.
  - Idempotency: running any pipeline stage twice produces identical results.
  - Data quality: injecting known bad records → quarantine captures them all.
  - Streaming: vital signs with anomalies → anomaly detector flags them.
- **CI/CD pipeline (`.github/workflows/ci.yml`):**
  - `lint` job: flake8 passes.
  - `unit` job: pytest passes (excluding Spark tests).
  - `spark-tests` job: currently `continue-on-error: true` — evaluate
    whether this should be a hard gate for production.
  - `sql-lint` job: sqlfluff with `|| true` — same question: should SQL
    lint failures block merge?
  - `docs` job: markdownlint with `continue-on-error: true` — acceptable
    for docs, but verify it runs.
- **Test isolation:** Each test must be independent. No shared mutable state
  between tests. PySpark tests must create and tear down their own
  SparkSession.

================================================================================
## SECTION 8 — Performance & Scalability
================================================================================
- **Spark tuning (Silver/Gold transforms):**
  - Partition strategy: by date (`year/month/day`) for time-series data,
    by source for Bronze. Verify partition count is reasonable (not 1 file
    per row, not 1 giant file).
  - `spark.sql.shuffle.partitions`: tuned for data volume (default 200 may
    be too high for 100K patients, too low for 1M+).
  - `.coalesce()` before writing Parquet to avoid small files.
  - `broadcast()` hint on small dimension tables in joins.
- **SQL Server (OLTP) performance:**
  - `load_oltp.py` with `--truncate`: bulk insert via `fast_executemany=True`
    on pyodbc/SQLAlchemy.
  - Indexes dropped before bulk load, rebuilt after? Or is the volume small
    enough that it doesn't matter? Document the choice.
- **Synapse performance:**
  - `COPY INTO` from Gold Parquet is the fastest ingestion path — verify
    it's used, not row-by-row INSERT.
  - Distribution keys chosen to minimize data movement on common joins.
  - Statistics updated after load (`CREATE STATISTICS` or `UPDATE STATISTICS`).
  - Resource class for the ETL user: `largerc` or `xlargerc` for bulk ops.
- **Streaming performance:**
  - Spark Structured Streaming micro-batch interval: what is it? 10s? 30s?
    Tuned for the expected event rate.
  - Watermark for late data: configured to handle network delays from
    IoT devices (e.g., 2 minutes).
  - Checkpoint compaction to prevent checkpoint directory bloat.
- **Streamlit dashboard performance:**
  - `@st.cache_data` on expensive queries.
  - Demo data builder (`build_demo_data.py`) pre-computes aggregations to
    avoid live Spark/Synapse queries in demo mode.
  - Page load time < 3s on demo data.
- **Power BI performance:**
  - Import mode vs. DirectQuery: document the choice and its implications.
  - DAX measures (`dashboards/powerbi/dax_measures.md`) use `CALCULATE` +
    `FILTER` patterns efficiently, not row-by-row iteration.
  - Dataset refresh schedule documented.
- **Data volume projections:**
  - Current: 100K patients, 500K encounters, 200K claims.
  - 1-year projection: document expected growth rate.
  - Synapse scaling: when to move from DW100c to DW200c+.
  - ADLS storage: lifecycle policies for Bronze (hot → cool after 30 days).

================================================================================
## SECTION 9 — Streaming & Real-Time Pipeline
================================================================================
- **Event Hubs configuration:**
  - Partition count: sufficient for expected throughput (1 partition per
    10 MB/s ingress).
  - Retention: 1-7 days, aligned with replay requirements.
  - Consumer group: dedicated for the Spark streaming job (not `$Default`
    shared with other consumers).
  - Managed identity auth from Databricks to Event Hubs.
- **Spark Structured Streaming (`pipelines/streaming/vitals_streaming.py`):**
  - Trigger: `processingTime` or `availableNow`? Document and justify.
  - Watermark: configured for late-arriving vital signs.
  - Output mode: `append` for Delta Lake (not `complete` which rewrites).
  - Checkpoint: persistent storage (ADLS, not local filesystem in cluster).
  - Schema evolution: what happens if a new vital sign type is added?
- **Anomaly detection:**
  - Rules-based or ML-based? Document the approach.
  - Thresholds: heart rate > 120 or < 40, SpO2 < 90, temperature > 39,
    systolic BP > 180 or < 80.
  - Alert routing: to Streamlit live page and/or Power BI tile.
  - False positive rate: acceptable for clinical alerting? Document.
- **Backpressure handling:**
  - If the streaming job falls behind, does it auto-scale (Databricks
    autoscaling cluster) or queue? Document the expected behavior.
  - Max records per trigger: configured to prevent OOM on spike.
- **Exactly-once semantics:**
  - Delta Lake + checkpointing provides exactly-once. Verify checkpoint
    is on durable storage and not cleared accidentally.
  - Duplicate vital sign detection: same device + timestamp → deduplicate.

================================================================================
## SECTION 10 — Observability & Monitoring
================================================================================
- **`dw.load_audit` table:**
  - Schema: `layer`, `object_name`, `status`, `started_at`, `finished_at`,
    `rows_read`, `rows_written`, `rows_rejected`, `error_message`,
    `correlation_id`.
  - Populated by every pipeline stage (Bronze, Silver, Gold).
  - Queryable for pipeline health checks (see `docs/monitoring.md`).
- **Azure Monitor / Log Analytics:**
  - ADF pipeline failure alerts configured.
  - Pipeline duration > 90 min alert.
  - Synapse DWU > 80% sustained alert.
  - Workspace configured and connected to all resources.
- **Streaming monitoring:**
  - Watermark drift alert: > 2 minutes → clinical on-call.
  - Spark Streaming UI: query progress, input rate, processing rate.
  - Checkpoint lag metric exposed.
- **Data quality monitoring:**
  - Bronze rows/day delta < 50% of trailing 7-day average → alert.
  - Silver rejection rate > 1% per rule → alert.
  - Orphan claims query (Q12) returns > 0 rows → alert.
- **Dashboard uptime:**
  - Streamlit health endpoint: does the app expose one?
  - Power BI dataset refresh failure alert.
- **Alerting channels:**
  - Data platform: email + Microsoft Teams channel.
  - Clinical (vital signs): separate on-call rotation.
  - Verify alerts are actually wired (not just documented).
- **Cost monitoring:**
  - Azure cost alerts per resource group.
  - Synapse DWU auto-pause configured for non-production hours.
  - Databricks cluster auto-termination after idle period.

================================================================================
## SECTION 11 — Deployment & Infrastructure
================================================================================
- **Docker:**
  - `docker-compose.yml`: SQL Server 2022 image pinned to specific version.
  - `Dockerfile.generator`: Python base image, deps installed, generators
    runnable as container commands.
  - `Dockerfile.streamlit`: Streamlit app containerized for deployment.
  - All Dockerfiles have `HEALTHCHECK` instructions.
  - `.dockerignore` excludes `data/`, `venv/`, `.git/`, `__pycache__/`.
- **Azure infrastructure:**
  - ARM templates or Terraform/Bicep for all Azure resources (ADLS, Synapse,
    Databricks, Event Hubs, Key Vault, ADF).
  - Infrastructure as Code is version-controlled and deployable to a fresh
    subscription.
  - Resource naming convention: `hcdw-{env}-{resource}-{region}`.
  - Tags: `project`, `environment`, `owner`, `cost-center`.
- **ADF deployment (`pipelines/adf_templates/`):**
  - ARM templates export cleanly from ADF Studio.
  - Parameterized for environment (dev/staging/prod): linked service
    endpoints, Key Vault references, trigger schedules.
  - CI/CD: ADF publish flow or manual deployment documented.
- **Environment promotion:**
  - Dev → Staging → Production pipeline.
  - Database schema changes applied via versioned SQL scripts (not manual).
  - Configuration differences between environments documented.
- **Rollback plan:**
  - Pipeline failure: re-run from checkpoint (streaming) or from Bronze
    (batch).
  - Schema change: reverse migration script or snapshot restore.
  - Azure resource: ARM template rollback or resource group restore.
- **Disaster recovery:**
  - RPO: how much data can we afford to lose? (Batch: up to last pipeline
    run; Streaming: up to last checkpoint).
  - RTO: how long to recover? Document per component.
  - Geo-redundancy: ADLS GRS, Synapse geo-backup, Event Hubs geo-DR.
  - DR drill: documented and tested.

================================================================================
## SECTION 12 — CI/CD Pipeline Hardening
================================================================================
- **Current state (`.github/workflows/ci.yml`):**
  - 5 jobs: lint, unit, spark-tests, sql-lint, docs.
  - `spark-tests`: `continue-on-error: true` — acceptable for CI but must
    not be ignored in pre-production.
  - `sql-lint`: `|| true` on sqlfluff — same concern.
- **Recommended additions for production:**
  - [ ] `pip audit` job for dependency vulnerabilities.
  - [ ] Docker image build + scan (Trivy or Snyk).
  - [ ] Integration test job: `make demo` on a clean environment.
  - [ ] SBOM generation (CycloneDX for Python).
  - [ ] Artifact publishing: tagged releases build and push Docker images
    to a container registry.
  - [ ] Branch protection: require all non-optional CI jobs to pass before
    merge to main.
- **Secrets in CI:**
  - GitHub Actions secrets for any Azure credentials used in integration
    tests.
  - No secrets printed in CI logs (`::add-mask::`).

================================================================================
## SECTION 13 — Arabic / Localization
================================================================================
- **UTF-8 everywhere:**
  - Python source files: `# -*- coding: utf-8 -*-` or Python 3 default.
  - CSV files generated by Synthea and claims generator: UTF-8 with BOM
    or without (document the convention).
  - JSON files: UTF-8.
  - SQL Server: `NVARCHAR` for all text columns that may contain Arabic.
  - Parquet: UTF-8 strings natively.
- **Arabic in hospital_seed.csv:**
  - Facility names, governorate names, addresses in Arabic.
  - Verify these flow correctly through all layers to Power BI/Streamlit.
  - No mojibake (garbled characters) at any stage.
- **Power BI RTL:**
  - Report pages support RTL layout for Arabic text.
  - Charts with Arabic labels render correctly.
  - Date format: Arabic or Western digits per user preference.
- **Streamlit Arabic:**
  - Page titles, labels, and tooltips support Arabic.
  - Plotly charts render Arabic text without fallback fonts.
- **Egyptian governorates:**
  - All 27 governorates present in reference data.
  - Governorate mapping in Silver layer (`governorate remap` mentioned in
    README) handles variant spellings (e.g., "القاهرة" vs "Cairo").

================================================================================
## SECTION 14 — Visualization & Reporting
================================================================================
- **Power BI (`dashboards/powerbi/`):**
  - `dax_measures.md`: DAX measures documented for: hospital utilization
    rate, bed occupancy, readmission rate (30-day), average length of stay,
    claim denial rate, revenue per encounter, ED throughput.
  - `report_design.md`: 3-page report layout (hospital utilization,
    readmission analysis, cost analysis) with filter context and drill-down.
  - Connection to Synapse: Import mode with scheduled refresh or DirectQuery.
  - Row-level security in Power BI: hospital-scoped access for facility
    managers.
- **Streamlit (`dashboards/streamlit/`):**
  - 3-page app: Overview, Detailed Analytics, Live Vital Signs.
  - Demo mode (`HCDW_DEMO_MODE=1`): uses pre-built Parquet fixtures from
    `build_demo_data.py`, no live Azure connection required.
  - `build_demo_data.py`: generates realistic aggregated data for all
    dashboard pages. Verify it runs without errors.
  - Error handling: graceful degradation if data source is unavailable.
  - No hardcoded file paths (use relative paths or environment variables).
- **Analytical queries (12 queries):**
  - Each query has a clear business question and expected output schema.
  - Results cross-validated between Synapse (SQL) and Streamlit (Python)
    for at least the top 3 KPIs.
  - Edge cases tested: empty date ranges, single-hospital filter, all-
    hospital aggregate.

================================================================================
## SECTION 15 — Documentation Completeness
================================================================================
Out of scope to polish, but verify these are not actively misleading:
- **`README.md`:** Architecture description matches actual implementation.
  File paths in project structure match reality.
- **`docs/architecture/overview.md`:** Azure services listed are actually
  used. Data flow diagram matches pipeline code.
- **`docs/architecture/er_diagram_oltp.md`:** Tables match
  `01_oltp_source_schema.sql`.
- **`docs/architecture/er_diagram_warehouse.md`:** Star schema matches
  `10_warehouse_schema.sql`.
- **`docs/data_dictionary/data_dictionary.md`:** Column definitions match
  actual schema. Data types accurate.
- **`docs/monitoring.md`:** Alert thresholds and runbook steps are
  actionable, not aspirational.
- **`docs/final_report.md`:** No outdated claims about features or metrics.
- **`CONTRIBUTING.md`:** Setup instructions actually work on a fresh clone.

================================================================================
## SECTION 16 — Compliance & Governance
================================================================================
- **Egyptian Data Protection Law (151/2020):**
  - Data subject rights: access, rectification, deletion — architecture
    supports these operations.
  - Consent: if patient data were real, consent capture mechanism exists.
  - Breach notification: process documented (NTRA within 72 hours).
  - Data Processing Agreement template for hospital tenants.
- **Egyptian Tax Law (claims/billing data):**
  - 5-year retention on financial records.
  - Audit trail on all financial transactions.
- **Medical data governance:**
  - Role-based access: clinical staff see patient data, analysts see
    aggregated/de-identified data, IT sees infrastructure metrics only.
  - Minimum necessary principle: each dashboard page shows only what that
    role needs.
- **Data lineage:**
  - Every record in Gold is traceable back to its Bronze source file.
  - `dw.load_audit` provides pipeline-level lineage.
  - Column-level lineage documented in data dictionary.
- **License compliance:**
  - Synthea: Apache 2.0 — compatible with commercial use.
  - PySpark: Apache 2.0.
  - Delta Lake: Apache 2.0.
  - All Python packages: verify no GPL/AGPL in `requirements.txt`
    transitive dependencies.

================================================================================
## EXECUTION METHODOLOGY
================================================================================
1. Run Pre-Flight checklist; output starting state.
2. Produce a numbered, prioritized **Blocking Issue Inventory** grouped by
   Critical / High / Medium. Critical = ship-stop. High = ship-stop unless
   risk-accepted. Medium = post-launch within 2 weeks.
3. Execute fixes top-down. After each fix:
   - `flake8` (zero new warnings)
   - `pytest` (no regression below baseline)
   - One PR-sized commit with prefix tag (PHI-, DQ-, SEC-, PIPE-, PERF-,
     OBS-, REL-, OPS-).
4. If any test below baseline fails after a fix: STOP, report, do not stack
   more changes on top.
5. Avoid scope creep. If you spot a lurking issue outside the immediate
   blocker, log it in the Risk Register, do not fix in the same commit.

================================================================================
## DELIVERABLES (at end of audit)
================================================================================
1. **Blocking Issue Inventory** (final state) — Critical / High / Medium,
   each with file paths, root cause, fix applied or pending, test added.
2. **Risk Register** — known limitations, accepted risks with owner and
   review date, deferred items with justification.
3. **Verification Log** — lint status, test counts, dependency CVE count,
   pipeline run summary (Bronze rows, Silver rejection rate, Gold row
   counts, streaming checkpoint health).
4. **Go / No-Go Recommendation** with explicit reasoning. If No-Go, the
   minimal critical path to Go.
5. **Rollback Plan** — exact steps to revert per environment tier (Azure
   resources, Synapse schema, ADLS data, Streamlit deployment).
6. **Operational Handover Note** — what changed, what to watch in the first
   72 hours of production, alert thresholds, on-call contacts.

================================================================================
## OUT OF SCOPE (do not touch unless directly tied to a blocker)
================================================================================
- New data sources or generators.
- Dashboard redesign.
- Cloud provider migration (Azure → AWS/GCP).
- Documentation polish.
- Mass dependency upgrades.
- Pipeline rewrite (PySpark → Polars, SQLAlchemy → raw pyodbc).
- Style-only refactoring.
- New analytical queries beyond the existing 12.

================================================================================

Begin with the Pre-Flight checklist and the Blocking Issue Inventory.
Do not write a single line of fix code until that inventory exists and is
prioritized.
