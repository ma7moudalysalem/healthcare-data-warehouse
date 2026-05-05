/* Q5. Revenue per encounter, broken out by encounter class.
   Inputs are joined on encounter_sk; orphan claims are excluded since they
   can't be attributed to a specific encounter.
   ----------------------------------------------------------------------- */
SELECT
    h.hospital_name,
    fe.encounter_class,
    COUNT(DISTINCT fe.encounter_sk)                       AS encounters,
    CAST(AVG(fe.total_cost_usd) AS DECIMAL(12,2))         AS avg_encounter_cost,
    CAST(AVG(fc.billed_amount) AS DECIMAL(12,2))          AS avg_billed,
    CAST(AVG(fc.paid_amount) AS DECIMAL(12,2))            AS avg_paid,
    CAST(SUM(fc.paid_amount) AS DECIMAL(14,2))            AS total_paid,
    CAST(100.0 * AVG(fc.paid_amount) / NULLIF(AVG(fc.billed_amount), 0)
         AS DECIMAL(5,2))                                 AS collection_rate_pct
FROM dw.fact_encounter fe
JOIN dw.fact_claim     fc ON fc.encounter_sk = fe.encounter_sk
JOIN dw.dim_hospital   h  ON h.hospital_sk   = fe.hospital_sk
JOIN dw.dim_date       dd ON dd.date_sk      = fe.start_date_sk
WHERE dd.[year] = YEAR(SYSUTCDATETIME())
GROUP BY h.hospital_name, fe.encounter_class
ORDER BY h.hospital_name, total_paid DESC;
