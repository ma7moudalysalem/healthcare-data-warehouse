/* Q6. ED throughput: visits per day-of-week, with average length of stay.
   Helps staffing decisions: which days run hot, and how long do they stay?
   ----------------------------------------------------------------------- */
SELECT
    h.hospital_name,
    dd.day_name,
    dd.day_of_week,
    COUNT(*)                                              AS ed_visits,
    CAST(AVG(fe.length_of_stay_hours) AS DECIMAL(8,2))    AS avg_los_hours,
    CAST(MAX(fe.length_of_stay_hours) AS DECIMAL(8,2))    AS max_los_hours,
    SUM(CASE WHEN fe.is_readmission_30d = 1 THEN 1 ELSE 0 END)
                                                          AS ed_readmissions
FROM dw.fact_encounter fe
JOIN dw.dim_hospital   h  ON h.hospital_sk = fe.hospital_sk
JOIN dw.dim_date       dd ON dd.date_sk    = fe.start_date_sk
WHERE fe.encounter_class = 'emergency'
  AND dd.calendar_date >= DATEADD(MONTH, -3, CONVERT(DATE, SYSUTCDATETIME()))
GROUP BY h.hospital_name, dd.day_name, dd.day_of_week
ORDER BY h.hospital_name, dd.day_of_week;
