/* =========================================================================
   warehouse_azuresql.sql
   Azure SQL Database port of the gold-layer star schema (sql/ddl/10 + 11).

   The originals target a Synapse dedicated SQL pool. Azure SQL Database does
   NOT support DISTRIBUTION / CLUSTERED COLUMNSTORE on Basic tier, CTAS, or
   RANGE partitioning, so this file:
     * drops DISTRIBUTION = HASH/REPLICATE/ROUND_ROBIN and CLUSTERED COLUMNSTORE
     * rewrites dim_date's CTAS as CREATE TABLE + INSERT..SELECT
     * drops the fact_vital_signs_minute RANGE partition
     * keeps every column name/type identical, so the reporting views (and the
       Streamlit dashboard that reads them) are unchanged.
   Surrogate keys are plain BIGINT populated by the loader (deterministic
   hashes), so no IDENTITY / SEQUENCE is needed.
   Apply with: python scripts/apply_sql.py sql/ddl/azuresql/warehouse_azuresql.sql
   ========================================================================= */

IF SCHEMA_ID(N'dw')  IS NULL EXEC(N'CREATE SCHEMA dw');
IF SCHEMA_ID(N'stg') IS NULL EXEC(N'CREATE SCHEMA stg');
GO

/* ---- drop views (depend on tables) ---- */
IF OBJECT_ID(N'dw.vw_encounter_enriched', N'V') IS NOT NULL DROP VIEW dw.vw_encounter_enriched;
IF OBJECT_ID(N'dw.vw_claim_enriched',      N'V') IS NOT NULL DROP VIEW dw.vw_claim_enriched;
IF OBJECT_ID(N'dw.vw_vital_signs_minute',  N'V') IS NOT NULL DROP VIEW dw.vw_vital_signs_minute;
GO

/* ---- drop tables ---- */
IF OBJECT_ID(N'dw.fact_encounter', N'U')          IS NOT NULL DROP TABLE dw.fact_encounter;
IF OBJECT_ID(N'dw.fact_claim', N'U')              IS NOT NULL DROP TABLE dw.fact_claim;
IF OBJECT_ID(N'dw.fact_prescription', N'U')       IS NOT NULL DROP TABLE dw.fact_prescription;
IF OBJECT_ID(N'dw.fact_vital_signs_minute', N'U') IS NOT NULL DROP TABLE dw.fact_vital_signs_minute;
IF OBJECT_ID(N'dw.bridge_encounter_diagnosis', N'U') IS NOT NULL DROP TABLE dw.bridge_encounter_diagnosis;
IF OBJECT_ID(N'dw.dim_date', N'U')                IS NOT NULL DROP TABLE dw.dim_date;
IF OBJECT_ID(N'dw.dim_patient', N'U')             IS NOT NULL DROP TABLE dw.dim_patient;
IF OBJECT_ID(N'dw.dim_provider', N'U')            IS NOT NULL DROP TABLE dw.dim_provider;
IF OBJECT_ID(N'dw.dim_hospital', N'U')            IS NOT NULL DROP TABLE dw.dim_hospital;
IF OBJECT_ID(N'dw.dim_payer', N'U')               IS NOT NULL DROP TABLE dw.dim_payer;
IF OBJECT_ID(N'dw.dim_diagnosis', N'U')           IS NOT NULL DROP TABLE dw.dim_diagnosis;
IF OBJECT_ID(N'dw.dim_procedure', N'U')           IS NOT NULL DROP TABLE dw.dim_procedure;
IF OBJECT_ID(N'dw.dim_drug', N'U')                IS NOT NULL DROP TABLE dw.dim_drug;
IF OBJECT_ID(N'dw.load_audit', N'U')              IS NOT NULL DROP TABLE dw.load_audit;
GO

