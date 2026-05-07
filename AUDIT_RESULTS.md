# Production Readiness Audit Results

**Audit Date:** 2026-05-07
**Baseline Commit:** `159782b`
**Auditor:** Mahmoud Salem

---

## 1. Pre-Flight Verification Log

| Check | Result |
|-------|--------|
| `git status` | Clean (3 untracked: review doc, dev guide PDF/TeX) |
| `flake8` (src/ tests/ pipelines/ dashboards/) | 0 errors (post-fix) |
| `pytest` (54 tests, excl. Spark) | **54/54 passed** |
| Spark tests (`test_silver_common.py`) | Skipped (requires Java + Spark runtime) |
| Dependency CVEs (`pip audit`) | Tool not installed; recommend adding `pip-audit` to CI |
| Docker services | `docker-compose.yml` validated syntactically |
| SQL DDL files | All 5 DDL files valid UTF-8, non-empty, with GO terminators |
| SQL queries | All 12 queries reference `dw.*` schema |
| Stored procedures | All 3 use `CREATE OR ALTER` |
| Makefile targets | `lint`, `test-fast`, `test` all pass |
| `.gitignore` | Covers `.env`, `data/`, `venv/`, `*.py[cod]`, Synthea output |

---

## 2. Blocking Issue Inventory

### Critical (Ship-Stop) - FIXED

| # | Class | File | Issue | Fix Applied |
|---|-------|------|-------|-------------|
| 1 | SEC | `pipelines/load_oltp.py:74` | Hardcoded default SA password `YourStrong!Passw0rd` as fallback when `MSSQL_SA_PASSWORD` env var is missing. Any run without `.env` silently connects with known credentials. | Removed default; now raises `SystemExit` with instructions to set the env var. |
| 2 | SEC | `dashboards/streamlit/app.py:110-114` | SQL injection via f-string interpolation of user-selected hospital name directly into SQL WHERE clause (`hospital_name = '{selected_hospital}'`). An adversarial selectbox value or future text input could execute arbitrary SQL. | Rewrote `_filter_clause()` to return parameterized query (`?` placeholders) + params list. Both operations page and revenue page now use `pd.read_sql(sql, conn, params=...)`. |
| 3 | SEC | `docker/docker-compose.yml:9` | Hardcoded default SA password in compose file via `${MSSQL_SA_PASSWORD:-YourStrong!Passw0rd}`. Starting without `.env` exposes a known password. | Changed to `${MSSQL_SA_PASSWORD:?Set MSSQL_SA_PASSWORD in .env}` which fails-fast if unset. |

### High (Ship-Stop Unless Risk-Accepted) - FIXED

| # | Class | File | Issue | Fix Applied |
|---|-------|------|-------|-------------|
| 4 | DQ | `dashboards/streamlit/app.py:26` | `DEMO_MODE` logic bug: `not DEMO_DIR.exists() is False` always evaluates to `True` due to operator precedence (`is` binds tighter than `not`). Dashboard never connects to Synapse even when configured. | Fixed to `not DEMO_DIR.exists()` — correct boolean logic. |
| 5 | PIPE | `pipelines/bronze/bronze_ingest.py:155` | Uses `datetime.utcnow()` which is deprecated in Python 3.12+ and returns a naive datetime. | Replaced with `datetime.now(dt.timezone.utc)` for timezone-aware UTC. |

### Medium (Post-Launch Within 2 Weeks) - FIXED

| # | Class | File | Issue | Fix Applied |
|---|-------|------|-------|-------------|
| 6 | SEC | `dashboards/streamlit/app.py:181-183` | Second SQL injection in revenue page via f-string hospital name filter. | Fixed alongside #2 with parameterized queries. |
| 7 | PERF | `pipelines/silver/silver_common.py:122` | `df.rdd.isEmpty()` triggers a full Spark job to check emptiness. | Replaced with `len(df.head(1)) == 0` which short-circuits after one row. |
| 8 | OBS | `.github/workflows/ci.yml:68` | `sqlfluff lint sql/ --dialect tsql \|\| true` silences all SQL lint failures. Broken SQL passes CI. | Removed `\|\| true`; SQL lint failures now block merge. |
| 9 | DQ | `dashboards/streamlit/build_demo_data.py` | Multiple flake8 violations: E702 (semicolons), E231 (spacing), E501 (line length), affecting CI. | Reformatted: split semicolons to separate lines, broke long lines. |
| 10 | DQ | `dashboards/streamlit/app.py:135,141,142` | E712 flake8 warnings: `== True` comparisons on pandas boolean columns. | Changed to `.eq(True)` method calls. |

---

## 3. Risk Register (Known Limitations)

