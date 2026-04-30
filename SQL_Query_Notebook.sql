

-- ????????????????????????????????????????????????????????????
-- QUERY 1: 30-Day Readmission Rate by Condition
-- Techniques: Window functions (LAG, DATEDIFF), CTE, CASE
-- Business Q: Which conditions have the highest 30-day
--             readmission rates?
-- ????????????????????????????????????????????????????????????
WITH encounter_with_lag AS
(
    SELECT
        fe.encounter_key,
        fe.patient_key,
        fe.date_key,
        d.full_date                                                 AS encounter_date,
        fe.encounter_type,
        fe.readmission_flag,
        fe.readmission_days,
        -- Pull the most recent prior encounter date for same patient
        LAG(d.full_date) OVER
            (PARTITION BY fe.patient_key ORDER BY d.full_date)     AS prev_encounter_date,
        dd.icd10_code,
        dd.description                                              AS condition_name,
        dd.body_system
    FROM   dbo.fact_encounters    fe
    JOIN   dbo.dim_date           d   ON d.date_key       = fe.date_key
    -- Join conditions through encounters (simplified — in production via bridge)
    LEFT JOIN dbo.dim_diagnosis   dd  ON dd.diagnosis_key  = fe.encounter_key  -- simplified join
)
,readmission_by_condition AS
(
    SELECT
        condition_name,
        body_system,
        icd10_code,
        COUNT(*)                                                    AS total_encounters,
        SUM(readmission_flag)                                       AS readmissions,
        ROUND(
            100.0 * SUM(readmission_flag) / NULLIF(COUNT(*), 0), 2
        )                                                           AS readmission_rate_pct,
        AVG(CAST(readmission_days AS FLOAT))                        AS avg_days_to_readmit
    FROM   encounter_with_lag
    WHERE  condition_name IS NOT NULL
    GROUP BY condition_name, body_system, icd10_code
    HAVING COUNT(*) >= 50   -- exclude conditions with very low sample size
)
SELECT
    RANK() OVER (ORDER BY readmission_rate_pct DESC)                AS rank_by_readmission,
    condition_name,
    body_system,
    icd10_code,
    total_encounters,
    readmissions,
    readmission_rate_pct,
    ROUND(avg_days_to_readmit, 1)                                   AS avg_days_to_readmit,
    CASE
        WHEN readmission_rate_pct >= 20 THEN 'High Risk'
        WHEN readmission_rate_pct >= 10 THEN 'Medium Risk'
        ELSE 'Low Risk'
    END                                                             AS risk_category
FROM   readmission_by_condition
ORDER BY readmission_rate_pct DESC;