/* ---- DATE DIMENSION (CTAS -> CREATE + INSERT) ---- */
CREATE TABLE dw.dim_date
(
    date_sk            INT           NOT NULL PRIMARY KEY,
    calendar_date      DATE          NOT NULL,
    [year]             INT           NULL,
    [quarter]          INT           NULL,
    [month]            INT           NULL,
    month_name         NVARCHAR(20)  NULL,
    day_of_month       INT           NULL,
    day_of_week        INT           NULL,
    day_name           NVARCHAR(20)  NULL,
    iso_week           INT           NULL,
    is_weekend         BIT           NULL,
    is_month_start     BIT           NULL,
    month_end_date     DATE          NULL,
    quarter_start_date DATE          NULL
);
GO
INSERT INTO dw.dim_date
SELECT
    CONVERT(INT, FORMAT(d, 'yyyyMMdd')),
    d, YEAR(d), DATEPART(QUARTER, d), MONTH(d), DATENAME(MONTH, d),
    DAY(d), DATEPART(WEEKDAY, d), DATENAME(WEEKDAY, d), DATEPART(WEEK, d),
    CASE WHEN DATEPART(WEEKDAY, d) IN (1, 7) THEN 1 ELSE 0 END,
    CASE WHEN DAY(d) = 1 THEN 1 ELSE 0 END,
    EOMONTH(d),
    DATEFROMPARTS(YEAR(d), ((DATEPART(QUARTER, d) - 1) * 3) + 1, 1)
FROM (
    SELECT TOP (4748)
        DATEADD(DAY, ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1, '2018-01-01') AS d
    FROM sys.all_objects a CROSS JOIN sys.all_objects b
) AS s;
GO

/* ---- DIMENSIONS ---- */
CREATE TABLE dw.dim_patient
(
    patient_sk BIGINT NOT NULL PRIMARY KEY,
    patient_bk UNIQUEIDENTIFIER NOT NULL,
    mrn VARCHAR(20) NULL,
    first_name NVARCHAR(80) NULL, last_name NVARCHAR(80) NULL, full_name NVARCHAR(160) NULL,
    date_of_birth DATE NULL, age_band VARCHAR(20) NULL, gender CHAR(1) NULL,
    marital_status VARCHAR(20) NULL, race NVARCHAR(60) NULL, ethnicity NVARCHAR(60) NULL,
    governorate NVARCHAR(80) NULL, city NVARCHAR(80) NULL, is_deceased BIT NOT NULL,
    effective_from DATETIME2(0) NOT NULL, effective_to DATETIME2(0) NULL,
    is_current BIT NOT NULL, record_hash CHAR(64) NOT NULL
);
GO
CREATE TABLE dw.dim_provider
(
    provider_sk BIGINT NOT NULL PRIMARY KEY,
    provider_bk VARCHAR(15) NOT NULL,
    full_name NVARCHAR(160) NULL, credential VARCHAR(20) NULL, specialty NVARCHAR(80) NULL,
    primary_facility_sk BIGINT NULL, license_expiry DATE NULL, hire_date DATE NULL,
    is_active BIT NOT NULL,
    effective_from DATETIME2(0) NOT NULL, effective_to DATETIME2(0) NULL,
    is_current BIT NOT NULL, record_hash CHAR(64) NOT NULL
);
GO
CREATE TABLE dw.dim_hospital
(
    hospital_sk BIGINT NOT NULL PRIMARY KEY,
    hospital_bk VARCHAR(20) NOT NULL,
    hospital_name NVARCHAR(150) NOT NULL, facility_type VARCHAR(20) NOT NULL,
    city NVARCHAR(80) NULL, governorate NVARCHAR(80) NULL, bed_count INT NULL, is_active BIT NOT NULL,
    lat DECIMAL(9,6) NULL, lon DECIMAL(9,6) NULL
);
GO
CREATE TABLE dw.dim_payer
(
    payer_sk BIGINT NOT NULL PRIMARY KEY,
    payer_bk INT NULL, payer_name NVARCHAR(120) NOT NULL,
    is_government BIT NOT NULL, is_active BIT NOT NULL
);
GO
CREATE TABLE dw.dim_diagnosis
(
    diagnosis_sk BIGINT NOT NULL PRIMARY KEY,
    icd10_code VARCHAR(10) NOT NULL, description NVARCHAR(255) NULL, chapter NVARCHAR(120) NULL
);
GO
CREATE TABLE dw.dim_procedure
(
    procedure_sk BIGINT NOT NULL PRIMARY KEY,
    cpt_code VARCHAR(10) NOT NULL, description NVARCHAR(255) NULL, base_charge_usd DECIMAL(10,2) NULL
);
GO
CREATE TABLE dw.dim_drug
(
    drug_sk BIGINT NOT NULL PRIMARY KEY,
    rxnorm_code VARCHAR(15) NOT NULL, description NVARCHAR(255) NULL
);
GO

