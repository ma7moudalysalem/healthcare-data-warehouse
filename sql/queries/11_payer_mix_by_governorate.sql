/* Q11. Payer mix by governorate (last 6 months).
   Helps marketing target specific carriers for partnerships.
   ----------------------------------------------------------------------- */
WITH base AS (
    SELECT
        ISNULL(p.governorate, N'Unknown')          AS governorate,
        py.payer_name,
        fc.billed_amount,
        fc.paid_amount
    FROM dw.fact_claim    fc
    JOIN dw.dim_payer     py ON py.payer_sk    = fc.payer_sk
    LEFT JOIN dw.dim_patient p ON p.patient_sk = fc.patient_sk AND p.is_current = 1
    JOIN dw.dim_date      dd ON dd.date_sk    = fc.service_date_sk
    WHERE dd.calendar_date >= DATEADD(MONTH, -6, CONVERT(DATE, SYSUTCDATETIME()))
)
SELECT
    governorate,
    payer_name,
    COUNT(*)                                                    AS claim_count,
    CAST(SUM(billed_amount) AS DECIMAL(14,2))                   AS total_billed,
    CAST(SUM(paid_amount) AS DECIMAL(14,2))                     AS total_paid,
    CAST(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY governorate)
         AS DECIMAL(5,2))                                       AS share_of_governorate_pct
FROM base
GROUP BY governorate, payer_name
ORDER BY governorate, share_of_governorate_pct DESC;
