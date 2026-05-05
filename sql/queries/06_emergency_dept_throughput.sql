/* Q6. ED throughput by hour of day.
   Helps staffing decisions: when is the surge?
   ----------------------------------------------------------------------- */
SELECT
    h.hospital_name,
    DATEPART(HOUR, dd_start.calendar_date)               AS unused_marker, -- placeholder
    -- Actual hour-of-day source: encounter start time. Pull from the
    -- fact's date+time via the original encounter; fact_encounter only
    -- has date_sk, so we re-derive from the OLTP-aware column:
    CAST(fe.length_of_stay_hours AS INT)                 AS los_hours_bucket,
    COUNT(*)                                              AS ed_visits
FROM dw.fact_encounter fe
JOIN dw.dim_hospital   h       ON h.hospital_sk = fe.hospital_sk
JOIN dw.dim_date       dd_start ON dd_start.date_sk = fe.start_date_sk
WHERE fe.encounter_class = 'emergency'
  AND dd_start.calendar_date >= DATEADD(MONTH, -3, CONVERT(DATE, SYSUTCDATETIME()))
GROUP BY h.hospital_name, CAST(fe.length_of_stay_hours AS INT)
ORDER BY h.hospital_name, los_hours_bucket;