-- ????????????????????????????????????????????????????????????
-- QUERY 2: Patient Cost Distribution by Quintile
-- Techniques: NTILE, PERCENTILE_CONT, window aggregation
-- Business Q: How is healthcare cost distributed across
--             the patient population?
-- ????????????????????????????????????????????????????????????
WITH patient_total_cost AS
(
    SELECT
        fe.patient_key,
        p.first_name + ' ' + p.last_name                           AS patient_name,
        p.insurance_type,
        p.age_group,
        p.state,
        SUM(fe.total_cost)                                          AS lifetime_cost,
        COUNT(fe.encounter_key)                                     AS encounter_count,
        AVG(fe.total_cost)                                          AS avg_cost_per_visit,
        SUM(fe.length_of_stay_days)                                 AS total_los_days
    FROM   dbo.fact_encounters  fe
    JOIN   dbo.dim_patient      p  ON p.patient_key = fe.patient_key
                                   AND p.is_current = 1
    WHERE  fe.total_cost IS NOT NULL
    GROUP BY
        fe.patient_key,
        p.first_name, p.last_name,
        p.insurance_type, p.age_group, p.state
)
,cost_with_ntile AS
(
    SELECT
        *,
        NTILE(5) OVER (ORDER BY lifetime_cost)                      AS cost_quintile,
        NTILE(10) OVER (ORDER BY lifetime_cost)                     AS cost_decile,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY lifetime_cost)
            OVER ()                                                 AS median_cost,
        PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY lifetime_cost)
            OVER ()                                                 AS p90_cost,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY lifetime_cost)
            OVER ()                                                 AS p95_cost,
        SUM(lifetime_cost) OVER ()                                  AS population_total_cost
    FROM   patient_total_cost
)
SELECT
    cost_quintile,
    CASE cost_quintile
        WHEN 1 THEN 'Q1 — Lowest 20%'
        WHEN 2 THEN 'Q2 — Low-Medium'
        WHEN 3 THEN 'Q3 — Middle'
        WHEN 4 THEN 'Q4 — High-Medium'
        WHEN 5 THEN 'Q5 — Highest 20%'
    END                                                             AS quintile_label,
    COUNT(*)                                                        AS patient_count,
    MIN(lifetime_cost)                                              AS min_cost,
    MAX(lifetime_cost)                                              AS max_cost,
    AVG(lifetime_cost)                                              AS avg_cost,
    MIN(median_cost)                                                AS population_median,
    MIN(p90_cost)                                                   AS population_p90,
    SUM(lifetime_cost)                                              AS quintile_total_cost,
    ROUND(
        100.0 * SUM(lifetime_cost) / MIN(population_total_cost), 2
    )                                                               AS pct_of_total_spend
FROM   cost_with_ntile
GROUP BY cost_quintile
ORDER BY cost_quintile;


-- ????????????????????????????????????????????????????????????
-- QUERY 3: Provider Performance Ranking
-- Techniques: RANK, DENSE_RANK, AVG OVER partition, CASE
-- Business Q: Which providers deliver best outcomes relative
--             to cost and readmission rates?
-- ????????????????????????????????????????????????????????????
WITH provider_metrics AS
(
    SELECT
        pr.provider_key,
        pr.provider_name,
        pr.specialty,
        pr.organization,
        COUNT(fe.encounter_key)                                     AS total_patients_seen,
        AVG(fe.total_cost)                                          AS avg_cost_per_encounter,
        AVG(fe.length_of_stay_days)                                 AS avg_length_of_stay,
        ROUND(
            100.0 * SUM(fe.readmission_flag) /
            NULLIF(COUNT(fe.encounter_key), 0), 2
        )                                                           AS readmission_rate_pct,
        SUM(fe.total_cost)                                          AS total_revenue_generated,
        COUNT(DISTINCT fe.patient_key)                              AS unique_patients
    FROM   dbo.fact_encounters  fe
    JOIN   dbo.dim_provider     pr ON pr.provider_key = fe.provider_key
                                   AND pr.is_current = 1
    WHERE  fe.date_key >= 20230101   -- last 2 years
    GROUP BY
        pr.provider_key, pr.provider_name,
        pr.specialty, pr.organization
    HAVING COUNT(fe.encounter_key) >= 30   -- minimum volume threshold
)
,ranked_providers AS
(
    SELECT
        *,
        RANK() OVER (PARTITION BY specialty ORDER BY readmission_rate_pct ASC)  AS rank_readmission_in_specialty,
        RANK() OVER (PARTITION BY specialty ORDER BY avg_cost_per_encounter ASC) AS rank_cost_in_specialty,
        DENSE_RANK() OVER (ORDER BY total_revenue_generated DESC)               AS rank_revenue_overall,
        AVG(avg_cost_per_encounter) OVER (PARTITION BY specialty)               AS specialty_avg_cost,
        AVG(readmission_rate_pct) OVER (PARTITION BY specialty)                 AS specialty_avg_readmission
    FROM   provider_metrics
)
SELECT
    provider_name,
    specialty,
    organization,
    total_patients_seen,
    unique_patients,
    ROUND(avg_cost_per_encounter, 2)                                AS avg_cost_per_encounter,
    ROUND(specialty_avg_cost, 2)                                    AS specialty_benchmark_cost,
    ROUND(avg_cost_per_encounter - specialty_avg_cost, 2)           AS cost_vs_benchmark,
    ROUND(avg_length_of_stay, 2)                                    AS avg_los_days,
    readmission_rate_pct,
    ROUND(specialty_avg_readmission, 2)                             AS specialty_avg_readmission,
    rank_readmission_in_specialty,
    rank_cost_in_specialty,
    rank_revenue_overall,
    -- Composite performance score: lower cost + lower readmission = better
    CASE
        WHEN rank_readmission_in_specialty <= 3
         AND rank_cost_in_specialty <= 3
        THEN 'Top Performer'
        WHEN rank_readmission_in_specialty <= 5
          OR rank_cost_in_specialty <= 5
        THEN 'Above Average'
        ELSE 'Average'
    END                                                             AS performance_tier