| # | Area | Risk | Severity | Mitigation | Review By |
|---|------|------|----------|------------|-----------|
| R1 | SEC | `pip audit` not in CI pipeline; dependency CVEs not gated | Medium | ~~Add `pip-audit` job to `ci.yml`~~ **RESOLVED** - `dependency-audit` job added | Done |
| R2 | SEC | Flask `provider_api.py` uses development server; no auth | Low | Document as local-dev-only; not exposed in Docker compose ports (only on generator container) | N/A |
| R3 | PIPE | Spark tests in CI use `continue-on-error: true`; failures don't block | Medium | ~~Require Spark tests in pre-release gate~~ **RESOLVED** - `continue-on-error` removed | Done |
| R4 | PERF | `bronze_ingest.py` calls `df.count()` after write (line 83) which triggers a redundant Spark job | Low | Accepted trade-off: count is now emitted via structured logger for observability | N/A |
| R5 | DQ | Claims generator creates random UUIDs for `patient_id`/`encounter_id` that don't match Synthea output; orphan claims are expected by design (Q12) | Informational | Documented in `generate_claims.py:103-105` |  N/A |
| R6 | PIPE | `load_oltp.py` uses `DELETE` cascade instead of `TRUNCATE` due to FK constraints; slower on large volumes | Low | Acceptable for reload frequency (daily batch) | N/A |
| R7 | DQ | `.env.example` contains `YourStrong!Passw0rd` as placeholder text | Low | Standard practice; actual `.env` is gitignored | N/A |
| R8 | OBS | No structured logging framework (Serilog equivalent); pipelines use `print()` to stderr | Medium | ~~Add `logging` module with JSON formatter~~ **RESOLVED** - `pipelines/logging_config.py` with JSON/text formatters; all pipeline modules migrated | Done |
| R9 | SEC | Synapse connection in `app.py` uses `UID/PWD`; should migrate to Azure AD auth for production | Medium | ~~Use `azure-identity` + `pyodbc` token auth~~ **RESOLVED** - `SYNAPSE_AUTH_METHOD=azure_ad` uses `DefaultAzureCredential` | Done |
| R10 | PIPE | No explicit retry/backoff on OLTP connection failures in `load_oltp.py` | Medium | ~~Add manual retry with backoff~~ **RESOLVED** - 3 retries with exponential backoff | Done |

---

## 4. Verification Log (Post-Fix)

| Metric | Before Audit | After Audit |
|--------|-------------|-------------|
| flake8 errors (src/tests/pipelines/dashboards) | 13 | 0 |
| pytest passed | 54/54 | 54/54 |
| Hardcoded secrets in source | 2 occurrences | 0 |
| SQL injection vectors | 2 (app.py) | 0 |
| CI silent failures | 2 (sqlfluff, spark) | 0 |
| Logic bugs | 1 (DEMO_MODE) | 0 |
| Deprecated API usage | 1 (utcnow) | 0 |
| Pipeline modules using print() | 9 | 0 |
| Structured logging coverage | none | all pipelines |
| Azure AD auth support | none | DefaultAzureCredential |
| CI dependency audit | missing | pip-audit job |
| dashboards/ in CI lint | excluded | included |

---

## 5. Go / No-Go Recommendation

### GO (Conditional)

The codebase is production-ready with the fixes applied in this audit. All critical and high-severity blockers have been resolved:

**Strengths:**
- Well-structured Medallion Architecture with clear layer boundaries
- Comprehensive DQ rules with quarantine layer at every Silver transform
- SCD Type 2 properly implemented with stored procedures
- Deterministic data generation (seeded RNG across all generators)
- Star schema with appropriate Synapse distribution/partitioning
- Streaming pipeline with proper watermarking and anomaly detection
- 54 passing tests covering generators, API, SQL, and project structure

**Conditions for Go:**
1. Run Spark integration tests (`test_silver_common.py`) on a machine with Java + Spark before deploying Silver/Gold transforms
2. Add `pip-audit` to CI within first sprint post-launch
3. Migrate Synapse auth from UID/PWD to Azure AD before production data access (R9)
4. Add structured logging before production monitoring is needed (R8)

---

## 6. Files Changed

| File | Change |
|------|--------|
| `pipelines/load_oltp.py` | SEC: Remove hardcoded default SA password; add retry/backoff; structured logging |
| `docker/docker-compose.yml` | SEC: Fail-fast on missing SA password |
| `dashboards/streamlit/app.py` | SEC: Parameterized SQL queries; fix DEMO_MODE logic; fix E712; Azure AD auth |
| `dashboards/streamlit/build_demo_data.py` | DQ: Fix flake8 violations (E702, E231, E501) |
| `pipelines/logging_config.py` | NEW: Structured logging with JSON/text formatters |
| `pipelines/bronze/bronze_ingest.py` | PIPE: Replace deprecated `utcnow()`; structured logging |
| `pipelines/gold/gold_load.py` | OBS: Structured logging |
| `pipelines/streaming/vitals_streaming.py` | OBS: Structured logging |
| `pipelines/silver/silver_common.py` | PERF: Replace `rdd.isEmpty()` with `head(1)`; structured logging |
| `pipelines/silver/silver_dim_patient.py` | OBS: Structured logging |
| `pipelines/silver/silver_dim_provider.py` | OBS: Structured logging |
| `pipelines/silver/silver_fact_encounter.py` | OBS: Structured logging |
| `pipelines/silver/silver_fact_claim.py` | OBS: Structured logging |
| `.github/workflows/ci.yml` | CI: Remove `\|\| true`; remove `continue-on-error`; add `pip-audit` job; add `dashboards/` to flake8 |
| `.sqlfluff` | NEW: SQLFluff configuration for tsql dialect |
| `PRODUCTION_READINESS_REVIEW.md` | NEW: Full 16-section audit template |
| `AUDIT_RESULTS.md` | NEW: This file |
