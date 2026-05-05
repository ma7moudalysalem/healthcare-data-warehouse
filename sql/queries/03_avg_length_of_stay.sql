/* Q3. Average length-of-stay (LOS) by diagnosis chapter and hospital.
   Excludes encounters with LOS in the top 1% to avoid skew from outliers
   (e.g. long-term rehab cases).
   ----------------------------------------------------------------------- */
WITH eligible AS (
    SELECT
        h.hospital_name,
        dx.chapter,
        fe.length_of_stay_hours
    FROM dw.fact_encounter fe
    JOIN dw.dim_hospital   h  ON h.hospital_sk   = fe.hospital_sk
    JOIN dw.dim_diagnosis  dx ON dx.diagnosis_sk = fe.primary_diagnosis_sk
    WHERE fe.is_inpatient = 1
      AND fe.length_of_stay_hours IS NOT NULL
), capped AS (
    SELECT
        e.*,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY length_of_stay_hours)
            OVER ()    AS p99
    FROM eligible e
)
SELECT
    hospital_name,
    chapter,
    COUNT(*)                                            AS inpatient_stays,
    CAST(AVG(length_of_stay_hours) AS DECIMAL(8,2))     AS avg_los_hours,
    CAST(MAX(length_of_stay_hours) AS DECIMAL(8,2))     AS max_los_hours
FROM capped
WHERE length_of_stay_hours <= p99
GROUP BY hospital_name, chapter
ORDER BY hospital_name, avg_los_hours DESC;