FROM   ranked_providers
ORDER BY specialty, rank_readmission_in_specialty;


-- ????????????????????????????????????????????????????????????
-- QUERY 4: Condition Co-occurrence Analysis
-- Techniques: Self-join, conditional aggregation, pivot
-- Business Q: Which conditions frequently appear together
--             in the same patient? (Comorbidity matrix)
-- ????????????????????????????????????????????????????????????
WITH patient_conditions AS
(
    -- Get top 10 conditions by prevalence (for manageable matrix)
    SELECT TOP 10
        dd.icd10_code,
        dd.description AS condition_name,
        COUNT(DISTINCT fe.patient_key) AS patient_count
    FROM   dbo.fact_encounters  fe
    JOIN   dbo.dim_diagnosis    dd ON dd.diagnosis_key = fe.encounter_key
    WHERE  dd.icd10_code IS NOT NULL
    GROUP BY dd.icd10_code, dd.description
    ORDER BY patient_count DESC
)
,co_occurrence AS
(
    SELECT
        c1.icd10_code   AS condition_a_code,
        c1.condition_name AS condition_a,
        c2.icd10_code   AS condition_b_code,
        c2.condition_name AS condition_b,
        COUNT(DISTINCT fe1.patient_key) AS patients_with_both
    FROM   dbo.fact_encounters fe1
    JOIN   dbo.fact_encounters fe2
        ON fe1.patient_key = fe2.patient_key        -- same patient
        AND fe1.encounter_key < fe2.encounter_key   -- avoid self-join duplicates
    JOIN   dbo.dim_diagnosis c1 ON c1.diagnosis_key = fe1.encounter_key
    JOIN   dbo.dim_diagnosis c2 ON c2.diagnosis_key = fe2.encounter_key
    WHERE  c1.icd10_code IN (SELECT icd10_code FROM patient_conditions)
      AND  c2.icd10_code IN (SELECT icd10_code FROM patient_conditions)
      AND  c1.icd10_code <> c2.icd10_code
    GROUP BY
        c1.icd10_code, c1.description,
        c2.icd10_code, c2.description
)
SELECT
    condition_a,
    condition_b,
    patients_with_both,
    -- Jaccard similarity coefficient
    ROUND(
        1.0 * patients_with_both /
        (
            (SELECT COUNT(DISTINCT fe.patient_key) FROM dbo.fact_encounters fe
             JOIN dbo.dim_diagnosis dd ON dd.diagnosis_key = fe.encounter_key
             WHERE dd.icd10_code = co.condition_a_code)
            +
            (SELECT COUNT(DISTINCT fe.patient_key) FROM dbo.fact_encounters fe
             JOIN dbo.dim_diagnosis dd ON dd.diagnosis_key = fe.encounter_key
             WHERE dd.icd10_code = co.condition_b_code)
            - patients_with_both
        )
    , 4)                                                            AS jaccard_similarity
FROM   co_occurrence co
ORDER BY patients_with_both DESC;


