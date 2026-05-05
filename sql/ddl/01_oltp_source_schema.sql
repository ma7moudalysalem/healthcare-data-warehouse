/* =========================================================================
   01_oltp_source_schema.sql
   Source OLTP schema for the Healthcare Data Warehouse.

   This is the operational database the hospitals would write into. Synthea
   CSVs and the custom claim/vital/provider feeds are loaded here first, and
   then ADF copies the tables into the Bronze data lake nightly.

   Target: SQL Server 2019+ (also runs on Azure SQL DB).
   Run order: 01 -> 02 -> 03.
   ========================================================================= */

IF DB_ID(N'healthcare_oltp') IS NULL
BEGIN
    PRINT 'Database healthcare_oltp does not exist. Create it first:';
    PRINT '    CREATE DATABASE healthcare_oltp;';
    PRINT 'Then re-run this script.';
    SET NOEXEC ON;
END
GO

USE healthcare_oltp;
GO

/* ---------- Schemas ----------------------------------------------------- */
IF SCHEMA_ID(N'clinical') IS NULL EXEC(N'CREATE SCHEMA clinical');
IF SCHEMA_ID(N'billing')  IS NULL EXEC(N'CREATE SCHEMA billing');
IF SCHEMA_ID(N'ref')      IS NULL EXEC(N'CREATE SCHEMA ref');
GO

/* ---------- Reference tables ------------------------------------------- */
IF OBJECT_ID(N'ref.hospital', N'U') IS NULL
CREATE TABLE ref.hospital (
    hospital_code    VARCHAR(20)   NOT NULL PRIMARY KEY,
    hospital_name    NVARCHAR(150) NOT NULL,
    city             NVARCHAR(80)  NOT NULL,
    governorate      NVARCHAR(80)  NULL,
    bed_count        INT           NOT NULL DEFAULT 0,
    is_clinic        BIT           NOT NULL DEFAULT 0,
    opened_on        DATE          NULL,
    is_active        BIT           NOT NULL DEFAULT 1,
    created_at       DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at       DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME()
);

IF OBJECT_ID(N'ref.icd10', N'U') IS NULL
CREATE TABLE ref.icd10 (
    icd10_code       VARCHAR(10)   NOT NULL PRIMARY KEY,
    description      NVARCHAR(255) NOT NULL,
    chapter          NVARCHAR(120) NULL
);

IF OBJECT_ID(N'ref.cpt', N'U') IS NULL
CREATE TABLE ref.cpt (
    cpt_code         VARCHAR(10)   NOT NULL PRIMARY KEY,
    description      NVARCHAR(255) NOT NULL,
    base_charge_usd  DECIMAL(10,2) NOT NULL
);

IF OBJECT_ID(N'ref.rxnorm', N'U') IS NULL
CREATE TABLE ref.rxnorm (
    rxnorm_code      VARCHAR(15)   NOT NULL PRIMARY KEY,
    description      NVARCHAR(255) NOT NULL
);

IF OBJECT_ID(N'ref.payer', N'U') IS NULL
CREATE TABLE ref.payer (
    payer_id         INT IDENTITY(1,1) PRIMARY KEY,
    payer_name       NVARCHAR(120) NOT NULL UNIQUE,
    is_government    BIT           NOT NULL DEFAULT 0,
    is_active        BIT           NOT NULL DEFAULT 1
);
GO

/* ---------- Clinical core ---------------------------------------------- */
IF OBJECT_ID(N'clinical.patient', N'U') IS NULL
CREATE TABLE clinical.patient (
    patient_id          UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
    mrn                 VARCHAR(20)      NOT NULL UNIQUE,  -- medical record number
    first_name          NVARCHAR(80)     NOT NULL,
    last_name           NVARCHAR(80)     NOT NULL,
    date_of_birth       DATE             NOT NULL,
    gender              CHAR(1)          NOT NULL CHECK (gender IN ('M', 'F', 'U')),
    marital_status      VARCHAR(20)      NULL,
    race                NVARCHAR(60)     NULL,
    ethnicity           NVARCHAR(60)     NULL,
    address_line        NVARCHAR(200)    NULL,
    city                NVARCHAR(80)     NULL,
    governorate         NVARCHAR(80)     NULL,
    postal_code         VARCHAR(15)      NULL,
    country             NVARCHAR(60)     NOT NULL DEFAULT N'Egypt',
    phone               VARCHAR(30)      NULL,
    deceased_date       DATE             NULL,
    created_at          DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at          DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME()
);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_patient_mrn')
    CREATE INDEX ix_patient_mrn ON clinical.patient(mrn);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_patient_city')
    CREATE INDEX ix_patient_city ON clinical.patient(city);
