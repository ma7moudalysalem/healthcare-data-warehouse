/* Q8. Provider productivity: encounters and revenue per active provider.
   Filters to the current year and active providers only.
   ----------------------------------------------------------------------- */
SELECT
    pr.full_name                                  AS provider_name,
    pr.specialty,
    h.hospital_name                               AS primary_facility,
    COUNT(DISTINCT fe.encounter_sk)               AS encounters_ytd,
    COUNT(DISTINCT fe.patient_sk)                 AS unique_patients_ytd,
    CAST(AVG(fe.total_cost_usd) AS DECIMAL(12,2)) AS avg_encounter_revenue,
    CAST(SUM(fe.total_cost_usd) AS DECIMAL(14,2)) AS total_revenue_ytd
FROM dw.fact_encounter   fe
JOIN dw.dim_provider     pr ON pr.provider_sk = fe.provider_sk AND pr.is_current = 1 AND pr.is_active = 1
LEFT JOIN dw.dim_hospital h ON h.hospital_sk  = pr.primary_facility_sk
JOIN dw.dim_date         dd ON dd.date_sk     = fe.start_date_sk
WHERE dd.[year] = YEAR(SYSUTCDATETIME())
GROUP BY pr.full_name, pr.specialty, h.hospital_name
HAVING COUNT(DISTINCT fe.encounter_sk) >= 50      -- exclude very low volume
ORDER BY total_revenue_ytd DESC
OFFSET 0 ROWS FETCH NEXT 50 ROWS ONLY;