-- ????????????????????????????????????????????????????????????
-- QUERY 5: Monthly Encounter Volume Trends + MoM Growth
-- Techniques: DATE_TRUNC, LAG for MoM%, running total
-- Business Q: How are encounter volumes trending over time?
--             Are there seasonal patterns?
-- ????????????????????????????????????????????????????????????
WITH monthly_volume AS
(
    SELECT
        d.year,
        d.month,
        d.month_name,
        d.year_month,
        d.fiscal_year,
        d.fiscal_quarter,
        COUNT(fe.encounter_key)                                     AS total_encounters,
        COUNT(DISTINCT fe.patient_key)                              AS unique_patients,
        SUM(fe.total_cost)                                          AS total_revenue,
        AVG(fe.length_of_stay_days)                                 AS avg_los,
        SUM(CASE WHEN fe.encounter_type = 'emergency' THEN 1 ELSE 0 END) AS emergency_encounters,
        SUM(CASE WHEN fe.encounter_type = 'inpatient' THEN 1 ELSE 0 END) AS inpatient_encounters
    FROM   dbo.fact_encounters  fe
    JOIN   dbo.dim_date         d ON d.date_key = fe.date_key
    WHERE  d.year BETWEEN 2022 AND 2025
    GROUP BY d.year, d.month, d.month_name, d.year_month, d.fiscal_year, d.fiscal_quarter
)
SELECT
    year_month,
    month_name,
    fiscal_year,
    fiscal_quarter,
    total_encounters,
    unique_patients,
    ROUND(total_revenue, 2)                                         AS total_revenue,
    ROUND(avg_los, 2)                                               AS avg_los_days,
    emergency_encounters,
    inpatient_encounters,
    -- Month-over-month change
    LAG(total_encounters) OVER (ORDER BY year, month)               AS prev_month_encounters,
    total_encounters -
        LAG(total_encounters) OVER (ORDER BY year, month)           AS mom_encounter_change,
    ROUND(
        100.0 * (total_encounters -
            LAG(total_encounters) OVER (ORDER BY year, month)) /
        NULLIF(LAG(total_encounters) OVER (ORDER BY year, month), 0)
    , 2)                                                            AS mom_growth_pct,
    -- Year-over-year comparison
    LAG(total_encounters, 12) OVER (ORDER BY year, month)           AS same_month_last_year,
    ROUND(
        100.0 * (total_encounters -
            LAG(total_encounters, 12) OVER (ORDER BY year, month)) /
        NULLIF(LAG(total_encounters, 12) OVER (ORDER BY year, month), 0)
    , 2)                                                            AS yoy_growth_pct,
    -- Cumulative running total
    SUM(total_encounters) OVER (
        PARTITION BY year ORDER BY month ROWS UNBOUNDED PRECEDING
    )                                                               AS ytd_encounters,
    SUM(total_revenue) OVER (
        PARTITION BY year ORDER BY month ROWS UNBOUNDED PRECEDING
    )                                                               AS ytd_revenue
FROM   monthly_volume
ORDER BY year, month;


