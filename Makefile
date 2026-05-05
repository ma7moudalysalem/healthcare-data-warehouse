# Convenience targets for the healthcare data warehouse.
# Use GNU Make 4.x. On Windows, run from a Git Bash / WSL shell.

PY ?= python
PIP ?= pip
DATA_RAW ?= data/raw

.PHONY: help install synthea-smoke synthea-full claims providers vitals \
        oltp-up oltp-init oltp-load \
        bronze silver gold demo-data \
        streamlit lint test test-fast clean

help:
	@echo "Targets:"
	@echo "  install          - install Python deps"
	@echo "  synthea-smoke    - 1K patient Synthea run (~30s)"
	@echo "  synthea-full     - 100K patient Synthea run (~25 min)"
	@echo "  claims           - 200K-row claims JSONL"
	@echo "  providers        - dump providers.json + start API"
	@echo "  vitals           - 60s of stdout vitals (smoke test)"
	@echo "  oltp-up          - bring up SQL Server in Docker"
	@echo "  oltp-init        - create schema + seed reference tables"
	@echo "  oltp-load        - load Synthea + claims into OLTP"
	@echo "  bronze           - run all Bronze ingests"
	@echo "  silver           - run all Silver transforms"
	@echo "  gold             - stage Gold parquet"
	@echo "  demo-data        - build Streamlit demo Parquet fixtures"
	@echo "  streamlit        - run dashboard (demo mode)"
	@echo "  demo             - end-to-end local demo (no Azure required)"
	@echo "  lint test        - flake8 + pytest"

install:
	$(PIP) install -r requirements.txt

synthea-smoke:
	$(PY) -m src.synthea.run_synthea --population 1000

synthea-full:
	$(PY) -m src.synthea.run_synthea --population 100000

claims:
	$(PY) -m src.generators.generate_claims --count 200000

providers:
	$(PY) -m src.generators.provider_api

vitals:
	$(PY) -m src.generators.simulate_vitals --rate 1 --devices 5 --duration 60 --stdout

oltp-up:
	docker compose -f docker/docker-compose.yml up -d sqlserver

oltp-init:
	sqlcmd -S localhost -U sa -P "$$MSSQL_SA_PASSWORD" -C -i sql/ddl/01_oltp_source_schema.sql
	sqlcmd -S localhost -U sa -P "$$MSSQL_SA_PASSWORD" -C -i sql/ddl/02_oltp_seed_reference.sql

oltp-load:
	$(PY) -m pipelines.load_oltp --truncate

bronze:
	$(PY) -m pipelines.bronze.bronze_ingest --source synthea   --input $(DATA_RAW)/synthea         --layer-root data/bronze
	$(PY) -m pipelines.bronze.bronze_ingest --source claims    --input $(DATA_RAW)/claims.jsonl    --layer-root data/bronze
	$(PY) -m pipelines.bronze.bronze_ingest --source providers --input $(DATA_RAW)/providers.json  --layer-root data/bronze

silver:
	$(PY) -m pipelines.silver.silver_dim_patient    --bronze-root data/bronze --silver-root data/silver --quarantine-root data/silver_quarantine
	$(PY) -m pipelines.silver.silver_dim_provider   --bronze-root data/bronze --silver-root data/silver --quarantine-root data/silver_quarantine
	$(PY) -m pipelines.silver.silver_fact_encounter --bronze-root data/bronze --silver-root data/silver --quarantine-root data/silver_quarantine
	$(PY) -m pipelines.silver.silver_fact_claim     --bronze-root data/bronze --silver-root data/silver --quarantine-root data/silver_quarantine

gold:
	$(PY) -m pipelines.gold.gold_load \
		--silver-root data/silver \
		--gold-root data/gold \
		--hospital-seed-csv config/hospital_seed.csv

demo-data:
	$(PY) dashboards/streamlit/build_demo_data.py

streamlit:
	HCDW_DEMO_MODE=1 streamlit run dashboards/streamlit/app.py

demo:
	$(PY) -m scripts.demo_local

lint:
	flake8 src/ tests/ pipelines/ --max-line-length=120 --exclude=__pycache__,build,dist

test-fast:
	pytest tests/ -v --tb=short --ignore=tests/test_silver_common.py

test:
	pytest tests/ -v --tb=short

clean:
	rm -rf data/bronze data/silver data/silver_quarantine data/gold
	rm -rf dashboards/streamlit/demo_data
	find . -type d -name __pycache__ -exec rm -rf {} +
