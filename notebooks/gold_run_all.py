# Databricks notebook source
# MAGIC %md
# MAGIC # Gold - run-all driver
# MAGIC
# MAGIC Stages parquet files in `gold/staging/...` ready for ADF's COPY INTO
# MAGIC into Synapse. Order matters: dim_hospital first (its surrogate key is
# MAGIC needed by dim_provider), then patient, then provider, then facts.
# MAGIC
# MAGIC Parameters:
# MAGIC * `silver_root`         - abfss URI for silver
# MAGIC * `gold_root`           - abfss URI for gold
# MAGIC * `hospital_seed_csv`   - abfss URI of the hospital seed CSV (uploaded once)

# COMMAND ----------
silver_root        = dbutils.widgets.get("silver_root")
gold_root          = dbutils.widgets.get("gold_root")
hospital_seed_csv  = dbutils.widgets.get("hospital_seed_csv")

# COMMAND ----------
# MAGIC %sh
# MAGIC pip install -q -e /Workspace/Repos/healthcare-dw

# COMMAND ----------
from pipelines.gold.gold_load import (
    _dim_hospital_staging, _dim_patient_staging,
    _dim_provider_staging, _fact_encounter_staging, _fact_claim_staging,
)

silver = silver_root.rstrip("/")
gold   = gold_root.rstrip("/")

_dim_hospital_staging(spark, gold, hospital_seed_csv)
_dim_patient_staging(spark, silver, gold)
_dim_provider_staging(spark, silver, gold)
_fact_encounter_staging(spark, silver, gold)
_fact_claim_staging(spark, silver, gold)

print("Gold staging complete.")