-- ????????????????????????????????????????????????????????????
-- QUERY 6: Claim Denial Analysis by Payer and Reason
-- Techniques: GROUP BY GROUPING SETS, HAVING, ratio analysis
-- Business Q: What are denial rates by payer and reason?
--             Which payers are most problematic?
-- ????????????????????????????????????????????????????????????
WITH denial_base AS
(
    SELECT
        py.payer_name,
        py.payer_type,
        fc.claim_status,
        fc.denial_reason,
        fc.denial_reason_code,
        fc.amount_billed,
        fc.amount_paid,
        fc.amount_denied,
        fc.processing_days,
        d.year,
        d.quarter_name
    FROM   dbo.fact_claims   fc
    JOIN   dbo.dim_payer     py ON py.payer_key = fc.payer_key
    JOIN   dbo.dim_date      d  ON d.date_key   = fc.date_key
    WHERE  d.year = 2024   -- current fiscal year
)
SELECT
    COALESCE(payer_name,       'ALL PAYERS')    AS payer_name,
    COALESCE(payer_type,       'ALL TYPES')     AS payer_type,
    COALESCE(denial_reason,    'ALL REASONS')   AS denial_reason,
    COUNT(*)                                     AS total_claims,
    SUM(CASE WHEN claim_status = 'denied'  THEN 1 ELSE 0 END)  AS denied_claims,
    SUM(CASE WHEN claim_status = 'approved' OR
                  claim_status = 'paid'    THEN 1 ELSE 0 END)  AS approved_claims,
    ROUND(
        100.0 * SUM(CASE WHEN claim_status = 'denied' THEN 1 ELSE 0 END) /
        NULLIF(COUNT(*), 0)
    , 2)                                         AS denial_rate_pct,
    SUM(amount_billed)                           AS total_billed,
    SUM(amount_denied)                           AS total_denied_amount,
    ROUND(AVG(CAST(processing_days AS FLOAT)), 1) AS avg_processing_days,
    -- Grouping identifier
    CASE
        WHEN GROUPING(payer_name) = 1 AND GROUPING(denial_reason) = 1 THEN 'Grand Total'
        WHEN GROUPING(denial_reason) = 1                              THEN 'Payer Subtotal'
        ELSE 'Detail'
    END                                          AS row_level
FROM   denial_base
GROUP BY GROUPING SETS
(
    (payer_name, payer_type, denial_reason),    -- detail level
    (payer_name, payer_type),                   -- payer subtotal
    ()                                          -- grand total
)
HAVING
    COUNT(*) >= 10                              -- suppress tiny groups
ORDER BY
    GROUPING(payer_name),
    GROUPING(denial_reason),
    denial_rate_pct DESC;


-- ????????????????????????????????????????????????????????????
-- QUERY 7: Length of Stay Analysis with Outlier Detection
-- Techniques: DATEDIFF, CASE, statistical outlier (IQR method)
-- Business Q: What are LOS patterns? Where are the outliers?
-- ????????????????????????????????????????????????????????????
WITH los_stats AS
(
    SELECT
        fe.encounter_key,
        fe.patient_key,
        fe.encounter_type,
        dd.description                                              AS primary_condition,
        dd.body_system,
        pr.specialty,
        fe.length_of_stay_days,
        fe.total_cost,
        -- Statistical benchmarks using Synapse window percentiles
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY fe.length_of_stay_days)
            OVER (PARTITION BY fe.encounter_type)                   AS q1_los,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY fe.length_of_stay_days)
            OVER (PARTITION BY fe.encounter_type)                   AS median_los,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY fe.length_of_stay_days)
            OVER (PARTITION BY fe.encounter_type)                   AS q3_los,
        AVG(fe.length_of_stay_days)
            OVER (PARTITION BY fe.encounter_type)                   AS mean_los_by_type,
        AVG(fe.length_of_stay_days)
            OVER (PARTITION BY dd.body_system)                      AS mean_los_by_body_system
    FROM   dbo.fact_encounters  fe
    LEFT JOIN dbo.dim_diagnosis dd ON dd.diagnosis_key = fe.encounter_key
    LEFT JOIN dbo.dim_provider  pr ON pr.provider_key  = fe.provider_key AND pr.is_current = 1
    WHERE  fe.length_of_stay_days IS NOT NULL
      AND  fe.length_of_stay_days > 0
)
,los_with_iqr AS
(
    SELECT
        *,
        q3_los - q1_los                                             AS iqr,
        -- IQR-based outlier fences (Tukey method: 1.5 * IQR)
        q1_los - (1.5 * (q3_los - q1_los))                         AS lower_fence,
        q3_los + (1.5 * (q3_los - q1_los))                         AS upper_fence
    FROM   los_stats
)
SELECT
    encounter_type,
    body_system,
    primary_condition,
    COUNT(*)                                                        AS encounter_count,
    ROUND(MIN(length_of_stay_days), 2)                              AS min_los,
    ROUND(AVG(length_of_stay_days), 2)                              AS mean_los,
    ROUND(MIN(median_los), 2)                                       AS median_los,
    ROUND(MAX(length_of_stay_days), 2)                              AS max_los,
    ROUND(MIN(q1_los), 2)                                           AS q1_los,
    ROUND(MIN(q3_los), 2)                                           AS q3_los,
    ROUND(MIN(iqr), 2)                                              AS iqr,
    SUM(CASE WHEN length_of_stay_days > upper_fence THEN 1 ELSE 0 END) AS high_outlier_count,
    SUM(CASE WHEN length_of_stay_days < lower_fence THEN 1 ELSE 0 END) AS low_outlier_count,
    ROUND(AVG(CASE WHEN length_of_stay_days > upper_fence
              THEN total_cost END), 2)                              AS avg_outlier_cost,
    ROUND(AVG(CASE WHEN length_of_stay_days BETWEEN lower_fence AND upper_fence
              THEN total_cost END), 2)                              AS avg_normal_cost
