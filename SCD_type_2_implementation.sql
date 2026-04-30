
-- PART A: SCD Type 2 — dim_patient
-- Tracked columns: insurance_type, city, state, marital_status
-- Strategy: MERGE incoming Silver data against current dim rows
-- ============================================================

-- Step 1: Stage incoming Silver patient data into a temp table
-- (In production this is a Synapse external table over Silver Delta)
CREATE TABLE #stage_patients
(
    patient_id          NVARCHAR(50),
    first_name          NVARCHAR(100),
    last_name           NVARCHAR(100),
    birth_date          DATE,
    gender              NVARCHAR(10),
    race                NVARCHAR(50),
    ethnicity           NVARCHAR(50),
    city                NVARCHAR(100),
    state               NVARCHAR(50),
    zip_code            NVARCHAR(20),
    insurance_type      NVARCHAR(50),
    marital_status      NVARCHAR(20),
    row_hash            NVARCHAR(64)   -- SHA-256 of (insurance_type + city + state + marital_status)
);

-- Step 2: Expire rows where SCD-tracked columns have changed
--         (Set valid_to = today - 1 day, is_current = 0)
UPDATE dbo.dim_patient
SET
    valid_to   = DATEADD(DAY, -1, CAST(GETDATE() AS DATE)),
    is_current = 0
WHERE is_current = 1
  AND patient_id IN
  (
      SELECT s.patient_id
      FROM   #stage_patients s
      JOIN   dbo.dim_patient  d
          ON d.patient_id = s.patient_id
         AND d.is_current  = 1
      WHERE  d.row_hash <> s.row_hash   -- Hash mismatch = a tracked column changed
  );

-- Step 3: Insert NEW current rows for changed patients + brand new patients
INSERT INTO dbo.dim_patient
(
    patient_key, patient_id, first_name, last_name,
    birth_date, gender, race, ethnicity,
    city, state, zip_code, insurance_type, marital_status,
    valid_from, valid_to, is_current, row_hash
)
SELECT
    -- Surrogate key: use ROW_NUMBER seeded from current max
    (SELECT ISNULL(MAX(patient_key), 0) FROM dbo.dim_patient) + ROW_NUMBER() OVER (ORDER BY s.patient_id),
    s.patient_id,
    s.first_name, s.last_name,
    s.birth_date, s.gender, s.race, s.ethnicity,
    s.city, s.state, s.zip_code, s.insurance_type, s.marital_status,
    CAST(GETDATE() AS DATE),    -- valid_from = today
    NULL,                       -- valid_to   = NULL (current row)
    1,                          -- is_current = 1
    s.row_hash
FROM   #stage_patients s
WHERE  NOT EXISTS
       (
           -- Exclude patients where nothing changed (hash matches current row)
           SELECT 1
           FROM   dbo.dim_patient d
           WHERE  d.patient_id = s.patient_id
             AND  d.is_current  = 1
             AND  d.row_hash    = s.row_hash
       );

DROP TABLE #stage_patients;

-- ============================================================
-- PART B: SCD Type 2 — dim_provider
-- Tracked columns: specialty, sub_specialty, organization
-- Same pattern as dim_patient
-- ============================================================

CREATE TABLE #stage_providers
(
    provider_id         NVARCHAR(50),
    provider_name       NVARCHAR(200),
    specialty           NVARCHAR(100),
    sub_specialty       NVARCHAR(100),
    organization        NVARCHAR(200),
    city                NVARCHAR(100),
    state               NVARCHAR(50),
    npi_number          NVARCHAR(20),
    row_hash            NVARCHAR(64)   -- SHA-256 of (specialty + sub_specialty + organization)
);

-- Expire changed provider rows
UPDATE dbo.dim_provider
SET
    valid_to   = DATEADD(DAY, -1, CAST(GETDATE() AS DATE)),
    is_current = 0
WHERE is_current = 1
  AND provider_id IN
  (
      SELECT s.provider_id
      FROM   #stage_providers s
      JOIN   dbo.dim_provider  d
          ON d.provider_id = s.provider_id
         AND d.is_current   = 1
      WHERE  d.row_hash <> s.row_hash
  );

-- Insert new current rows for providers
INSERT INTO dbo.dim_provider
(
    provider_key, provider_id, provider_name,
    specialty, sub_specialty, organization,
    city, state, npi_number,
    valid_from, valid_to, is_current, row_hash
)
SELECT
    (SELECT ISNULL(MAX(provider_key), 0) FROM dbo.dim_provider) + ROW_NUMBER() OVER (ORDER BY s.provider_id),
    s.provider_id, s.provider_name,
    s.specialty, s.sub_specialty, s.organization,
    s.city, s.state, s.npi_number,
    CAST(GETDATE() AS DATE),
    NULL,
    1,
    s.row_hash
FROM   #stage_providers s
WHERE  NOT EXISTS
       (
           SELECT 1
           FROM   dbo.dim_provider d
           WHERE  d.provider_id = s.provider_id
             AND  d.is_current   = 1
             AND  d.row_hash     = s.row_hash
       );

DROP TABLE #stage_providers;

-- ============================================================
-- PART C: Audit Query — Verify SCD2 History
-- Shows version count per patient/provider and date ranges
-- ============================================================

-- Patients with multiple versions (had changes)
SELECT
    patient_id,
    COUNT(*)            AS version_count,
    MIN(valid_from)     AS first_seen,
    MAX(valid_from)     AS latest_version_date,
    STRING_AGG(insurance_type, ' ? ')
        WITHIN GROUP (ORDER BY valid_from)  AS insurance_history
FROM   dbo.dim_patient
GROUP BY patient_id
HAVING COUNT(*) > 1
ORDER BY version_count DESC;

-- Providers with specialty changes
SELECT
    provider_id,
    provider_name,
    COUNT(*)            AS version_count,
    STRING_AGG(specialty, ' ? ')
        WITHIN GROUP (ORDER BY valid_from)  AS specialty_history
FROM   dbo.dim_provider
GROUP BY provider_id, provider_name
HAVING COUNT(*) > 1
ORDER BY version_count DESC;

-- Current snapshot — what coverage exists right now
SELECT
    'dim_patient'   AS dimension,
    COUNT(*)        AS current_rows,
    SUM(CASE WHEN is_current = 0 THEN 1 ELSE 0 END) AS historical_rows
FROM dbo.dim_patient
UNION ALL
SELECT
    'dim_provider',
    COUNT(*),
    SUM(CASE WHEN is_current = 0 THEN 1 ELSE 0 END)
FROM dbo.dim_provider;

PRINT 'SCD Type 2 MERGE completed for dim_patient and dim_provider.';