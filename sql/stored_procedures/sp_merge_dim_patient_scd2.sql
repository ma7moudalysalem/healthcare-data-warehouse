/* =========================================================================
   sp_merge_dim_patient_scd2.sql
   Type-2 merge for dw.dim_patient.

   Input: stg.dim_patient_incoming (one row per patient, current attributes).
   Behaviour:
     * brand new patient_bk          -> insert with effective_from = load_ts,
                                        effective_to = NULL, is_current = 1
     * existing patient_bk, hash same -> no-op
     * existing patient_bk, hash diff -> close current row (effective_to,
                                        is_current = 0) and insert new row
     * patients absent from staging  -> left untouched (we don't soft-delete
                                        on partial loads)

   The hash compares the full SCD2 attribute set so a change to e.g.
   marital_status correctly opens a new version.
   ========================================================================= */

USE healthcare_dw;
GO

CREATE OR ALTER PROCEDURE dw.sp_merge_dim_patient_scd2
    @load_ts DATETIME2(0) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @load_ts IS NULL SET @load_ts = SYSUTCDATETIME();

    /* 1. compute incoming hash (over the SCD2 attributes only) ---------- */
    IF OBJECT_ID(N'tempdb..#incoming') IS NOT NULL DROP TABLE #incoming;
    SELECT
        s.*,
        CONVERT(CHAR(64), HASHBYTES('SHA2_256',
            CONCAT(
                ISNULL(s.first_name, N''), '|',
                ISNULL(s.last_name, N''), '|',
                ISNULL(CONVERT(VARCHAR(10), s.date_of_birth, 23), ''), '|',
                ISNULL(s.age_band, ''), '|',
                ISNULL(s.gender, ''), '|',
                ISNULL(s.marital_status, ''), '|',
                ISNULL(s.race, N''), '|',
                ISNULL(s.ethnicity, N''), '|',
                ISNULL(s.governorate, N''), '|',
                ISNULL(s.city, N''), '|',
                CONVERT(CHAR(1), s.is_deceased)
            )
        ), 2) AS new_hash
    INTO #incoming
    FROM stg.dim_patient_incoming s;

    /* 2. close versions whose attributes have changed ------------------- */
    UPDATE tgt
       SET effective_to = @load_ts,
           is_current   = 0
    FROM dw.dim_patient tgt
    JOIN #incoming inc
      ON inc.patient_bk = tgt.patient_bk
     AND tgt.is_current = 1
    WHERE inc.new_hash <> tgt.record_hash;

    /* 3. insert brand new rows AND new versions of changed rows --------- */
    INSERT INTO dw.dim_patient
        (patient_sk, patient_bk, mrn, first_name, last_name, full_name,
         date_of_birth, age_band, gender, marital_status, race, ethnicity,
         governorate, city, is_deceased,
         effective_from, effective_to, is_current, record_hash)
    SELECT
        NEXT VALUE FOR dw.patient_sk_seq,
        inc.patient_bk, inc.mrn, inc.first_name, inc.last_name,
        CONCAT(inc.first_name, N' ', inc.last_name),
        inc.date_of_birth, inc.age_band, inc.gender, inc.marital_status,
        inc.race, inc.ethnicity, inc.governorate, inc.city, inc.is_deceased,
        @load_ts, NULL, 1, inc.new_hash
    FROM #incoming inc
    LEFT JOIN dw.dim_patient cur
           ON cur.patient_bk = inc.patient_bk AND cur.is_current = 1
    WHERE cur.patient_bk IS NULL                  -- brand new
       OR cur.record_hash <> inc.new_hash;        -- changed

    /* 4. report --------------------------------------------------------- */
    DECLARE @inserted INT = @@ROWCOUNT;
    INSERT INTO dw.load_audit (layer, object_name, rows_written, started_at, finished_at, status)
    VALUES ('gold', 'dim_patient', @inserted, @load_ts, SYSUTCDATETIME(), 'success');

    PRINT CONCAT('dim_patient SCD2 merge: ', @inserted, ' new versions.');
END;
GO