/* ---- FACTS ---- */
CREATE TABLE dw.fact_encounter
(
    encounter_sk BIGINT NOT NULL PRIMARY KEY,
    encounter_bk UNIQUEIDENTIFIER NOT NULL,
    patient_sk BIGINT NOT NULL, provider_sk BIGINT NULL, hospital_sk BIGINT NOT NULL,
    primary_diagnosis_sk BIGINT NULL, start_date_sk INT NOT NULL, end_date_sk INT NULL,
    encounter_class VARCHAR(30) NOT NULL, length_of_stay_hours DECIMAL(10,2) NULL,
    base_cost_usd DECIMAL(12,2) NULL, total_cost_usd DECIMAL(12,2) NULL,
    payer_coverage_usd DECIMAL(12,2) NULL, out_of_pocket_usd DECIMAL(12,2) NULL,
    is_inpatient BIT NOT NULL, is_emergency BIT NOT NULL, is_readmission_30d BIT NOT NULL,
    discharge_status VARCHAR(40) NULL,
    silver_loaded_at DATETIME2(0) NOT NULL, gold_loaded_at DATETIME2(0) NOT NULL
);
GO
CREATE TABLE dw.fact_claim
(
    claim_sk BIGINT NOT NULL PRIMARY KEY,
    claim_bk UNIQUEIDENTIFIER NOT NULL, claim_number VARCHAR(40) NOT NULL,
    encounter_sk BIGINT NULL, patient_sk BIGINT NULL, provider_sk BIGINT NULL,
    hospital_sk BIGINT NULL, payer_sk BIGINT NULL, primary_diagnosis_sk BIGINT NULL,
    service_date_sk INT NOT NULL, submission_date_sk INT NULL, decision_date_sk INT NULL,
    days_to_decision INT NULL, status VARCHAR(30) NOT NULL,
    is_denied BIT NOT NULL, is_paid_in_full BIT NOT NULL, line_count INT NOT NULL,
    billed_amount DECIMAL(12,2) NOT NULL, allowed_amount DECIMAL(12,2) NOT NULL,
    paid_amount DECIMAL(12,2) NOT NULL, denied_amount DECIMAL(12,2) NOT NULL,
    patient_responsibility DECIMAL(12,2) NOT NULL, currency CHAR(3) NOT NULL,
    silver_loaded_at DATETIME2(0) NOT NULL, gold_loaded_at DATETIME2(0) NOT NULL
);
GO
CREATE TABLE dw.fact_prescription
(
    prescription_sk BIGINT NOT NULL PRIMARY KEY,
    encounter_sk BIGINT NULL, patient_sk BIGINT NOT NULL, drug_sk BIGINT NOT NULL,
    start_date_sk INT NOT NULL, stop_date_sk INT NULL, therapy_duration_days INT NULL,
    dispenses INT NOT NULL, total_cost_usd DECIMAL(12,2) NULL
);
GO
CREATE TABLE dw.fact_vital_signs_minute
(
    vital_sk BIGINT NOT NULL PRIMARY KEY,
    patient_sk BIGINT NOT NULL, hospital_sk BIGINT NOT NULL,
    device_id VARCHAR(40) NOT NULL, bed_number VARCHAR(10) NULL,
    minute_start_utc DATETIME2(0) NOT NULL, date_sk INT NOT NULL, sample_count INT NOT NULL,
    heart_rate_avg DECIMAL(6,2) NULL, heart_rate_max DECIMAL(6,2) NULL, heart_rate_min DECIMAL(6,2) NULL,
    spo2_avg DECIMAL(5,2) NULL, spo2_min DECIMAL(5,2) NULL,
    systolic_avg DECIMAL(6,2) NULL, diastolic_avg DECIMAL(6,2) NULL,
    respiratory_rate_avg DECIMAL(5,2) NULL, temperature_c_avg DECIMAL(5,2) NULL,
    temperature_c_max DECIMAL(5,2) NULL, anomaly_event_count INT NOT NULL,
    primary_anomaly_kind VARCHAR(40) NULL
);
GO
CREATE TABLE dw.bridge_encounter_diagnosis
(
    encounter_sk BIGINT NOT NULL, diagnosis_sk BIGINT NOT NULL,
    is_primary BIT NOT NULL, severity VARCHAR(20) NULL
);
GO
CREATE TABLE dw.load_audit
(
    audit_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    layer VARCHAR(20) NOT NULL, object_name VARCHAR(120) NOT NULL,
    rows_read BIGINT NULL, rows_written BIGINT NULL, rows_rejected BIGINT NULL,
    started_at DATETIME2(0) NOT NULL, finished_at DATETIME2(0) NULL,
    status VARCHAR(20) NOT NULL, error_message NVARCHAR(MAX) NULL
);
GO