FROM   los_with_iqr
GROUP BY encounter_type, body_system, primary_condition
HAVING COUNT(*) >= 20
ORDER BY mean_los DESC;


-- ????????????????????????????????????????????????????????????
-- QUERY 8: Patient Cohort Retention Analysis
-- Techniques: Date arithmetic, cohort assignment, pivot
-- Business Q: How do patient cohorts return for follow-up
--             visits over a 12-month period?
-- ????????????????????????????????????????????????????????????
WITH first_encounter AS
(
    -- Each patient's very first encounter = cohort enrollment
    SELECT
        fe.patient_key,
        MIN(d.full_date)                                            AS first_encounter_date,
        FORMAT(MIN(d.full_date), 'yyyy-MM')                         AS cohort_month
    FROM   dbo.fact_encounters  fe
    JOIN   dbo.dim_date         d  ON d.date_key = fe.date_key
    WHERE  d.year >= 2022
    GROUP BY fe.patient_key
)
,all_encounters AS
(
    SELECT
        fe.patient_key,
        d.full_date                                                 AS encounter_date
    FROM   dbo.fact_encounters  fe
    JOIN   dbo.dim_date         d  ON d.date_key = fe.date_key
)
,cohort_activity AS
(
    SELECT
        f.cohort_month,
        f.patient_key,
        f.first_encounter_date,
        a.encounter_date,
        -- Month offset from first encounter (0 = enrollment month)
        DATEDIFF(MONTH, f.first_encounter_date, a.encounter_date)   AS months_since_enrollment
    FROM   first_encounter  f
    JOIN   all_encounters   a ON a.patient_key = f.patient_key
    WHERE  DATEDIFF(MONTH, f.first_encounter_date, a.encounter_date) BETWEEN 0 AND 12
)
SELECT
    cohort_month,
    COUNT(DISTINCT CASE WHEN months_since_enrollment = 0  THEN patient_key END) AS month_0_enrolled,
    COUNT(DISTINCT CASE WHEN months_since_enrollment = 1  THEN patient_key END) AS month_1_retained,
    COUNT(DISTINCT CASE WHEN months_since_enrollment = 3  THEN patient_key END) AS month_3_retained,
    COUNT(DISTINCT CASE WHEN months_since_enrollment = 6  THEN patient_key END) AS month_6_retained,
    COUNT(DISTINCT CASE WHEN months_since_enrollment = 12 THEN patient_key END) AS month_12_retained,
    -- Retention rates
    ROUND(100.0 *
        COUNT(DISTINCT CASE WHEN months_since_enrollment = 1  THEN patient_key END) /
        NULLIF(COUNT(DISTINCT CASE WHEN months_since_enrollment = 0 THEN patient_key END), 0)
    , 1)                                                            AS month_1_retention_pct,
    ROUND(100.0 *
        COUNT(DISTINCT CASE WHEN months_since_enrollment = 6  THEN patient_key END) /
        NULLIF(COUNT(DISTINCT CASE WHEN months_since_enrollment = 0 THEN patient_key END), 0)
    , 1)                                                            AS month_6_retention_pct,
    ROUND(100.0 *
        COUNT(DISTINCT CASE WHEN months_since_enrollment = 12 THEN patient_key END) /
        NULLIF(COUNT(DISTINCT CASE WHEN months_since_enrollment = 0 THEN patient_key END), 0)
    , 1)                                                            AS month_12_retention_pct
