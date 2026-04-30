-- SECTION 1: DROP EXISTING TABLES (Clean Slate)
-- ============================================================

IF OBJECT_ID('dbo.fact_vitals',     'U') IS NOT NULL DROP TABLE dbo.fact_vitals;
IF OBJECT_ID('dbo.fact_claims',     'U') IS NOT NULL DROP TABLE dbo.fact_claims;
IF OBJECT_ID('dbo.fact_encounters', 'U') IS NOT NULL DROP TABLE dbo.fact_encounters;
IF OBJECT_ID('dbo.dim_patient',     'U') IS NOT NULL DROP TABLE dbo.dim_patient;
IF OBJECT_ID('dbo.dim_provider',    'U') IS NOT NULL DROP TABLE dbo.dim_provider;
IF OBJECT_ID('dbo.dim_date',        'U') IS NOT NULL DROP TABLE dbo.dim_date;
IF OBJECT_ID('dbo.dim_time',        'U') IS NOT NULL DROP TABLE dbo.dim_time;
IF OBJECT_ID('dbo.dim_diagnosis',   'U') IS NOT NULL DROP TABLE dbo.dim_diagnosis;
IF OBJECT_ID('dbo.dim_payer',       'U') IS NOT NULL DROP TABLE dbo.dim_payer;

-- ============================================================
-- SECTION 2: DIMENSION TABLES
-- All dimensions use REPLICATE distribution (small lookup tables
-- broadcast to every compute node to avoid shuffle on joins)
-- ============================================================

-- ------------------------------------------------------------
-- dim_patient  —  SCD Type 2
-- Tracks historical changes to insurance_type, city/state (address)
-- Surrogate key: patient_key (INT IDENTITY)
-- Natural key:   patient_id (NVARCHAR — original Synthea UUID)
-- ------------------------------------------------------------
CREATE TABLE dbo.dim_patient
(
    patient_key         INT             NOT NULL,   -- surrogate PK
    patient_id          NVARCHAR(50)    NOT NULL,   -- natural key (Synthea UUID)
    first_name          NVARCHAR(100)   NOT NULL,
    last_name           NVARCHAR(100)   NOT NULL,
    birth_date          DATE            NOT NULL,
    gender              NVARCHAR(10)    NOT NULL,   -- M / F / Other
    race                NVARCHAR(50)    NULL,
    ethnicity           NVARCHAR(50)    NULL,
    city                NVARCHAR(100)   NULL,
    state               NVARCHAR(50)    NULL,
    zip_code            NVARCHAR(20)    NULL,
    insurance_type      NVARCHAR(50)    NULL,       -- private / medicaid / medicare / self-pay
    marital_status      NVARCHAR(20)    NULL,
    -- SCD Type 2 columns
    valid_from          DATE            NOT NULL DEFAULT CAST(GETDATE() AS DATE),
    valid_to            DATE            NULL,       -- NULL = current row
    is_current          BIT             NOT NULL DEFAULT 1,
    -- Derived / computed
    age_at_load         AS DATEDIFF(YEAR, birth_date, GETDATE()),
    age_group           AS CASE
                            WHEN DATEDIFF(YEAR, birth_date, GETDATE()) < 18  THEN '0-17'
                            WHEN DATEDIFF(YEAR, birth_date, GETDATE()) < 35  THEN '18-34'
                            WHEN DATEDIFF(YEAR, birth_date, GETDATE()) < 50  THEN '35-49'
                            WHEN DATEDIFF(YEAR, birth_date, GETDATE()) < 65  THEN '50-64'
                            ELSE '65+'
                           END,
    row_hash            NVARCHAR(64)    NULL        -- SHA-256 of SCD-tracked columns for change detection
)
WITH
(
    DISTRIBUTION = REPLICATE,
    CLUSTERED COLUMNSTORE INDEX
);

