/* =========================================================================
   12_warehouse_sequences_staging.sql
   Sequences for surrogate keys and staging tables for SCD2 inputs.

   On Synapse dedicated SQL pool, IDENTITY isn't supported on round-robin or
   replicated tables in the same pattern as on SQL Server, so we use named
   sequences with NEXT VALUE FOR. Each dimension has its own sequence.
   ========================================================================= */

USE healthcare_dw;
GO

IF NOT EXISTS (SELECT 1 FROM sys.sequences WHERE name = N'patient_sk_seq')
    EXEC(N'CREATE SEQUENCE dw.patient_sk_seq AS BIGINT START WITH 1 INCREMENT BY 1 CACHE 1000');
IF NOT EXISTS (SELECT 1 FROM sys.sequences WHERE name = N'provider_sk_seq')
    EXEC(N'CREATE SEQUENCE dw.provider_sk_seq AS BIGINT START WITH 1 INCREMENT BY 1 CACHE 1000');
IF NOT EXISTS (SELECT 1 FROM sys.sequences WHERE name = N'hospital_sk_seq')
    EXEC(N'CREATE SEQUENCE dw.hospital_sk_seq AS BIGINT START WITH 1 INCREMENT BY 1 CACHE 100');
IF NOT EXISTS (SELECT 1 FROM sys.sequences WHERE name = N'payer_sk_seq')
    EXEC(N'CREATE SEQUENCE dw.payer_sk_seq AS BIGINT START WITH 1 INCREMENT BY 1 CACHE 100');
IF NOT EXISTS (SELECT 1 FROM sys.sequences WHERE name = N'diagnosis_sk_seq')
    EXEC(N'CREATE SEQUENCE dw.diagnosis_sk_seq AS BIGINT START WITH 1 INCREMENT BY 1 CACHE 1000');
IF NOT EXISTS (SELECT 1 FROM sys.sequences WHERE name = N'procedure_sk_seq')
    EXEC(N'CREATE SEQUENCE dw.procedure_sk_seq AS BIGINT START WITH 1 INCREMENT BY 1 CACHE 1000');
IF NOT EXISTS (SELECT 1 FROM sys.sequences WHERE name = N'drug_sk_seq')
    EXEC(N'CREATE SEQUENCE dw.drug_sk_seq AS BIGINT START WITH 1 INCREMENT BY 1 CACHE 1000');
IF NOT EXISTS (SELECT 1 FROM sys.sequences WHERE name = N'encounter_sk_seq')
    EXEC(N'CREATE SEQUENCE dw.encounter_sk_seq AS BIGINT START WITH 1 INCREMENT BY 1 CACHE 10000');
IF NOT EXISTS (SELECT 1 FROM sys.sequences WHERE name = N'claim_sk_seq')
    EXEC(N'CREATE SEQUENCE dw.claim_sk_seq AS BIGINT START WITH 1 INCREMENT BY 1 CACHE 10000');
IF NOT EXISTS (SELECT 1 FROM sys.sequences WHERE name = N'prescription_sk_seq')
    EXEC(N'CREATE SEQUENCE dw.prescription_sk_seq AS BIGINT START WITH 1 INCREMENT BY 1 CACHE 10000');
IF NOT EXISTS (SELECT 1 FROM sys.sequences WHERE name = N'vital_sk_seq')
    EXEC(N'CREATE SEQUENCE dw.vital_sk_seq AS BIGINT START WITH 1 INCREMENT BY 1 CACHE 100000');
GO

/* ---------- Staging tables (truncate-and-load) ------------------------ */
IF OBJECT_ID(N'stg.dim_patient_incoming', N'U') IS NULL
CREATE TABLE stg.dim_patient_incoming
(
    patient_bk      UNIQUEIDENTIFIER NOT NULL,
    mrn             VARCHAR(20)  NULL,
    first_name      NVARCHAR(80) NULL,
    last_name       NVARCHAR(80) NULL,
    date_of_birth   DATE         NULL,
    age_band        VARCHAR(20)  NULL,
    gender          CHAR(1)      NULL,
    marital_status  VARCHAR(20)  NULL,
    race            NVARCHAR(60) NULL,
    ethnicity       NVARCHAR(60) NULL,
    governorate     NVARCHAR(80) NULL,
    city            NVARCHAR(80) NULL,
    is_deceased     BIT          NOT NULL
)
WITH (DISTRIBUTION = HASH(patient_bk), HEAP);
GO

IF OBJECT_ID(N'stg.dim_provider_incoming', N'U') IS NULL
CREATE TABLE stg.dim_provider_incoming
(
    provider_bk         VARCHAR(15)  NOT NULL,
    full_name           NVARCHAR(160) NULL,
    credential          VARCHAR(20)  NULL,
    specialty           NVARCHAR(80) NULL,
    primary_facility_sk BIGINT       NULL,
    license_expiry      DATE         NULL,
    hire_date           DATE         NULL,
    is_active           BIT          NOT NULL
)
WITH (DISTRIBUTION = ROUND_ROBIN, HEAP);
GO

PRINT 'Sequences and staging tables created.';
GO