GO

IF OBJECT_ID(N'clinical.provider', N'U') IS NULL
CREATE TABLE clinical.provider (
    provider_npi        VARCHAR(15)   NOT NULL PRIMARY KEY,
    first_name          NVARCHAR(80)  NOT NULL,
    last_name           NVARCHAR(80)  NOT NULL,
    credential          VARCHAR(20)   NULL,
    specialty           NVARCHAR(80)  NULL,
    primary_facility    VARCHAR(20)   NULL REFERENCES ref.hospital(hospital_code),
    license_number      VARCHAR(40)   NULL,
    license_expiry      DATE          NULL,
    hire_date           DATE          NULL,
    is_active           BIT           NOT NULL DEFAULT 1,
    phone               VARCHAR(30)   NULL,
    email               VARCHAR(120)  NULL,
    created_at          DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at          DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'clinical.encounter', N'U') IS NULL
CREATE TABLE clinical.encounter (
    encounter_id        UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
    patient_id          UNIQUEIDENTIFIER NOT NULL REFERENCES clinical.patient(patient_id),
    provider_npi        VARCHAR(15)      NULL REFERENCES clinical.provider(provider_npi),
    hospital_code       VARCHAR(20)      NOT NULL REFERENCES ref.hospital(hospital_code),
    encounter_class     VARCHAR(30)      NOT NULL,  -- ambulatory|emergency|inpatient|wellness|...
    encounter_type      NVARCHAR(120)    NULL,      -- free text e.g. "Encounter for check up"
    reason_code         VARCHAR(30)      NULL,
    reason_description  NVARCHAR(255)    NULL,
    start_at            DATETIME2(0)     NOT NULL,
    end_at              DATETIME2(0)     NULL,
    base_cost_usd       DECIMAL(12,2)    NULL,
    total_cost_usd      DECIMAL(12,2)    NULL,
    payer_coverage_usd  DECIMAL(12,2)    NULL,
    discharge_status    VARCHAR(40)      NULL,      -- routine|expired|transfer|ama|...
    is_readmission_30d  BIT              NOT NULL DEFAULT 0,
    created_at          DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME()
);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_encounter_patient_start')
    CREATE INDEX ix_encounter_patient_start ON clinical.encounter(patient_id, start_at);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_encounter_hospital_start')
    CREATE INDEX ix_encounter_hospital_start ON clinical.encounter(hospital_code, start_at);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_encounter_class')
    CREATE INDEX ix_encounter_class ON clinical.encounter(encounter_class);
GO