-- ------------------------------------------------------------
-- dim_provider  —  SCD Type 2
-- Tracks specialty and organization changes
-- ------------------------------------------------------------
CREATE TABLE dbo.dim_provider
(
    provider_key        INT             NOT NULL,
    provider_id         NVARCHAR(50)    NOT NULL,
    provider_name       NVARCHAR(200)   NOT NULL,
    specialty           NVARCHAR(100)   NULL,
    sub_specialty       NVARCHAR(100)   NULL,
    organization        NVARCHAR(200)   NULL,
    city                NVARCHAR(100)   NULL,
    state               NVARCHAR(50)    NULL,
    npi_number          NVARCHAR(20)    NULL,       -- National Provider Identifier
    -- SCD Type 2 columns
    valid_from          DATE            NOT NULL DEFAULT CAST(GETDATE() AS DATE),
    valid_to            DATE            NULL,
    is_current          BIT             NOT NULL DEFAULT 1,
    row_hash            NVARCHAR(64)    NULL
)
WITH
(
    DISTRIBUTION = REPLICATE,
    CLUSTERED COLUMNSTORE INDEX
);

-- ------------------------------------------------------------
-- dim_date  —  Static / Type 0
-- Pre-populated calendar dimension (2010-2035)
-- ------------------------------------------------------------
CREATE TABLE dbo.dim_date
(
    date_key            INT             NOT NULL,   -- YYYYMMDD format e.g. 20240115
    full_date           DATE            NOT NULL,
    year                SMALLINT        NOT NULL,
    quarter             TINYINT         NOT NULL,   -- 1-4
    quarter_name        NVARCHAR(10)    NOT NULL,   -- Q1, Q2, Q3, Q4
    month               TINYINT         NOT NULL,   -- 1-12
    month_name          NVARCHAR(15)    NOT NULL,   -- January … December
    month_short         NVARCHAR(5)     NOT NULL,   -- Jan … Dec
    week_of_year        TINYINT         NOT NULL,
    day_of_month        TINYINT         NOT NULL,
    day_of_week         TINYINT         NOT NULL,   -- 1=Sunday … 7=Saturday
    day_name            NVARCHAR(15)    NOT NULL,
    is_weekend          BIT             NOT NULL,
    is_holiday          BIT             NOT NULL DEFAULT 0,
    holiday_name        NVARCHAR(100)   NULL,
    fiscal_year         SMALLINT        NOT NULL,   -- Fiscal year starts July 1
    fiscal_quarter      TINYINT         NOT NULL,
    fiscal_month        TINYINT         NOT NULL,
    days_in_month       TINYINT         NOT NULL,
    is_last_day_of_month BIT            NOT NULL DEFAULT 0,
    iso_week            TINYINT         NOT NULL,
    year_month          NVARCHAR(7)     NOT NULL    -- YYYY-MM
)
WITH
(
    DISTRIBUTION = REPLICATE,
    CLUSTERED COLUMNSTORE INDEX
);

-- ------------------------------------------------------------
-- dim_time  —  Static / Type 0
-- Hour-level granularity for vital signs time analysis
-- ------------------------------------------------------------
CREATE TABLE dbo.dim_time
(
    time_key            INT             NOT NULL,   -- HHMM integer e.g. 1430
    hour                TINYINT         NOT NULL,   -- 0-23
    minute              TINYINT         NOT NULL,   -- 0-59
    hour_minute         NVARCHAR(5)     NOT NULL,   -- HH:MM
    am_pm               NVARCHAR(2)     NOT NULL,
    shift               NVARCHAR(20)    NOT NULL,   -- Morning(6-14)/Afternoon(14-22)/Night(22-6)
    shift_period        NVARCHAR(10)    NOT NULL,   -- Early/Mid/Late within shift
    is_business_hour    BIT             NOT NULL    -- 08:00-17:00
)
WITH
(
    DISTRIBUTION = REPLICATE,
    CLUSTERED COLUMNSTORE INDEX
);

