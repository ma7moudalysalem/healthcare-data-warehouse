/* Q2. 30-day inpatient readmission rate by hospital and quarter.
   Used by: quality-of-care steering committee, regulatory reporting.
   Note: is_readmission_30d is computed in the Silver layer using LAG over
   the patient's encounter history, so this query is just an aggregate.
   ----------------------------------------------------------------------- */
SELECT
    h.hospital_name,
    dd.[year],
    dd.[quarter],
    SUM(CASE WHEN fe.is_inpatient = 1 THEN 1 ELSE 0 END)                      AS inpatient_discharges,
    SUM(CASE WHEN fe.is_inpatient = 1 AND fe.is_readmission_30d = 1 THEN 1
             ELSE 0 END)                                                       AS readmissions_30d,
    CAST(
        100.0 * SUM(CASE WHEN fe.is_inpatient = 1 AND fe.is_readmission_30d = 1 THEN 1 ELSE 0 END)
              / NULLIF(SUM(CASE WHEN fe.is_inpatient = 1 THEN 1 ELSE 0 END), 0)
        AS DECIMAL(5,2)
    )                                                                          AS readmission_rate_pct
FROM dw.fact_encounter fe
JOIN dw.dim_hospital   h  ON h.hospital_sk = fe.hospital_sk
JOIN dw.dim_date       dd ON dd.date_sk    = fe.start_date_sk
WHERE dd.[year] >= YEAR(SYSUTCDATETIME()) - 2
GROUP BY h.hospital_name, dd.[year], dd.[quarter]
ORDER BY dd.[year], dd.[quarter], h.hospital_name;