FROM   cohort_activity
GROUP BY cohort_month
ORDER BY cohort_month;


-- ????????????????????????????????????????????????????????????
-- QUERY 9: Top Medications by Cost — Pareto Analysis
-- Techniques: SUM, RANK, cumulative percentage (80/20 rule)
-- Business Q: Which medications drive the most cost?
--             Can we identify the Pareto-dominant drugs?
-- ????????????????????????????????????????????????????????????
WITH medication_cost AS
(
    -- Aggregate cost metrics per drug (from Silver medication table)
    -- In production this joins to a fact_medications fact table
    SELECT
        drug_code,
        drug_description,
        body_system,                            -- derived from RxNorm mapping
        COUNT(*)                                AS prescription_count,
        COUNT(DISTINCT patient_key)             AS unique_patients,
        SUM(unit_cost * quantity)               AS total_drug_cost,
        AVG(unit_cost)                          AS avg_unit_cost,
        AVG(duration_days)                      AS avg_prescription_days
    FROM   dbo.silver_medications               -- Silver table (pre-aggregated)
    GROUP BY drug_code, drug_description, body_system
)
,ranked_medications AS
(
    SELECT
        *,
        RANK() OVER (ORDER BY total_drug_cost DESC)                 AS cost_rank,
        SUM(total_drug_cost) OVER ()                                AS grand_total_cost
    FROM   medication_cost
)
,cumulative AS
(
    SELECT
        *,
        SUM(total_drug_cost) OVER (ORDER BY cost_rank
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)       AS cumulative_cost,
        ROUND(
            100.0 * SUM(total_drug_cost) OVER (ORDER BY cost_rank
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) /
            NULLIF(grand_total_cost, 0)
        , 2)                                                        AS cumulative_pct
    FROM   ranked_medications
)
SELECT
    cost_rank,
    drug_description,
    body_system,
    prescription_count,
    unique_patients,
    ROUND(total_drug_cost, 2)                                       AS total_drug_cost,
    ROUND(avg_unit_cost, 4)                                         AS avg_unit_cost,
    ROUND(avg_prescription_days, 1)                                 AS avg_prescription_days,
    ROUND(100.0 * total_drug_cost / NULLIF(grand_total_cost, 0), 3) AS pct_of_total_spend,
    cumulative_pct,
    CASE
        WHEN cumulative_pct <= 80 THEN 'Pareto Top 80%'
        ELSE 'Tail Medications'
    END                                                             AS pareto_category
FROM   cumulative
ORDER BY cost_rank;


