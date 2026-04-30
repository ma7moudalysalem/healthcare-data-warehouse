--- This schema was originally designed for Azure Synapse (MPP architecture) and
--- has been adapted to SQL Server while preserving logical design and relationships.



--- dim_patient ( SCD 2)


CREATE TABLE dbo.dim_patient
(
    patient_key     INT IDENTITY(1,1) PRIMARY KEY,
    patient_id      NVARCHAR(50) NOT NULL,
    first_name      NVARCHAR(100),
    last_name       NVARCHAR(100),
    birth_date      DATE,
    gender          NVARCHAR(10),
    race            NVARCHAR(50),
    ethnicity       NVARCHAR(50),
    city            NVARCHAR(100),
    state           NVARCHAR(50),
    zip_code        NVARCHAR(20),
    insurance_type  NVARCHAR(50),
    marital_status  NVARCHAR(50),

    valid_from      DATETIME NOT NULL,
    valid_to        DATETIME NULL,
    is_current      BIT NOT NULL,

    row_hash        NVARCHAR(64)
);



---------------------------------------

-- dim_provider

CREATE TABLE dbo.dim_provider
(
    provider_key    INT IDENTITY(1,1) PRIMARY KEY,
    provider_id     NVARCHAR(50) NOT NULL,
    provider_name   NVARCHAR(200),
    specialty       NVARCHAR(100),
    city            NVARCHAR(100),
    state           NVARCHAR(50),

    valid_from      DATETIME NOT NULL,
    valid_to        DATETIME NULL,
    is_current      BIT NOT NULL,

    row_hash        NVARCHAR(64)
);


-------------------------------------

-- dim payer

CREATE TABLE dbo.dim_payer
(
    payer_key      INT IDENTITY(1,1) PRIMARY KEY,
    payer_id       NVARCHAR(50),
    payer_name     NVARCHAR(200),
    payer_type     NVARCHAR(50)
);


-----------------------------------

-- dim_date

CREATE TABLE dbo.dim_date
(
    date_key        INT PRIMARY KEY,
    full_date       DATE,
    day             INT,
    month           INT,
    year            INT,
    quarter         INT,
    day_name        NVARCHAR(20),
    month_name      NVARCHAR(20)
);


------------------------------

-- dim_time

CREATE TABLE dbo.dim_time
(
    time_key   INT PRIMARY KEY,
    hour       INT,
    minute     INT,
    am_pm      NVARCHAR(2),
    shift      NVARCHAR(20)
);




--------------------------------

-------------------------- Fact Tables



--- fact_encounters


CREATE TABLE dbo.fact_encounters
(
    encounter_key       BIGINT IDENTITY(1,1) PRIMARY KEY,
    encounter_id        NVARCHAR(50),

    patient_key         INT NOT NULL,
    provider_key        INT NOT NULL,
    date_key            INT NOT NULL,
    end_date_key        INT NULL,
    payer_key           INT NOT NULL,

    encounter_type      NVARCHAR(50),
    encounter_class     NVARCHAR(50),

    total_cost          DECIMAL(12,2),
    payer_coverage      DECIMAL(12,2),
    patient_cost        DECIMAL(12,2),

    length_of_stay_days DECIMAL(8,2),
    readmission_flag    BIT,

    etl_load_date       DATETIME,

    CONSTRAINT FK_fe_patient 
        FOREIGN KEY (patient_key) REFERENCES dbo.dim_patient(patient_key),

    CONSTRAINT FK_fe_provider 
        FOREIGN KEY (provider_key) REFERENCES dbo.dim_provider(provider_key),

    CONSTRAINT FK_fe_date 
        FOREIGN KEY (date_key) REFERENCES dbo.dim_date(date_key),

    CONSTRAINT FK_fe_payer 
        FOREIGN KEY (payer_key) REFERENCES dbo.dim_payer(payer_key)
);




---------------------------------------------

---- Fact_Claims



CREATE TABLE dbo.fact_claims
(
    claim_key       BIGINT IDENTITY(1,1) PRIMARY KEY,
    claim_id        NVARCHAR(50),

    patient_key     INT,
    encounter_key   BIGINT,
    payer_key       INT,
    date_key        INT,

    amount_billed   DECIMAL(12,2),
    amount_paid     DECIMAL(12,2),

    claim_status    NVARCHAR(50),

    CONSTRAINT FK_fc_patient 
        FOREIGN KEY (patient_key) REFERENCES dbo.dim_patient(patient_key),

    CONSTRAINT FK_fc_encounter 
        FOREIGN KEY (encounter_key) REFERENCES dbo.fact_encounters(encounter_key),

    CONSTRAINT FK_fc_payer 
        FOREIGN KEY (payer_key) REFERENCES dbo.dim_payer(payer_key),

    CONSTRAINT FK_fc_date 
        FOREIGN KEY (date_key) REFERENCES dbo.dim_date(date_key)
);




---------------------------------------

--- Fact_vitals


CREATE TABLE dbo.fact_vitals
(
    vital_key           BIGINT IDENTITY(1,1) PRIMARY KEY,

    patient_key         INT,
    date_key            INT,
    time_key            INT,

    heart_rate          DECIMAL(6,2),
    temperature         DECIMAL(5,2),

    reading_timestamp   DATETIME,

    CONSTRAINT FK_fv_patient 
        FOREIGN KEY (patient_key) REFERENCES dbo.dim_patient(patient_key),

    CONSTRAINT FK_fv_date 
        FOREIGN KEY (date_key) REFERENCES dbo.dim_date(date_key),

    CONSTRAINT FK_fv_time 
        FOREIGN KEY (time_key) REFERENCES dbo.dim_time(time_key)
);