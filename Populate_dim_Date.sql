
-- POPULATE dim_date 
-- ============================================================

WITH date_range AS
(
    SELECT CAST('2010-01-01' AS DATE) AS d
    UNION ALL
    SELECT DATEADD(DAY, 1, d)
    FROM   date_range
    WHERE  d < '2035-12-31'
)
INSERT INTO dbo.dim_date
(
    date_key, full_date, year, quarter, quarter_name,
    month, month_name, month_short, week_of_year,
    day_of_month, day_of_week, day_name,
    is_weekend, is_holiday, fiscal_year,
    fiscal_quarter, fiscal_month, days_in_month,
    is_last_day_of_month, iso_week, year_month
)
SELECT
    CAST(FORMAT(d, 'yyyyMMdd') AS INT)              AS date_key,
    d                                               AS full_date,
    YEAR(d)                                         AS year,
    DATEPART(QUARTER, d)                            AS quarter,
    'Q' + CAST(DATEPART(QUARTER, d) AS NVARCHAR)    AS quarter_name,
    MONTH(d)                                        AS month,
    DATENAME(MONTH, d)                              AS month_name,
    LEFT(DATENAME(MONTH, d), 3)                     AS month_short,
    DATEPART(WEEK, d)                               AS week_of_year,
    DAY(d)                                          AS day_of_month,
    DATEPART(WEEKDAY, d)                            AS day_of_week,   -- 1=Sun, 7=Sat (US default)
    DATENAME(WEEKDAY, d)                            AS day_name,
    CASE WHEN DATEPART(WEEKDAY, d) IN (1,7) THEN 1 ELSE 0 END  AS is_weekend,
    0                                               AS is_holiday,    -- update via separate holiday script
    -- Fiscal year starts July 1
    CASE WHEN MONTH(d) >= 7 THEN YEAR(d) + 1 ELSE YEAR(d) END  AS fiscal_year,
    CASE
        WHEN MONTH(d) IN (7,8,9)   THEN 1
        WHEN MONTH(d) IN (10,11,12) THEN 2
        WHEN MONTH(d) IN (1,2,3)   THEN 3
        ELSE 4
    END                                             AS fiscal_quarter,
    CASE
        WHEN MONTH(d) >= 7 THEN MONTH(d) - 6
        ELSE MONTH(d) + 6
    END                                             AS fiscal_month,
    DAY(EOMONTH(d))                                 AS days_in_month,
    CASE WHEN d = EOMONTH(d) THEN 1 ELSE 0 END      AS is_last_day_of_month,
    DATEPART(ISO_WEEK, d)                           AS iso_week,
    FORMAT(d, 'yyyy-MM')                            AS year_month
FROM   date_range
OPTION (MAXRECURSION 10000);

-- ============================================================
-- POPULATE dim_time  (1440 rows — every minute of the day)
-- ============================================================

WITH hours AS (SELECT 0 AS h UNION ALL SELECT h+1 FROM hours WHERE h < 23),
     minutes AS (SELECT 0 AS m UNION ALL SELECT m+1 FROM minutes WHERE m < 59)
INSERT INTO dbo.dim_time (time_key, hour, minute, hour_minute, am_pm, shift, shift_period, is_business_hour)
SELECT
    h.h * 100 + m.m                                             AS time_key,
    h.h                                                         AS hour,
    m.m                                                         AS minute,
    RIGHT('0' + CAST(h.h AS NVARCHAR), 2) + ':' +
    RIGHT('0' + CAST(m.m AS NVARCHAR), 2)                       AS hour_minute,
    CASE WHEN h.h < 12 THEN 'AM' ELSE 'PM' END                  AS am_pm,
    CASE
        WHEN h.h >= 6  AND h.h < 14 THEN 'Morning'
        WHEN h.h >= 14 AND h.h < 22 THEN 'Afternoon'
        ELSE 'Night'
    END                                                         AS shift,
    CASE
        WHEN h.h >= 6  AND h.h < 10 THEN 'Early Morning'
        WHEN h.h >= 10 AND h.h < 14 THEN 'Late Morning'
        WHEN h.h >= 14 AND h.h < 18 THEN 'Early Afternoon'
        WHEN h.h >= 18 AND h.h < 22 THEN 'Late Afternoon'
        WHEN h.h >= 22 OR  h.h < 2  THEN 'Early Night'
        ELSE 'Late Night'
    END                                                         AS shift_period,
    CASE WHEN h.h >= 8 AND h.h < 17 THEN 1 ELSE 0 END          AS is_business_hour
FROM   hours h CROSS JOIN minutes m
ORDER BY h.h, m.m
OPTION (MAXRECURSION 1000);

PRINT 'dim_date populated: 2010-01-01 to 2035-12-31';
PRINT 'dim_time populated: 1440 rows (every minute of the day)';