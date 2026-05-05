/* =========================================================================
   sp_merge_dim_provider_scd2.sql
   Type-2 merge for dw.dim_provider.
   Mirrors sp_merge_dim_patient_scd2 - the staging table is
   stg.dim_provider_incoming.
   ========================================================================= */

USE healthcare_dw;
GO

CREATE OR ALTER PROCEDURE dw.sp_merge_dim_provider_scd2
    @load_ts DATETIME2(0) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @load_ts IS NULL SET @load_ts = SYSUTCDATETIME();

    IF OBJECT_ID(N'tempdb..#incoming') IS NOT NULL DROP TABLE #incoming;
    SELECT
        s.*,
        CONVERT(CHAR(64), HASHBYTES('SHA2_256',
            CONCAT(
                ISNULL(s.full_name, N''), '|',
                ISNULL(s.credential, ''), '|',
                ISNULL(s.specialty, N''), '|',
                ISNULL(CONVERT(VARCHAR(20), s.primary_facility_sk), ''), '|',
                ISNULL(CONVERT(VARCHAR(10), s.license_expiry, 23), ''), '|',
                ISNULL(CONVERT(VARCHAR(10), s.hire_date, 23), ''), '|',
                CONVERT(CHAR(1), s.is_active)
            )
        ), 2) AS new_hash
    INTO #incoming
    FROM stg.dim_provider_incoming s;

    UPDATE tgt
       SET effective_to = @load_ts, is_current = 0
    FROM dw.dim_provider tgt
    JOIN #incoming inc
      ON inc.provider_bk = tgt.provider_bk
     AND tgt.is_current = 1
    WHERE inc.new_hash <> tgt.record_hash;

    INSERT INTO dw.dim_provider
        (provider_sk, provider_bk, full_name, credential, specialty,
         primary_facility_sk, license_expiry, hire_date, is_active,
         effective_from, effective_to, is_current, record_hash)
    SELECT
        NEXT VALUE FOR dw.provider_sk_seq,
        inc.provider_bk, inc.full_name, inc.credential, inc.specialty,
        inc.primary_facility_sk, inc.license_expiry, inc.hire_date, inc.is_active,
        @load_ts, NULL, 1, inc.new_hash
    FROM #incoming inc
    LEFT JOIN dw.dim_provider cur
           ON cur.provider_bk = inc.provider_bk AND cur.is_current = 1
    WHERE cur.provider_bk IS NULL OR cur.record_hash <> inc.new_hash;

    DECLARE @inserted INT = @@ROWCOUNT;
    INSERT INTO dw.load_audit (layer, object_name, rows_written, started_at, finished_at, status)
    VALUES ('gold', 'dim_provider', @inserted, @load_ts, SYSUTCDATETIME(), 'success');

    PRINT CONCAT('dim_provider SCD2 merge: ', @inserted, ' new versions.');
END;
GO
