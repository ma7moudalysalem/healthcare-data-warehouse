/* Q4. Claim denial rate and dollar leakage by payer and month.
   Used by: revenue-cycle management.
   ----------------------------------------------------------------------- */
SELECT
    p.payer_name,
    dd.[year],
    dd.[month],
    COUNT(*)                                                   AS total_claims,
    SUM(CAST(fc.is_denied AS INT))                             AS denied_claims,
    CAST(100.0 * SUM(CAST(fc.is_denied AS INT)) / COUNT(*)
         AS DECIMAL(5,2))                                      AS denial_rate_pct,
    SUM(fc.billed_amount)                                      AS total_billed,
    SUM(CASE WHEN fc.is_denied = 1 THEN fc.billed_amount ELSE 0 END)
                                                                AS total_denied_billed,
    CAST(100.0 *
         SUM(CASE WHEN fc.is_denied = 1 THEN fc.billed_amount ELSE 0 END)
         / NULLIF(SUM(fc.billed_amount), 0)
         AS DECIMAL(5,2))                                      AS dollar_denial_pct
FROM dw.fact_claim     fc
JOIN dw.dim_payer      p  ON p.payer_sk = fc.payer_sk
JOIN dw.dim_date       dd ON dd.date_sk = fc.service_date_sk
WHERE dd.calendar_date >= DATEADD(MONTH, -12, CONVERT(DATE, SYSUTCDATETIME()))
GROUP BY p.payer_name, dd.[year], dd.[month]
ORDER BY dd.[year], dd.[month], denial_rate_pct DESC;
