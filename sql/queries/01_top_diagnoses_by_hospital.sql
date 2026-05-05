/* Q1. Top 10 primary diagnoses per hospital for the last 12 months.
   Used by: clinical-leadership monthly review.
   Audience: Chief Medical Officer.
   ----------------------------------------------------------------------- */
WITH ranked AS (
    SELECT
        h.hospital_name,
        dx.icd10_code,
        dx.description                          AS diagnosis,
        COUNT(*)                                AS encounter_count,
        ROW_NUMBER() OVER (
            PARTITION BY h.hospital_name
            ORDER BY COUNT(*) DESC
        ) AS rn
    FROM dw.fact_encounter         fe
    JOIN dw.dim_hospital           h  ON h.hospital_sk     = fe.hospital_sk
    JOIN dw.dim_diagnosis          dx ON dx.diagnosis_sk   = fe.primary_diagnosis_sk
    JOIN dw.dim_date               dd ON dd.date_sk        = fe.start_date_sk
    WHERE dd.calendar_date >= DATEADD(MONTH, -12, CONVERT(DATE, SYSUTCDATETIME()))
    GROUP BY h.hospital_name, dx.icd10_code, dx.description
)
SELECT hospital_name, icd10_code, diagnosis, encounter_count
FROM ranked
WHERE rn <= 10
ORDER BY hospital_name, encounter_count DESC;
