# OLTP Source - ER Diagram

This is the source operational model that feeds the Bronze layer. The
warehouse star schema (Gold) is in `er_diagram_warehouse.md`.

```mermaid
erDiagram
    HOSPITAL ||--o{ ENCOUNTER : "hosts"
    HOSPITAL ||--o{ PROVIDER  : "primary_facility"
    HOSPITAL ||--o{ CLAIM     : "billed_for"

    PATIENT  ||--o{ ENCOUNTER  : "has"
    PATIENT  ||--o{ CONDITION  : "diagnosed_with"
    PATIENT  ||--o{ MEDICATION : "prescribed"
    PATIENT  ||--o{ PROCEDURE  : "underwent"
    PATIENT  ||--o{ CLAIM      : "filed_by"

    PROVIDER ||--o{ ENCOUNTER  : "performed_by"
    PROVIDER ||--o{ CLAIM      : "submitted_by"

    ENCOUNTER ||--o{ CONDITION  : "documented"
    ENCOUNTER ||--o{ MEDICATION : "ordered"
    ENCOUNTER ||--o{ PROCEDURE  : "performed"
    ENCOUNTER ||--o| CLAIM      : "billed"

    PAYER ||--o{ CLAIM : "covers"

    CLAIM ||--|{ CLAIM_LINE : "details"

    HOSPITAL {
        string hospital_code PK
        string hospital_name
        string city
        string governorate
        int    bed_count
        bool   is_clinic
        bool   is_active
    }

    PATIENT {
        uuid   patient_id PK
        string mrn
        string first_name
        string last_name
        date   date_of_birth
        char   gender
        string governorate
        date   deceased_date
    }

    PROVIDER {
        string provider_npi PK
        string first_name
        string last_name
        string specialty
        string primary_facility FK
        bool   is_active
    }

    ENCOUNTER {
        uuid   encounter_id PK
        uuid   patient_id FK
        string provider_npi FK
        string hospital_code FK
        string encounter_class
        datetime start_at
        datetime end_at
        decimal total_cost_usd
        bool   is_readmission_30d
    }

    CONDITION {
        bigint condition_id PK
        uuid   encounter_id FK
        uuid   patient_id FK
        string icd10_code
        date   onset_date
        bool   is_chronic
    }

    MEDICATION {
        bigint medication_id PK
        uuid   encounter_id FK
        uuid   patient_id FK
        string rxnorm_code
        date   start_date
        decimal total_cost_usd
    }

    PROCEDURE {
        bigint procedure_id PK
        uuid   encounter_id FK
        uuid   patient_id FK
        string cpt_code
        datetime performed_at
        decimal base_cost_usd
    }

    PAYER {
        int    payer_id PK
        string payer_name
        bool   is_government
    }

    CLAIM {
        uuid   claim_id PK
        string claim_number
        uuid   encounter_id FK
        uuid   patient_id FK
        string hospital_code FK
        int    payer_id FK
        date   service_date
        string status
        decimal billed_amount
        decimal paid_amount
    }

    CLAIM_LINE {
        bigint claim_line_id PK
        uuid   claim_id FK
        int    line_number
        string cpt_code
        decimal billed_amount
    }
```

## Notes

* `claim.encounter_id` and `claim.patient_id` are **soft FKs**. Real claim
  feeds frequently arrive before the matching encounter has finished
  posting, so we accept orphans and surface the unmatched rate as a Silver
  data-quality KPI rather than rejecting at insert time.
* `encounter.provider_npi` is nullable in the source because Synthea doesn't
  always emit a provider; the Silver layer joins to the provider API to
  fill the gap before the Gold dimension is built.
* All clinical tables carry both `encounter_id` and `patient_id` for query
  ergonomics - it lets analysts filter by patient without a join.