-- ------------------------------------------------------------
-- dim_diagnosis  —  Static / Type 1
-- ICD-10 code lookup table
-- ------------------------------------------------------------
CREATE TABLE dbo.dim_diagnosis
(
    diagnosis_key       INT             NOT NULL,
    icd10_code          NVARCHAR(10)    NOT NULL,
    description         NVARCHAR(500)   NOT NULL,
    category_code       NVARCHAR(10)    NULL,       -- 3-character ICD chapter
    category_name       NVARCHAR(200)   NULL,
    body_system         NVARCHAR(100)   NULL,       -- Cardiovascular / Respiratory / etc.
    is_chronic          BIT             NOT NULL DEFAULT 0,
    is_communicable     BIT             NOT NULL DEFAULT 0,
    severity_level      NVARCHAR(20)    NULL        -- Low / Medium / High / Critical
)
WITH
(
    DISTRIBUTION = REPLICATE,
    CLUSTERED COLUMNSTORE INDEX
);

-- ------------------------------------------------------------
-- dim_payer  —  Type 1 (overwrite on change)
-- Insurance payer reference
-- ------------------------------------------------------------
CREATE TABLE dbo.dim_payer
(
    payer_key           INT             NOT NULL,
    payer_id            NVARCHAR(50)    NOT NULL,
    payer_name          NVARCHAR(200)   NOT NULL,
    payer_type          NVARCHAR(50)    NOT NULL,   -- private / medicaid / medicare / self-pay / other
    plan_name           NVARCHAR(200)   NULL,
    state_code          NVARCHAR(5)     NULL,       -- State payer operates in
    is_government       BIT             NOT NULL DEFAULT 0
)
WITH
(
    DISTRIBUTION = REPLICATE,
    CLUSTERED COLUMNSTORE INDEX
);

-- ============================================================
-- SECTION 3: FACT TABLES
-- All facts HASH distributed on patient_key (most common join
-- attribute) for data co-location and reduced shuffle.
-- Columnstore indexes for analytical scan performance.
-- ============================================================

-- ------------------------------------------------------------
-- fact_encounters  —  Grain: One row per patient encounter
-- Most central fact — captures clinical visit details
-- ------------------------------------------------------------
CREATE TABLE dbo.fact_encounters
(
    encounter_key           BIGINT          NOT NULL,   -- surrogate PK
    encounter_id            NVARCHAR(50)    NOT NULL,   -- natural key
    -- Foreign Keys (dimension surrogate keys)
    patient_key             INT             NOT NULL,
    provider_key            INT             NOT NULL,
    date_key                INT             NOT NULL,   -- encounter start date
    end_date_key            INT             NULL,       -- encounter end date
    payer_key               INT             NOT NULL,
    -- Degenerate Dimensions
    encounter_type          NVARCHAR(50)    NOT NULL,   -- inpatient / outpatient / emergency / wellness
    encounter_class         NVARCHAR(50)    NULL,
    -- Measures
    total_cost              DECIMAL(12,2)   NULL,
    payer_coverage          DECIMAL(12,2)   NULL,
    patient_cost            DECIMAL(12,2)   NULL,
    length_of_stay_days     DECIMAL(8,2)    NULL,       -- fractional days allowed
    num_conditions          SMALLINT        NULL DEFAULT 0,
    num_medications         SMALLINT        NULL DEFAULT 0,
    num_procedures          SMALLINT        NULL DEFAULT 0,
    -- Derived Flags
    readmission_flag        BIT             NOT NULL DEFAULT 0,  -- 1 if admitted within 30 days of prior discharge
    readmission_days        SMALLINT        NULL,                -- days since last discharge (if readmission)
    is_emergency            BIT             NOT NULL DEFAULT 0,
    is_inpatient            BIT             NOT NULL DEFAULT 0,
    -- Audit
    etl_load_date           DATETIME2       NOT NULL DEFAULT GETDATE(),
    source_system           NVARCHAR(50)    NOT NULL DEFAULT 'Synthea'
)
WITH
(
    DISTRIBUTION = HASH(patient_key),
    CLUSTERED COLUMNSTORE INDEX
);