/* ---- REPORTING VIEWS (verbatim from sql/ddl/11_warehouse_views.sql) ---- */
CREATE VIEW dw.vw_encounter_enriched AS
SELECT
    fe.encounter_sk, fe.encounter_bk AS encounter_id, fe.encounter_class,
    fe.start_date_sk, dd.calendar_date AS encounter_date, dd.[year] AS encounter_year,
    dd.[month] AS encounter_month, dd.month_name AS encounter_month_name,
    dd.day_name AS encounter_day_of_week, fe.length_of_stay_hours,
    fe.is_inpatient, fe.is_emergency, fe.is_readmission_30d, fe.discharge_status,
    fe.total_cost_usd, fe.payer_coverage_usd, fe.out_of_pocket_usd,
    p.patient_bk AS patient_id, p.full_name AS patient_name, p.age_band, p.gender,
    p.governorate AS patient_governorate,
    h.hospital_bk AS hospital_code, h.hospital_name, h.facility_type,
    h.governorate AS hospital_governorate, h.bed_count,
    pr.full_name AS provider_name, pr.specialty AS provider_specialty,
    dx.icd10_code AS primary_icd10_code, dx.description AS primary_diagnosis,
    dx.chapter AS diagnosis_chapter
FROM dw.fact_encounter fe
JOIN dw.dim_date dd ON dd.date_sk = fe.start_date_sk
JOIN dw.dim_patient p ON p.patient_sk = fe.patient_sk AND p.is_current = 1
JOIN dw.dim_hospital h ON h.hospital_sk = fe.hospital_sk
LEFT JOIN dw.dim_provider pr ON pr.provider_sk = fe.provider_sk AND pr.is_current = 1
LEFT JOIN dw.dim_diagnosis dx ON dx.diagnosis_sk = fe.primary_diagnosis_sk;
GO
CREATE VIEW dw.vw_claim_enriched AS
SELECT
    fc.claim_sk, fc.claim_number, fc.status, fc.is_denied, fc.is_paid_in_full,
    fc.days_to_decision, fc.line_count, fc.billed_amount, fc.allowed_amount,
    fc.paid_amount, fc.denied_amount, fc.patient_responsibility, fc.currency,
    dd_serv.calendar_date AS service_date, dd_serv.[year] AS service_year,
    dd_serv.[month] AS service_month, dd_dec.calendar_date AS decision_date,
    payer.payer_name AS payer_name, payer.is_government AS is_government_payer,
    h.hospital_name AS hospital_name, h.facility_type AS facility_type,
    p.age_band AS patient_age_band, p.gender AS patient_gender,
    p.governorate AS patient_governorate,
    dx.icd10_code AS primary_icd10_code, dx.description AS primary_diagnosis
FROM dw.fact_claim fc
JOIN dw.dim_date dd_serv ON dd_serv.date_sk = fc.service_date_sk
LEFT JOIN dw.dim_date dd_dec ON dd_dec.date_sk = fc.decision_date_sk
LEFT JOIN dw.dim_payer payer ON payer.payer_sk = fc.payer_sk
LEFT JOIN dw.dim_hospital h ON h.hospital_sk = fc.hospital_sk
LEFT JOIN dw.dim_patient p ON p.patient_sk = fc.patient_sk AND p.is_current = 1
LEFT JOIN dw.dim_diagnosis dx ON dx.diagnosis_sk = fc.primary_diagnosis_sk;
GO
CREATE VIEW dw.vw_vital_signs_minute AS
SELECT
    vs.minute_start_utc, vs.device_id, vs.bed_number,
    p.patient_bk AS patient_id, p.full_name AS patient_name,
    h.hospital_name, h.governorate AS hospital_governorate,
    vs.heart_rate_avg, vs.heart_rate_min, vs.heart_rate_max,
    vs.spo2_avg, vs.spo2_min, vs.systolic_avg, vs.diastolic_avg,
    vs.respiratory_rate_avg, vs.temperature_c_avg, vs.temperature_c_max,
    vs.sample_count, vs.anomaly_event_count, vs.primary_anomaly_kind
FROM dw.fact_vital_signs_minute vs
JOIN dw.dim_patient p ON p.patient_sk = vs.patient_sk AND p.is_current = 1
JOIN dw.dim_hospital h ON h.hospital_sk = vs.hospital_sk;
GO
