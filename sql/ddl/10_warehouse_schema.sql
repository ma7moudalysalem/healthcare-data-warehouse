/* =========================================================================
   10_warehouse_schema.sql
   Gold-layer star schema for Azure Synapse (dedicated SQL pool).

   Conventions:
   * surrogate keys are BIGINT IDENTITY, named <dim>_sk
   * natural / business keys are kept on each dimension as <dim>_bk
   * SCD2 dimensions carry effective_from / effective_to / is_current
   * date_sk is YYYYMMDD (INT) so dimension joins don't require a lookup
   * fact grain is one row per encounter (fact_encounter), one row per claim
     (fact_claim), one row per prescription (fact_prescription) and one row
     per minute per device (fact_vital_signs_minute)

   Distribution / index choices target the analytical workload described
   in the design doc:
       * dim_patient is HASH(patient_sk)            - the largest dim
       * dim_provider/dim_hospital are REPLICATE    - small, joined often
       * fact_encounter HASH(patient_sk)            - co-located with dim_patient
       * fact_claim     HASH(encounter_sk)          - 1:1 with encounters
       * fact_vital_signs_minute HASH(patient_sk) PARTITION (date_sk)
   ========================================================================= */

USE healthcare_dw;
GO

IF SCHEMA_ID(N'dw')   IS NULL EXEC(N'CREATE SCHEMA dw');
IF SCHEMA_ID(N'stg')  IS NULL EXEC(N'CREATE SCHEMA stg');
GO

