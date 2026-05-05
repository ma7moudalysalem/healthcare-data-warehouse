/* =========================================================================
   sp_refresh_kpi_daily.sql
   Refreshes daily KPI aggregates used by the Power BI / Streamlit dashboards.

   The DAX side could compute these on the fly, but for a 5-hospital network
   over multiple years that's ~3M rows in the encounter fact and the
   refresh time on Power BI Service is unpleasant. Pre-aggregating to one
   row per (date, hospital, encounter_class) drops the dashboard fact set
   to ~50K rows.

   The procedure is idempotent: it deletes the target date range first,
   then re-inserts. Pass the window via @from_date / @to_date; defaults
   to the trailing 35 days.
   ========================================================================= */

USE healthcare_dw;
GO

IF OBJECT_ID(N'dw.kpi_daily_hospital', N'U') IS NULL
CREATE TABLE dw.kpi_daily_hospital
(
    date_sk                 INT             NOT NULL,
    hospital_sk             BIGINT          NOT NULL,
    encounter_class         VARCHAR(30)     NOT NULL,
    encounter_count         INT             NOT NULL,
    inpatient_count         INT             NOT NULL,
    emergency_count         INT             NOT NULL,
    readmission_30d_count   INT             NOT NULL,
    avg_length_of_stay      DECIMAL(8,2)    NULL,
    total_revenue_usd       DECIMAL(14,2)   NULL,
    total_payer_coverage_usd DECIMAL(14,2)  NULL,
    refreshed_at            DATETIME2(0)    NOT NULL
)
WITH (DISTRIBUTION = HASH(hospital_sk), CLUSTERED COLUMNSTORE INDEX);
GO

CREATE OR ALTER PROCEDURE dw.sp_refresh_kpi_daily
    @from_date DATE = NULL,
    @to_date   DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @to_date IS NULL   SET @to_date   = CONVERT(DATE, SYSUTCDATETIME());
    IF @from_date IS NULL SET @from_date = DATEADD(DAY, -35, @to_date);

    DECLARE @from_sk INT = CONVERT(INT, FORMAT(@from_date, 'yyyyMMdd'));
    DECLARE @to_sk   INT = CONVERT(INT, FORMAT(@to_date,   'yyyyMMdd'));

    /* clear the window so re-runs are idempotent ----------------------- */
    DELETE FROM dw.kpi_daily_hospital
    WHERE date_sk BETWEEN @from_sk AND @to_sk;

    INSERT INTO dw.kpi_daily_hospital
        (date_sk, hospital_sk, encounter_class,
         encounter_count, inpatient_count, emergency_count, readmission_30d_count,
         avg_length_of_stay, total_revenue_usd, total_payer_coverage_usd,
         refreshed_at)
    SELECT
        fe.start_date_sk,
        fe.hospital_sk,
        fe.encounter_class,
        COUNT_BIG(*),
        SUM(CASE WHEN fe.is_inpatient = 1 THEN 1 ELSE 0 END),
        SUM(CASE WHEN fe.is_emergency = 1 THEN 1 ELSE 0 END),
        SUM(CASE WHEN fe.is_readmission_30d = 1 THEN 1 ELSE 0 END),
        AVG(CONVERT(DECIMAL(10,2), fe.length_of_stay_hours)),
        SUM(fe.total_cost_usd),
        SUM(fe.payer_coverage_usd),
        SYSUTCDATETIME()
    FROM dw.fact_encounter fe
    WHERE fe.start_date_sk BETWEEN @from_sk AND @to_sk
    GROUP BY fe.start_date_sk, fe.hospital_sk, fe.encounter_class;

    DECLARE @rows INT = @@ROWCOUNT;
    INSERT INTO dw.load_audit (layer, object_name, rows_written, started_at, finished_at, status)
    VALUES ('gold', 'kpi_daily_hospital', @rows, SYSUTCDATETIME(), SYSUTCDATETIME(), 'success');

    PRINT CONCAT('kpi_daily_hospital refreshed: ', @rows, ' rows for ', @from_date, ' .. ', @to_date);
END;
GO