-- ------------------------------------------------------------
-- fact_claims  —  Grain: One row per insurance claim
-- Financial layer — tracks claim lifecycle and payments
-- ------------------------------------------------------------
CREATE TABLE dbo.fact_claims
(
    claim_key               BIGINT          NOT NULL,
    claim_id                NVARCHAR(50)    NOT NULL,
    -- Foreign Keys
    patient_key             INT             NOT NULL,
    encounter_key           BIGINT          NOT NULL,
    payer_key               INT             NOT NULL,
    date_key                INT             NOT NULL,   -- claim submission date
    -- Measures
    amount_billed           DECIMAL(12,2)   NOT NULL,
    amount_paid             DECIMAL(12,2)   NULL DEFAULT 0,
    amount_denied           AS (amount_billed - ISNULL(amount_paid, 0)),  -- computed
    adjustment_amount       DECIMAL(12,2)   NULL DEFAULT 0,
    processing_days         SMALLINT        NULL,       -- submission to decision
    -- Degenerate Dimensions
    claim_status            NVARCHAR(30)    NOT NULL,   -- submitted/approved/denied/appealed/paid
    denial_reason           NVARCHAR(200)   NULL,
    denial_reason_code      NVARCHAR(20)    NULL,
    -- Flags
    is_denied               BIT             NOT NULL DEFAULT 0,
    is_appealed             BIT             NOT NULL DEFAULT 0,
    is_paid                 BIT             NOT NULL DEFAULT 0,
    -- Audit
    etl_load_date           DATETIME2       NOT NULL DEFAULT GETDATE(),
    source_system           NVARCHAR(50)    NOT NULL DEFAULT 'CustomGenerator'
)
WITH
(
    DISTRIBUTION = HASH(patient_key),
    CLUSTERED COLUMNSTORE INDEX
);

-- ------------------------------------------------------------
-- fact_vitals  —  Grain: One row per vital signs reading
-- High-volume streaming data — partitioned by load date
-- ------------------------------------------------------------
CREATE TABLE dbo.fact_vitals
(
    vital_key               BIGINT          NOT NULL,
    device_id               NVARCHAR(50)    NULL,
    -- Foreign Keys
    patient_key             INT             NOT NULL,
    date_key                INT             NOT NULL,
    time_key                INT             NOT NULL,
    -- Measures (all nullable — sensor may miss a reading)
    heart_rate              DECIMAL(6,2)    NULL,       -- bpm
    systolic_bp             DECIMAL(6,2)    NULL,       -- mmHg
    diastolic_bp            DECIMAL(6,2)    NULL,       -- mmHg
    temperature             DECIMAL(5,2)    NULL,       -- Celsius
    spo2                    DECIMAL(5,2)    NULL,       -- % oxygen saturation
    respiratory_rate        DECIMAL(5,2)    NULL,       -- breaths/min
    -- Derived anomaly flags (set by streaming pipeline)
    anomaly_flag            BIT             NOT NULL DEFAULT 0,
    anomaly_type            NVARCHAR(100)   NULL,       -- tachycardia / hypotension / fever / hypoxia
    anomaly_severity        NVARCHAR(20)    NULL,       -- mild / moderate / critical
    -- Windowed aggregation results (set by Spark Structured Streaming)
    window_avg_hr           DECIMAL(6,2)    NULL,       -- 5-min window average HR
    window_avg_spo2         DECIMAL(5,2)    NULL,
    hr_trend                NVARCHAR(10)    NULL,       -- increasing / stable / decreasing
    -- Timestamp
    reading_timestamp       DATETIME2       NOT NULL,
    -- Audit
    etl_load_date           DATETIME2       NOT NULL DEFAULT GETDATE(),
    source_system           NVARCHAR(50)    NOT NULL DEFAULT 'IoTSimulator'
)
WITH
(
    DISTRIBUTION = HASH(patient_key),
    CLUSTERED COLUMNSTORE INDEX,
    PARTITION (date_key RANGE RIGHT FOR VALUES
        (20230101, 20230401, 20230701, 20231001,
         20240101, 20240401, 20240701, 20241001,
         20250101, 20250401, 20250701, 20251001))
);