/* -------------------------------------------------------------------------
   DATE DIMENSION
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.dim_date', N'U') IS NULL
CREATE TABLE dw.dim_date
WITH (DISTRIBUTION = REPLICATE, CLUSTERED COLUMNSTORE INDEX)
AS
SELECT
    CONVERT(INT, FORMAT(d, 'yyyyMMdd'))                          AS date_sk,
    d                                                            AS calendar_date,
    YEAR(d)                                                      AS [year],
    DATEPART(QUARTER, d)                                         AS [quarter],
    MONTH(d)                                                     AS [month],
    DATENAME(MONTH, d)                                           AS month_name,
    DAY(d)                                                       AS day_of_month,
    DATEPART(WEEKDAY, d)                                         AS day_of_week,
    DATENAME(WEEKDAY, d)                                         AS day_name,
    DATEPART(WEEK, d)                                            AS iso_week,
    CASE WHEN DATEPART(WEEKDAY, d) IN (1, 7) THEN 1 ELSE 0 END   AS is_weekend,
    CASE WHEN DAY(d) = 1 THEN 1 ELSE 0 END                       AS is_month_start,
    EOMONTH(d)                                                   AS month_end_date,
    DATEFROMPARTS(YEAR(d), ((DATEPART(QUARTER, d) - 1) * 3) + 1, 1) AS quarter_start_date
FROM (
    SELECT TOP (4748)
        DATEADD(DAY, ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1, '2018-01-01') AS d
    FROM sys.all_objects a CROSS JOIN sys.all_objects b
) AS s;
GO

/* -------------------------------------------------------------------------
   PATIENT DIMENSION (SCD Type 2)
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.dim_patient', N'U') IS NULL
CREATE TABLE dw.dim_patient
(
    patient_sk          BIGINT          NOT NULL,    -- surrogate
    patient_bk          UNIQUEIDENTIFIER NOT NULL,   -- natural key from OLTP
    mrn                 VARCHAR(20)     NOT NULL,
    first_name          NVARCHAR(80)    NULL,
    last_name           NVARCHAR(80)    NULL,
    full_name           NVARCHAR(160)   NULL,
    date_of_birth       DATE            NULL,
    age_band            VARCHAR(20)     NULL,        -- "0-17", "18-34", ...
    gender              CHAR(1)         NULL,
    marital_status      VARCHAR(20)     NULL,
    race                NVARCHAR(60)    NULL,
    ethnicity           NVARCHAR(60)    NULL,
    governorate         NVARCHAR(80)    NULL,
    city                NVARCHAR(80)    NULL,
    is_deceased         BIT             NOT NULL,
    -- SCD2 metadata
    effective_from      DATETIME2(0)    NOT NULL,
    effective_to        DATETIME2(0)    NULL,
    is_current          BIT             NOT NULL,
    record_hash         CHAR(64)        NOT NULL     -- SHA256 of attribute set
)
WITH (DISTRIBUTION = HASH(patient_sk), CLUSTERED COLUMNSTORE INDEX);
GO

/* -------------------------------------------------------------------------
   PROVIDER DIMENSION (SCD Type 2)
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.dim_provider', N'U') IS NULL
CREATE TABLE dw.dim_provider
(
    provider_sk         BIGINT          NOT NULL,
    provider_bk         VARCHAR(15)     NOT NULL,    -- NPI
    full_name           NVARCHAR(160)   NULL,
    credential          VARCHAR(20)     NULL,
    specialty           NVARCHAR(80)    NULL,
    primary_facility_sk BIGINT          NULL,
    license_expiry      DATE            NULL,
    hire_date           DATE            NULL,
    is_active           BIT             NOT NULL,
    effective_from      DATETIME2(0)    NOT NULL,
    effective_to        DATETIME2(0)    NULL,
    is_current          BIT             NOT NULL,
    record_hash         CHAR(64)        NOT NULL
)
WITH (DISTRIBUTION = REPLICATE, CLUSTERED COLUMNSTORE INDEX);
GO

/* -------------------------------------------------------------------------
   HOSPITAL DIMENSION (SCD Type 1 - rarely changes)
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.dim_hospital', N'U') IS NULL
CREATE TABLE dw.dim_hospital
(
    hospital_sk         BIGINT          NOT NULL,
    hospital_bk         VARCHAR(20)     NOT NULL,
    hospital_name       NVARCHAR(150)   NOT NULL,
    facility_type       VARCHAR(20)     NOT NULL,    -- 'hospital' | 'clinic'
    city                NVARCHAR(80)    NULL,
    governorate         NVARCHAR(80)    NULL,
    bed_count           INT             NULL,
    is_active           BIT             NOT NULL
)
WITH (DISTRIBUTION = REPLICATE, CLUSTERED COLUMNSTORE INDEX);
GO

/* -------------------------------------------------------------------------
   PAYER / CARRIER DIMENSION
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.dim_payer', N'U') IS NULL
CREATE TABLE dw.dim_payer
(
    payer_sk         BIGINT       NOT NULL,
    payer_bk         INT          NULL,              -- ref.payer.payer_id
    payer_name       NVARCHAR(120) NOT NULL,
    is_government    BIT          NOT NULL,
    is_active        BIT          NOT NULL
)
WITH (DISTRIBUTION = REPLICATE, CLUSTERED COLUMNSTORE INDEX);
GO

/* -------------------------------------------------------------------------
   DIAGNOSIS / PROCEDURE / DRUG DIMENSIONS (degenerate, code-based)
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.dim_diagnosis', N'U') IS NULL
CREATE TABLE dw.dim_diagnosis
(
    diagnosis_sk     BIGINT       NOT NULL,
    icd10_code       VARCHAR(10)  NOT NULL,
    description      NVARCHAR(255) NULL,
    chapter          NVARCHAR(120) NULL
)
WITH (DISTRIBUTION = REPLICATE, CLUSTERED COLUMNSTORE INDEX);
GO

IF OBJECT_ID(N'dw.dim_procedure', N'U') IS NULL
CREATE TABLE dw.dim_procedure
(
    procedure_sk     BIGINT       NOT NULL,
    cpt_code         VARCHAR(10)  NOT NULL,
    description      NVARCHAR(255) NULL,
    base_charge_usd  DECIMAL(10,2) NULL
)
WITH (DISTRIBUTION = REPLICATE, CLUSTERED COLUMNSTORE INDEX);
GO

IF OBJECT_ID(N'dw.dim_drug', N'U') IS NULL
CREATE TABLE dw.dim_drug
(
    drug_sk          BIGINT       NOT NULL,
    rxnorm_code      VARCHAR(15)  NOT NULL,
    description      NVARCHAR(255) NULL
)
WITH (DISTRIBUTION = REPLICATE, CLUSTERED COLUMNSTORE INDEX);
GO

/* -------------------------------------------------------------------------
   FACT - ENCOUNTER
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.fact_encounter', N'U') IS NULL
CREATE TABLE dw.fact_encounter
(
    encounter_sk            BIGINT          NOT NULL,
    encounter_bk            UNIQUEIDENTIFIER NOT NULL,
    patient_sk              BIGINT          NOT NULL,
    provider_sk             BIGINT          NULL,
    hospital_sk             BIGINT          NOT NULL,
    primary_diagnosis_sk    BIGINT          NULL,
    start_date_sk           INT             NOT NULL,
    end_date_sk             INT             NULL,
    encounter_class         VARCHAR(30)     NOT NULL,
    length_of_stay_hours    DECIMAL(10,2)   NULL,
    base_cost_usd           DECIMAL(12,2)   NULL,
    total_cost_usd          DECIMAL(12,2)   NULL,
    payer_coverage_usd      DECIMAL(12,2)   NULL,
    out_of_pocket_usd       DECIMAL(12,2)   NULL,
    is_inpatient            BIT             NOT NULL,
    is_emergency            BIT             NOT NULL,
    is_readmission_30d      BIT             NOT NULL,
    discharge_status        VARCHAR(40)     NULL,
    -- audit
    silver_loaded_at        DATETIME2(0)    NOT NULL,
    gold_loaded_at          DATETIME2(0)    NOT NULL
)
WITH (DISTRIBUTION = HASH(patient_sk), CLUSTERED COLUMNSTORE INDEX);
GO

/* -------------------------------------------------------------------------
   FACT - CLAIM (1 row per claim, line-level rolled up)
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.fact_claim', N'U') IS NULL
CREATE TABLE dw.fact_claim
(
    claim_sk                BIGINT          NOT NULL,
    claim_bk                UNIQUEIDENTIFIER NOT NULL,
    claim_number            VARCHAR(40)     NOT NULL,
    encounter_sk            BIGINT          NULL,    -- nullable: orphan claims allowed
    patient_sk              BIGINT          NULL,
    provider_sk             BIGINT          NULL,
    hospital_sk             BIGINT          NULL,
    payer_sk                BIGINT          NULL,
    primary_diagnosis_sk    BIGINT          NULL,
    service_date_sk         INT             NOT NULL,
    submission_date_sk      INT             NULL,
    decision_date_sk        INT             NULL,
    days_to_decision        INT             NULL,
    status                  VARCHAR(30)     NOT NULL,
    is_denied               BIT             NOT NULL,
    is_paid_in_full         BIT             NOT NULL,
    line_count              INT             NOT NULL,
    billed_amount           DECIMAL(12,2)   NOT NULL,
    allowed_amount          DECIMAL(12,2)   NOT NULL,
    paid_amount             DECIMAL(12,2)   NOT NULL,
    denied_amount           DECIMAL(12,2)   NOT NULL,
    patient_responsibility  DECIMAL(12,2)   NOT NULL,
    currency                CHAR(3)         NOT NULL,
    silver_loaded_at        DATETIME2(0)    NOT NULL,
    gold_loaded_at          DATETIME2(0)    NOT NULL
)
WITH (DISTRIBUTION = HASH(encounter_sk), CLUSTERED COLUMNSTORE INDEX);
GO

/* -------------------------------------------------------------------------
   FACT - PRESCRIPTION (1 row per medication line)
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.fact_prescription', N'U') IS NULL
CREATE TABLE dw.fact_prescription
(
    prescription_sk         BIGINT          NOT NULL,
    encounter_sk            BIGINT          NULL,
    patient_sk              BIGINT          NOT NULL,
    drug_sk                 BIGINT          NOT NULL,
    start_date_sk           INT             NOT NULL,
    stop_date_sk            INT             NULL,
    therapy_duration_days   INT             NULL,
    dispenses               INT             NOT NULL,
    total_cost_usd          DECIMAL(12,2)   NULL
)
WITH (DISTRIBUTION = HASH(patient_sk), CLUSTERED COLUMNSTORE INDEX);
GO

/* -------------------------------------------------------------------------
   FACT - VITAL SIGNS (1 row per device per minute)
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.fact_vital_signs_minute', N'U') IS NULL
CREATE TABLE dw.fact_vital_signs_minute
(
    vital_sk                BIGINT          NOT NULL,
    patient_sk              BIGINT          NOT NULL,
    hospital_sk             BIGINT          NOT NULL,
    device_id               VARCHAR(40)     NOT NULL,
    bed_number              VARCHAR(10)     NULL,
    minute_start_utc        DATETIME2(0)    NOT NULL,
    date_sk                 INT             NOT NULL,
    sample_count            INT             NOT NULL,
    heart_rate_avg          DECIMAL(6,2)    NULL,
    heart_rate_max          DECIMAL(6,2)    NULL,
    heart_rate_min          DECIMAL(6,2)    NULL,
    spo2_avg                DECIMAL(5,2)    NULL,
    spo2_min                DECIMAL(5,2)    NULL,
    systolic_avg            DECIMAL(6,2)    NULL,
    diastolic_avg           DECIMAL(6,2)    NULL,
    respiratory_rate_avg    DECIMAL(5,2)    NULL,
    temperature_c_avg       DECIMAL(5,2)    NULL,
    temperature_c_max       DECIMAL(5,2)    NULL,
    anomaly_event_count     INT             NOT NULL,
    primary_anomaly_kind    VARCHAR(40)     NULL
)
WITH (
    DISTRIBUTION = HASH(patient_sk),
    CLUSTERED COLUMNSTORE INDEX,
    PARTITION (date_sk RANGE RIGHT FOR VALUES (
        20240101, 20240401, 20240701, 20241001,
        20250101, 20250401, 20250701, 20251001,
        20260101, 20260401
    ))
);
GO

/* -------------------------------------------------------------------------
   BRIDGE - encounter <-> diagnosis (many-to-many)
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.bridge_encounter_diagnosis', N'U') IS NULL
CREATE TABLE dw.bridge_encounter_diagnosis
(
    encounter_sk     BIGINT NOT NULL,
    diagnosis_sk     BIGINT NOT NULL,
    is_primary       BIT    NOT NULL,
    severity         VARCHAR(20) NULL
)
WITH (DISTRIBUTION = HASH(encounter_sk), CLUSTERED COLUMNSTORE INDEX);
GO

/* -------------------------------------------------------------------------
   AUDIT - load runs
   ------------------------------------------------------------------------- */
IF OBJECT_ID(N'dw.load_audit', N'U') IS NULL
CREATE TABLE dw.load_audit
(
    audit_id        BIGINT IDENTITY(1,1) NOT NULL,
    layer           VARCHAR(20)  NOT NULL,    -- bronze|silver|gold
    object_name     VARCHAR(120) NOT NULL,
    rows_read       BIGINT       NULL,
    rows_written    BIGINT       NULL,
    rows_rejected   BIGINT       NULL,
    started_at      DATETIME2(0) NOT NULL,
    finished_at     DATETIME2(0) NULL,
    status          VARCHAR(20)  NOT NULL,    -- success|failed|partial
    error_message   NVARCHAR(MAX) NULL
)
WITH (DISTRIBUTION = ROUND_ROBIN, HEAP);
GO

PRINT 'Warehouse star schema created (dw schema).';
GO
