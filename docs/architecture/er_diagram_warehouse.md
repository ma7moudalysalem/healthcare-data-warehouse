# Warehouse - Star Schema (Gold)

This is the Synapse / Power BI-facing model. Source-system grain is in
`er_diagram_oltp.md`. Bronze and Silver layers are flat copies and cleaned
versions of these same tables; the model below is the analytical contract.

```mermaid
erDiagram
    DIM_DATE       ||--o{ FACT_ENCOUNTER         : "start_date_sk"
    DIM_DATE       ||--o{ FACT_CLAIM             : "service_date_sk"
    DIM_DATE       ||--o{ FACT_PRESCRIPTION      : "start_date_sk"
    DIM_DATE       ||--o{ FACT_VITAL_SIGNS_MIN   : "date_sk"

    DIM_PATIENT    ||--o{ FACT_ENCOUNTER         : "patient_sk"
    DIM_PATIENT    ||--o{ FACT_CLAIM             : "patient_sk"
    DIM_PATIENT    ||--o{ FACT_PRESCRIPTION      : "patient_sk"
    DIM_PATIENT    ||--o{ FACT_VITAL_SIGNS_MIN   : "patient_sk"

    DIM_PROVIDER   ||--o{ FACT_ENCOUNTER         : "provider_sk"
    DIM_PROVIDER   ||--o{ FACT_CLAIM             : "provider_sk"

    DIM_HOSPITAL   ||--o{ FACT_ENCOUNTER         : "hospital_sk"
    DIM_HOSPITAL   ||--o{ FACT_CLAIM             : "hospital_sk"
    DIM_HOSPITAL   ||--o{ FACT_VITAL_SIGNS_MIN   : "hospital_sk"

    DIM_PAYER      ||--o{ FACT_CLAIM             : "payer_sk"

    DIM_DIAGNOSIS  ||--o{ FACT_ENCOUNTER         : "primary_diagnosis_sk"
    DIM_DIAGNOSIS  ||--o{ FACT_CLAIM             : "primary_diagnosis_sk"
    DIM_DIAGNOSIS  ||--o{ BRIDGE_ENCOUNTER_DIAGNOSIS : "diagnosis_sk"

    DIM_DRUG       ||--o{ FACT_PRESCRIPTION      : "drug_sk"

    FACT_ENCOUNTER ||--|{ BRIDGE_ENCOUNTER_DIAGNOSIS : "encounter_sk"

    DIM_DATE {
        int  date_sk PK
        date calendar_date
        int  year
        int  quarter
        int  month
        string month_name
        string day_name
        bool is_weekend
    }

    DIM_PATIENT {
        bigint patient_sk PK
        uuid   patient_bk
        string mrn
        string full_name
        date   date_of_birth
        string age_band
        char   gender
        string governorate
        bool   is_deceased
        datetime effective_from
        datetime effective_to
        bool   is_current
        char   record_hash
    }

    DIM_PROVIDER {
        bigint provider_sk PK
        string provider_bk
        string full_name
        string credential
        string specialty
        bigint primary_facility_sk FK
        date   license_expiry
        bool   is_active
        datetime effective_from
        datetime effective_to
        bool   is_current
        char   record_hash
    }

    DIM_HOSPITAL {
        bigint hospital_sk PK
        string hospital_bk
        string hospital_name
        string facility_type
        string governorate
        int    bed_count
        bool   is_active
    }

    DIM_PAYER {
        bigint payer_sk PK
        int    payer_bk
        string payer_name
        bool   is_government
    }

    DIM_DIAGNOSIS {
        bigint diagnosis_sk PK
        string icd10_code
        string description
        string chapter
    }

    DIM_DRUG {
        bigint drug_sk PK
        string rxnorm_code
        string description
    }

    FACT_ENCOUNTER {
        bigint encounter_sk PK
        bigint patient_sk FK
        bigint provider_sk FK
        bigint hospital_sk FK
        bigint primary_diagnosis_sk FK
        int    start_date_sk FK
        string encounter_class
        decimal length_of_stay_hours
        decimal total_cost_usd
        bool   is_inpatient
        bool   is_emergency
        bool   is_readmission_30d
    }

    FACT_CLAIM {
        bigint claim_sk PK
        bigint encounter_sk FK
        bigint patient_sk FK
        bigint payer_sk FK
        int    service_date_sk FK
        string status
        bool   is_denied
        decimal billed_amount
        decimal paid_amount
        decimal denied_amount
    }

    FACT_PRESCRIPTION {
        bigint prescription_sk PK
        bigint patient_sk FK
        bigint drug_sk FK
        int    start_date_sk FK
        int    therapy_duration_days
        decimal total_cost_usd
    }

    FACT_VITAL_SIGNS_MIN {
        bigint vital_sk PK
        bigint patient_sk FK
        bigint hospital_sk FK
        datetime minute_start_utc
        int    date_sk FK
        decimal heart_rate_avg
        decimal spo2_avg
        int    anomaly_event_count
    }

    BRIDGE_ENCOUNTER_DIAGNOSIS {
        bigint encounter_sk FK
        bigint diagnosis_sk FK
        bool   is_primary
        string severity
    }
```

## Distribution and storage choices (Synapse dedicated SQL pool)

| Table                       | Distribution     | Reason |
|-----------------------------|------------------|--------|
| dim_date                    | REPLICATE        | Tiny, joined on every query |
| dim_patient                 | HASH(patient_sk) | Largest dimension |
| dim_provider, dim_hospital, dim_payer, dim_diagnosis, dim_drug | REPLICATE | Small enough |
| fact_encounter              | HASH(patient_sk) | Co-locates with dim_patient |
| fact_claim                  | HASH(encounter_sk) | Most joins go through encounter |
| fact_prescription           | HASH(patient_sk) | Patient-centric analytics |
| fact_vital_signs_minute     | HASH(patient_sk), PARTITION(date_sk RANGE RIGHT) | Heaviest fact, partitioned by quarter |
| bridge_encounter_diagnosis  | HASH(encounter_sk) | Co-located with fact_encounter |

All facts and dimensions use **clustered columnstore** indexes - the working
load is analytical scans, not point-lookups.

## SCD2 mechanics

`dim_patient` and `dim_provider` track history via three columns:

| Column         | Meaning                                            |
|----------------|----------------------------------------------------|
| effective_from | When this row became current (UTC).                |
| effective_to   | When the row was superseded. NULL on the live row. |
| is_current     | Convenience flag, redundant with effective_to.     |

The merge logic (`sp_merge_dim_patient_scd2`) uses a SHA-256 hash over the
SCD2 attribute set. Hash mismatch -> close current row + insert new version.
Reporting views always filter `is_current = 1`; if you need point-in-time
reporting, join on `start_date BETWEEN effective_from AND ISNULL(effective_to, '9999-12-31')`.

## Date dimension range

`dim_date` is populated from **2018-01-01 through 2030-12-31**. That's 8 years
of history (matching Synthea's `generate.years_of_history = 8`) plus enough
forward room for prescription stop dates, license expiries and quarterly
forecasts.