-- ============================================================
-- SECTION 4: PRIMARY KEY CONSTRAINTS
-- (Synapse Dedicated SQL Pool does NOT enforce PK constraints
--  but they document uniqueness intent and aid optimizer hints)
-- ============================================================

ALTER TABLE dbo.dim_patient    ADD CONSTRAINT PK_dim_patient    PRIMARY KEY NONCLUSTERED (patient_key)    NOT ENFORCED;
ALTER TABLE dbo.dim_provider   ADD CONSTRAINT PK_dim_provider   PRIMARY KEY NONCLUSTERED (provider_key)   NOT ENFORCED;
ALTER TABLE dbo.dim_date       ADD CONSTRAINT PK_dim_date       PRIMARY KEY NONCLUSTERED (date_key)       NOT ENFORCED;
ALTER TABLE dbo.dim_time       ADD CONSTRAINT PK_dim_time       PRIMARY KEY NONCLUSTERED (time_key)       NOT ENFORCED;
ALTER TABLE dbo.dim_diagnosis  ADD CONSTRAINT PK_dim_diagnosis  PRIMARY KEY NONCLUSTERED (diagnosis_key)  NOT ENFORCED;
ALTER TABLE dbo.dim_payer      ADD CONSTRAINT PK_dim_payer      PRIMARY KEY NONCLUSTERED (payer_key)      NOT ENFORCED;
ALTER TABLE dbo.fact_encounters ADD CONSTRAINT PK_fact_encounters PRIMARY KEY NONCLUSTERED (encounter_key) NOT ENFORCED;
ALTER TABLE dbo.fact_claims    ADD CONSTRAINT PK_fact_claims    PRIMARY KEY NONCLUSTERED (claim_key)      NOT ENFORCED;
ALTER TABLE dbo.fact_vitals    ADD CONSTRAINT PK_fact_vitals    PRIMARY KEY NONCLUSTERED (vital_key)      NOT ENFORCED;

-- ============================================================
-- SECTION 5: FOREIGN KEY CONSTRAINTS (NOT ENFORCED — Synapse)
-- Documented for lineage and optimizer statistics
-- ============================================================

ALTER TABLE dbo.fact_encounters ADD CONSTRAINT FK_fe_patient   FOREIGN KEY (patient_key)  REFERENCES dbo.dim_patient  (patient_key)  NOT ENFORCED;
ALTER TABLE dbo.fact_encounters ADD CONSTRAINT FK_fe_provider  FOREIGN KEY (provider_key) REFERENCES dbo.dim_provider (provider_key) NOT ENFORCED;
ALTER TABLE dbo.fact_encounters ADD CONSTRAINT FK_fe_date      FOREIGN KEY (date_key)     REFERENCES dbo.dim_date     (date_key)     NOT ENFORCED;
ALTER TABLE dbo.fact_encounters ADD CONSTRAINT FK_fe_payer     FOREIGN KEY (payer_key)    REFERENCES dbo.dim_payer    (payer_key)    NOT ENFORCED;

ALTER TABLE dbo.fact_claims    ADD CONSTRAINT FK_fc_patient    FOREIGN KEY (patient_key)   REFERENCES dbo.dim_patient  (patient_key)  NOT ENFORCED;
ALTER TABLE dbo.fact_claims    ADD CONSTRAINT FK_fc_encounter  FOREIGN KEY (encounter_key) REFERENCES dbo.fact_encounters (encounter_key) NOT ENFORCED;
ALTER TABLE dbo.fact_claims    ADD CONSTRAINT FK_fc_payer      FOREIGN KEY (payer_key)     REFERENCES dbo.dim_payer    (payer_key)    NOT ENFORCED;
ALTER TABLE dbo.fact_claims    ADD CONSTRAINT FK_fc_date       FOREIGN KEY (date_key)      REFERENCES dbo.dim_date     (date_key)     NOT ENFORCED;

