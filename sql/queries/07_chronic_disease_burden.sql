/* Q7. Chronic disease burden - patients with 2+ chronic conditions.
   "Chronic" set hard-coded to the most common ones in our population:
   hypertension (I10), T2DM (E11.9), hyperlipidemia (E78.5), CKD3 (N18.3),
   CAD (I25.10), asthma (J45.909).
   ----------------------------------------------------------------------- */
WITH chronic_codes AS (
    SELECT code FROM (VALUES
        ('I10'), ('E11.9'), ('E78.5'), ('N18.3'), ('I25.10'), ('J45.909')
    ) AS v(code)
), patient_chronic AS (
    SELECT
        bed.encounter_sk,
        fe.patient_sk,
        dx.icd10_code
    FROM dw.bridge_encounter_diagnosis bed
    JOIN dw.fact_encounter             fe  ON fe.encounter_sk = bed.encounter_sk
    JOIN dw.dim_diagnosis              dx  ON dx.diagnosis_sk = bed.diagnosis_sk
    JOIN chronic_codes                 cc  ON cc.code         = dx.icd10_code
), patient_summary AS (
    SELECT patient_sk, COUNT(DISTINCT icd10_code) AS chronic_condition_count
    FROM patient_chronic
    GROUP BY patient_sk
)
SELECT
    p.governorate,
    p.age_band,
    p.gender,
    COUNT(*)                                          AS patients_with_2_plus,
    AVG(CONVERT(DECIMAL(5,2), ps.chronic_condition_count))
                                                       AS avg_conditions
FROM patient_summary  ps
JOIN dw.dim_patient   p ON p.patient_sk = ps.patient_sk AND p.is_current = 1
WHERE ps.chronic_condition_count >= 2
GROUP BY p.governorate, p.age_band, p.gender
ORDER BY p.governorate, patients_with_2_plus DESC;
