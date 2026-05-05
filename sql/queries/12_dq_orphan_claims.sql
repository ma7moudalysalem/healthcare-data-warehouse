/* Q12. Data-quality monitor: orphan claims.
   Surfaces claims whose encounter_id didn't match any encounter in the
   warehouse. Run daily; >2% sustained should page the data team.
   ----------------------------------------------------------------------- */
SELECT
    dd.calendar_date                            AS service_date,
    COUNT(*)                                    AS total_claims,
    SUM(CASE WHEN fc.encounter_sk IS NULL THEN 1 ELSE 0 END)
                                                AS orphan_claims,
    CAST(100.0 *
         SUM(CASE WHEN fc.encounter_sk IS NULL THEN 1 ELSE 0 END)
         / COUNT(*) AS DECIMAL(5,2))            AS orphan_pct
FROM dw.fact_claim fc
JOIN dw.dim_date   dd ON dd.date_sk = fc.service_date_sk
WHERE dd.calendar_date >= DATEADD(DAY, -30, CONVERT(DATE, SYSUTCDATETIME()))
GROUP BY dd.calendar_date
ORDER BY dd.calendar_date;