-- ????????????????????????????????????????????????????????????
-- QUERY 10: Vital Signs Anomaly Patterns — When Do Crises Occur?
-- Techniques: Filtering, time-of-day patterns, aggregation
-- Business Q: When do vital sign anomalies occur most?
--             Which patient groups are most at risk?
-- ????????????????????????????????????????????????????????????
WITH anomaly_base AS
(
    SELECT
        fv.vital_key,
        fv.patient_key,
        fv.anomaly_type,
        fv.anomaly_severity,
        fv.heart_rate,
        fv.systolic_bp,
        fv.diastolic_bp,
        fv.temperature,
        fv.spo2,
        dt.shift,
        dt.shift_period,
        dt.is_business_hour,
        dt.hour,
        d.day_name,
        d.is_weekend,
        d.month_name,
        p.age_group,
        p.gender,
        p.insurance_type
    FROM   dbo.fact_vitals      fv
    JOIN   dbo.dim_time         dt ON dt.time_key    = fv.time_key
    JOIN   dbo.dim_date         d  ON d.date_key     = fv.date_key
    JOIN   dbo.dim_patient      p  ON p.patient_key  = fv.patient_key
                                   AND p.is_current  = 1
    WHERE  fv.anomaly_flag = 1
)
SELECT
    shift,
    shift_period,
    CASE WHEN is_business_hour = 1 THEN 'Business Hours' ELSE 'Off Hours' END AS hour_category,
    day_name,
    CASE WHEN is_weekend = 1 THEN 'Weekend' ELSE 'Weekday' END                AS day_type,
    anomaly_type,
    anomaly_severity,
    age_group,
    gender,
    COUNT(*)                                                        AS anomaly_count,
    COUNT(DISTINCT patient_key)                                     AS unique_patients_affected,
    ROUND(AVG(heart_rate), 1)                                       AS avg_hr_during_anomaly,
    ROUND(AVG(systolic_bp), 1)                                      AS avg_systolic_during_anomaly,
    ROUND(AVG(temperature), 2)                                      AS avg_temp_during_anomaly,
    ROUND(AVG(spo2), 2)                                             AS avg_spo2_during_anomaly,
    -- Peak hour within group
    MAX(hour)                                                       AS latest_hour_in_group,
    MIN(hour)                                                       AS earliest_hour_in_group
FROM   anomaly_base
GROUP BY
    shift, shift_period, is_business_hour,
    day_name, is_weekend,
    anomaly_type, anomaly_severity,
    age_group, gender
HAVING COUNT(*) >= 5   -- suppress noise
ORDER BY anomaly_count DESC;


-- ????????????????????????????????????????????????????????????
-- BONUS QUERY 11: Financial Dashboard — Revenue Waterfall KPIs
-- Techniques: Conditional aggregation, multi-fact join
-- Business Q: What is the net revenue picture?
--             Billed ? Denied ? Adjusted ? Paid
-- ????????????????????????????????????????????????????????????
SELECT
    py.payer_name,
    py.payer_type,
    d.year,
    d.fiscal_quarter,
    COUNT(fc.claim_key)                                             AS total_claims,
    SUM(fc.amount_billed)                                           AS gross_billed,
    SUM(CASE WHEN fc.claim_status = 'denied'
             THEN fc.amount_billed ELSE 0 END)                      AS total_denied,
    SUM(fc.adjustment_amount)                                       AS total_adjustments,
    SUM(fc.amount_paid)                                             AS net_revenue_collected,
    -- Net collection rate
    ROUND(
        100.0 * SUM(fc.amount_paid) /
        NULLIF(SUM(fc.amount_billed), 0)
    , 2)                                                            AS collection_rate_pct,
    -- Days to collect (efficiency metric)
    ROUND(AVG(CAST(fc.processing_days AS FLOAT)), 1)                AS avg_days_to_collect,
    -- Claim mix
    SUM(CASE WHEN fc.claim_status = 'denied'   THEN 1 ELSE 0 END)  AS claims_denied,
    SUM(CASE WHEN fc.claim_status = 'appealed' THEN 1 ELSE 0 END)  AS claims_appealed,
    SUM(CASE WHEN fc.claim_status = 'paid'     THEN 1 ELSE 0 END)  AS claims_paid
FROM   dbo.fact_claims  fc
JOIN   dbo.dim_payer    py ON py.payer_key = fc.payer_key
JOIN   dbo.dim_date     d  ON d.date_key   = fc.date_key
WHERE  d.year >= 2023
GROUP BY py.payer_name, py.payer_type, d.year, d.fiscal_quarter
ORDER BY d.year, d.fiscal_quarter, gross_billed DESC;

PRINT 'All 11 analytical queries defined successfully.';