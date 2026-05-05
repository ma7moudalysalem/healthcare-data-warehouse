# Databricks notebook source
# MAGIC %md
# MAGIC # Silver - run-all driver
# MAGIC
# MAGIC Called by `PL_Daily_Bronze_Silver_Gold` (ADF). Runs each Silver-layer
# MAGIC transform in parallel via `dbutils.notebook.run` and a thread pool, so
# MAGIC the four jobs share one cluster instead of provisioning four.
# MAGIC
# MAGIC Parameters:
# MAGIC * `bronze_root`     - abfss URI for bronze
# MAGIC * `silver_root`     - abfss URI for silver
# MAGIC * `quarantine_root` - abfss URI for the quarantine path
# MAGIC * `run_id`          - opaque correlation id

# COMMAND ----------
from concurrent.futures import ThreadPoolExecutor, as_completed

bronze_root     = dbutils.widgets.get("bronze_root")
silver_root     = dbutils.widgets.get("silver_root")
quarantine_root = dbutils.widgets.get("quarantine_root")
run_id          = dbutils.widgets.get("run_id")

print(f"run_id={run_id}")
print(f"bronze_root={bronze_root}")
print(f"silver_root={silver_root}")
print(f"quarantine_root={quarantine_root}")

# COMMAND ----------
JOBS = [
    ("silver_dim_patient",    "./silver_dim_patient_nb"),
    ("silver_dim_provider",   "./silver_dim_provider_nb"),
    ("silver_fact_encounter", "./silver_fact_encounter_nb"),
    ("silver_fact_claim",     "./silver_fact_claim_nb"),
]

ARGS = {
    "bronze_root": bronze_root,
    "silver_root": silver_root,
    "quarantine_root": quarantine_root,
    "run_id": run_id,
}


def _run(name: str, path: str) -> tuple[str, str]:
    print(f"[{name}] starting")
    result = dbutils.notebook.run(path, 0, ARGS)
    print(f"[{name}] returned {result!r}")
    return name, result


# COMMAND ----------
errors: list[tuple[str, BaseException]] = []
with ThreadPoolExecutor(max_workers=len(JOBS)) as pool:
    futures = {pool.submit(_run, name, path): name for name, path in JOBS}
    for fut in as_completed(futures):
        name = futures[fut]
        try:
            fut.result()
        except BaseException as e:  # noqa: BLE001
            errors.append((name, e))

if errors:
    msg = "; ".join(f"{n}: {e}" for n, e in errors)
    raise RuntimeError(f"Silver run failed: {msg}")

print("All Silver jobs completed.")
