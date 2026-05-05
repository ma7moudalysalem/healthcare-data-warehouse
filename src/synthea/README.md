# Synthea

We use [Synthea](https://github.com/synthetichealth/synthea) (Apache 2.0)
to generate the patient/encounter/condition/medication tables that drive the
Bronze layer.

## Quick start

```bash
# Java 11+ required. Verify with: java -version
python -m src.synthea.run_synthea --population 1000      # smoke test, ~30s
python -m src.synthea.run_synthea --population 100000    # full project size, ~25 min
```

The first run downloads `synthea-with-dependencies.jar` (~50 MB) into this
folder. The jar is gitignored.

## Output

CSVs land in `src/synthea/output/csv/`, then `run_synthea.py` copies them to
`data/raw/synthea/`. Files we use:

| File             | Role in warehouse                    |
|------------------|--------------------------------------|
| patients.csv     | dim_patient (SCD2)                   |
| encounters.csv   | fact_encounter, drives bridge tables |
| conditions.csv   | bridge_encounter_condition           |
| medications.csv  | fact_prescription                    |
| procedures.csv   | bridge_encounter_procedure           |
| observations.csv | not used (Synthea labs replaced by IoT) |
| organizations.csv| reference for hospitals (rewritten)  |
| providers.csv    | dim_provider (merged with API data)  |
| payers.csv       | dim_carrier (merged with claims)     |

## Egyptian re-mapping

Synthea ships with US demographics. The Silver layer rewrites the
`address`, `city`, `state` and `county` columns to the hospital network's
governorates (Cairo, Giza, Alexandria, Menoufia, etc.) using the deterministic
mapping in `pipelines/silver/dim_patient_silver.py`.