IF OBJECT_ID(N'clinical.condition', N'U') IS NULL
CREATE TABLE clinical.condition (
    condition_id        BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    encounter_id        UNIQUEIDENTIFIER NOT NULL REFERENCES clinical.encounter(encounter_id),
    patient_id          UNIQUEIDENTIFIER NOT NULL REFERENCES clinical.patient(patient_id),
    icd10_code          VARCHAR(10)      NOT NULL,
    description         NVARCHAR(255)    NULL,
    onset_date          DATE             NOT NULL,
    abated_date         DATE             NULL,
    severity            VARCHAR(20)      NULL,      -- mild|moderate|severe
    is_chronic          BIT              NOT NULL DEFAULT 0
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_condition_patient')
    CREATE INDEX ix_condition_patient ON clinical.condition(patient_id, onset_date);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_condition_icd10')
    CREATE INDEX ix_condition_icd10 ON clinical.condition(icd10_code);
GO

IF OBJECT_ID(N'clinical.medication', N'U') IS NULL
CREATE TABLE clinical.medication (
    medication_id       BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    encounter_id        UNIQUEIDENTIFIER NOT NULL REFERENCES clinical.encounter(encounter_id),
    patient_id          UNIQUEIDENTIFIER NOT NULL REFERENCES clinical.patient(patient_id),
    rxnorm_code         VARCHAR(15)      NOT NULL,
    description         NVARCHAR(255)    NULL,
    start_date          DATE             NOT NULL,
    stop_date           DATE             NULL,
    daily_dose_mg       DECIMAL(10,2)    NULL,
    cost_per_unit_usd   DECIMAL(10,2)    NULL,
    dispenses           INT              NOT NULL DEFAULT 1,
    total_cost_usd      DECIMAL(12,2)    NULL
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_medication_patient')
    CREATE INDEX ix_medication_patient ON clinical.medication(patient_id, start_date);
GO

IF OBJECT_ID(N'clinical.procedure_event', N'U') IS NULL
CREATE TABLE clinical.procedure_event (
    procedure_id        BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    encounter_id        UNIQUEIDENTIFIER NOT NULL REFERENCES clinical.encounter(encounter_id),
    patient_id          UNIQUEIDENTIFIER NOT NULL REFERENCES clinical.patient(patient_id),
    cpt_code            VARCHAR(10)      NOT NULL,
    description         NVARCHAR(255)    NULL,
    performed_at        DATETIME2(0)     NOT NULL,
    base_cost_usd       DECIMAL(10,2)    NULL,
    reason_code         VARCHAR(30)      NULL,
    reason_description  NVARCHAR(255)    NULL
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_procedure_patient')
    CREATE INDEX ix_procedure_patient ON clinical.procedure_event(patient_id, performed_at);
GO

/* ---------- Billing ---------------------------------------------------- */
IF OBJECT_ID(N'billing.claim', N'U') IS NULL
CREATE TABLE billing.claim (
    claim_id                UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
    claim_number            VARCHAR(40)      NOT NULL UNIQUE,
    encounter_id            UNIQUEIDENTIFIER NULL,    -- FK softly enforced; orphans land in DQ
    patient_id              UNIQUEIDENTIFIER NULL,
    provider_npi            VARCHAR(15)      NULL,
    hospital_code           VARCHAR(20)      NULL REFERENCES ref.hospital(hospital_code),
    payer_id                INT              NULL REFERENCES ref.payer(payer_id),
    policy_number           VARCHAR(40)      NULL,
    primary_diagnosis_code  VARCHAR(10)      NULL,
    service_date            DATE             NOT NULL,
    submission_date         DATE             NULL,
    decision_date           DATE             NULL,
    status                  VARCHAR(30)      NOT NULL,
    denial_reason           NVARCHAR(255)    NULL,
    billed_amount           DECIMAL(12,2)    NOT NULL,
    allowed_amount          DECIMAL(12,2)    NOT NULL DEFAULT 0,
    paid_amount             DECIMAL(12,2)    NOT NULL DEFAULT 0,
    patient_responsibility  DECIMAL(12,2)    NOT NULL DEFAULT 0,
    currency                CHAR(3)          NOT NULL DEFAULT 'EGP',
    raw_payload             NVARCHAR(MAX)    NULL,    -- original JSON for replay
    ingested_at             DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME()
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_claim_status_service')
    CREATE INDEX ix_claim_status_service ON billing.claim(status, service_date);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_claim_encounter')
    CREATE INDEX ix_claim_encounter ON billing.claim(encounter_id);
GO

IF OBJECT_ID(N'billing.claim_line', N'U') IS NULL
CREATE TABLE billing.claim_line (
    claim_line_id   BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    claim_id        UNIQUEIDENTIFIER NOT NULL REFERENCES billing.claim(claim_id) ON DELETE CASCADE,
    line_number     INT              NOT NULL,
    cpt_code        VARCHAR(10)      NULL,
    description     NVARCHAR(255)    NULL,
    units           INT              NOT NULL DEFAULT 1,
    billed_amount   DECIMAL(12,2)    NOT NULL,
    CONSTRAINT uq_claim_line UNIQUE(claim_id, line_number)
);
GO

PRINT 'OLTP schema created (clinical, billing, ref).';
GO