ALTER TABLE dbo.fact_vitals    ADD CONSTRAINT FK_fv_patient    FOREIGN KEY (patient_key)  REFERENCES dbo.dim_patient  (patient_key)  NOT ENFORCED;
ALTER TABLE dbo.fact_vitals    ADD CONSTRAINT FK_fv_date       FOREIGN KEY (date_key)     REFERENCES dbo.dim_date     (date_key)     NOT ENFORCED;
ALTER TABLE dbo.fact_vitals    ADD CONSTRAINT FK_fv_time       FOREIGN KEY (time_key)     REFERENCES dbo.dim_time     (time_key)     NOT ENFORCED;

-- ============================================================
-- SECTION 6: STATISTICS (Critical for Synapse Query Optimizer)
-- ============================================================

-- Fact table join columns — most impactful stats
CREATE STATISTICS STAT_fe_patient_key   ON dbo.fact_encounters (patient_key);
CREATE STATISTICS STAT_fe_provider_key  ON dbo.fact_encounters (provider_key);
CREATE STATISTICS STAT_fe_date_key      ON dbo.fact_encounters (date_key);
CREATE STATISTICS STAT_fe_payer_key     ON dbo.fact_encounters (payer_key);
CREATE STATISTICS STAT_fe_enc_type      ON dbo.fact_encounters (encounter_type);
CREATE STATISTICS STAT_fe_readmission   ON dbo.fact_encounters (readmission_flag);

CREATE STATISTICS STAT_fc_patient_key   ON dbo.fact_claims (patient_key);
CREATE STATISTICS STAT_fc_payer_key     ON dbo.fact_claims (payer_key);
CREATE STATISTICS STAT_fc_status        ON dbo.fact_claims (claim_status);
CREATE STATISTICS STAT_fc_is_denied     ON dbo.fact_claims (is_denied);

CREATE STATISTICS STAT_fv_patient_key   ON dbo.fact_vitals (patient_key);
CREATE STATISTICS STAT_fv_date_key      ON dbo.fact_vitals (date_key);
CREATE STATISTICS STAT_fv_anomaly       ON dbo.fact_vitals (anomaly_flag);

-- Dimension filter columns
CREATE STATISTICS STAT_dp_patient_id    ON dbo.dim_patient  (patient_id);
CREATE STATISTICS STAT_dp_is_current    ON dbo.dim_patient  (is_current);
CREATE STATISTICS STAT_dp_insurance     ON dbo.dim_patient  (insurance_type);
CREATE STATISTICS STAT_dp_state         ON dbo.dim_patient  (state);

CREATE STATISTICS STAT_dprov_specialty  ON dbo.dim_provider (specialty);
CREATE STATISTICS STAT_dprov_is_current ON dbo.dim_provider (is_current);

CREATE STATISTICS STAT_dd_year          ON dbo.dim_date (year);
CREATE STATISTICS STAT_dd_month         ON dbo.dim_date (month);
CREATE STATISTICS STAT_dd_yearmonth     ON dbo.dim_date (year_month);

CREATE STATISTICS STAT_diag_icd10       ON dbo.dim_diagnosis (icd10_code);
CREATE STATISTICS STAT_diag_body_sys    ON dbo.dim_diagnosis (body_system);

CREATE STATISTICS STAT_payer_type       ON dbo.dim_payer (payer_type);

PRINT 'Star Schema DDL completed successfully.';
PRINT 'Tables created: dim_patient, dim_provider, dim_date, dim_time, dim_diagnosis, dim_payer';
PRINT 'Fact tables created: fact_encounters, fact_claims, fact_vitals';