/* Q9. Top 20 drugs by total spend, current year.
   Used by: pharmacy formulary committee.
   ----------------------------------------------------------------------- */
SELECT TOP (20)
    d.rxnorm_code,
    d.description                                          AS drug,
    COUNT(*)                                               AS prescription_count,
    SUM(fp.dispenses)                                      AS total_dispenses,
    CAST(SUM(fp.total_cost_usd) AS DECIMAL(14,2))          AS total_spend,
    CAST(AVG(fp.total_cost_usd) AS DECIMAL(12,2))          AS avg_cost_per_rx
FROM dw.fact_prescription fp
JOIN dw.dim_drug          d  ON d.drug_sk    = fp.drug_sk
JOIN dw.dim_date          dd ON dd.date_sk   = fp.start_date_sk
WHERE dd.[year] = YEAR(SYSUTCDATETIME())
  AND fp.total_cost_usd IS NOT NULL
GROUP BY d.rxnorm_code, d.description
ORDER BY total_spend DESC;
