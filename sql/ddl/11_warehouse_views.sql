/* =========================================================================
   11_warehouse_views.sql
   Reporting views over the star schema.

   Views are the contract that Power BI / Streamlit consume - we expose the
   readable column names and pre-join the hot dimensions so dashboard
   authors don't have to think about surrogate keys.
   ========================================================================= */

USE healthcare_dw;
GO

IF OBJECT_ID(N'dw.vw_encounter_enriched', N'V') IS NOT NULL DROP VIEW dw.vw_encounter_enriched;
GO
CREATE VIEW dw.vw_encounter_enriched AS
SELECT
    fe.encounter_sk,
    fe.encounter_bk                              AS encounter_id,
    fe.encounter_class,
    fe.start_date_sk,
    dd.calendar_date                             AS encounter_date,
    dd.[year]                                    AS encounter_year,
    dd.[month]                                   AS encounter_month,
    dd.month_name                                AS encounter_month_name,
    dd.day_name                                  AS encounter_day_of_week,
    fe.length_of_stay_hours,
    fe.is_inpatient,
    fe.is_emergency,
    fe.is_readmission_30d,
    fe.discharge_status,
    fe.total_cost_usd,
    fe.payer_coverage_usd,
    fe.out_of_pocket_usd,
    -- patient
    p.patient_bk                                 AS patient_id,
    p.full_name                                  AS patient_name,
    p.age_band,
    p.gender,
    p.governorate                                AS patient_governorate,
    -- hospital
    h.hospital_bk                                AS hospital_code,
    h.hospital_name,
    h.facility_type,
    h.governorate                                AS hospital_governorate,
    h.bed_count,
    -- provider
    pr.full_name                                 AS provider_name,
    pr.specialty                                 AS provider_specialty,
    -- primary diagnosis
    dx.icd10_code                                AS primary_icd10_code,
    dx.description                               AS primary_diagnosis,
    dx.chapter                                   AS diagnosis_chapter
FROM dw.fact_encounter      fe
JOIN dw.dim_date            dd ON dd.date_sk    = fe.start_date_sk
JOIN dw.dim_patient         p  ON p.patient_sk  = fe.patient_sk AND p.is_current = 1
JOIN dw.dim_hospital        h  ON h.hospital_sk = fe.hospital_sk
LEFT JOIN dw.dim_provider   pr ON pr.provider_sk= fe.provider_sk AND pr.is_current = 1
LEFT JOIN dw.dim_diagnosis  dx ON dx.diagnosis_sk = fe.primary_diagnosis_sk;
GO

IF OBJECT_ID(N'dw.vw_claim_enriched', N'V') IS NOT NULL DROP VIEW dw.vw_claim_enriched;
GO
CREATE VIEW dw.vw_claim_enriched AS
SELECT
    fc.claim_sk,
    fc.claim_number,
    fc.status,
    fc.is_denied,
    fc.is_paid_in_full,
    fc.days_to_decision,
    fc.line_count,
    fc.billed_amount,
    fc.allowed_amount,
    fc.paid_amount,
    fc.denied_amount,
    fc.patient_responsibility,
    fc.currency,
    dd_serv.calendar_date     AS service_date,
    dd_serv.[year]            AS service_year,
    dd_serv.[month]           AS service_month,
    dd_dec.calendar_date      AS decision_date,
    payer.payer_name          AS payer_name,
    payer.is_government       AS is_government_payer,
    h.hospital_name           AS hospital_name,
    h.facility_type           AS facility_type,
    p.age_band                AS patient_age_band,
    p.gender                  AS patient_gender,
    p.governorate             AS patient_governorate,
    dx.icd10_code             AS primary_icd10_code,
    dx.description            AS primary_diagnosis
FROM dw.fact_claim          fc
JOIN dw.dim_date            dd_serv ON dd_serv.date_sk = fc.service_date_sk
LEFT JOIN dw.dim_date       dd_dec  ON dd_dec.date_sk  = fc.decision_date_sk
LEFT JOIN dw.dim_payer      payer   ON payer.payer_sk  = fc.payer_sk
LEFT JOIN dw.dim_hospital   h       ON h.hospital_sk   = fc.hospital_sk
LEFT JOIN dw.dim_patient    p       ON p.patient_sk    = fc.patient_sk AND p.is_current = 1
LEFT JOIN dw.dim_diagnosis  dx      ON dx.diagnosis_sk = fc.primary_diagnosis_sk;
GO

IF OBJECT_ID(N'dw.vw_vital_signs_minute', N'V') IS NOT NULL DROP VIEW dw.vw_vital_signs_minute;
GO
CREATE VIEW dw.vw_vital_signs_minute AS
SELECT
    vs.minute_start_utc,
    vs.device_id,
    vs.bed_number,
    p.patient_bk           AS patient_id,
    p.full_name            AS patient_name,
    h.hospital_name,
    h.governorate          AS hospital_governorate,
    vs.heart_rate_avg, vs.heart_rate_min, vs.heart_rate_max,
    vs.spo2_avg, vs.spo2_min,
    vs.systolic_avg, vs.diastolic_avg,
    vs.respiratory_rate_avg,
    vs.temperature_c_avg, vs.temperature_c_max,
    vs.sample_count,
    vs.anomaly_event_count,
    vs.primary_anomaly_kind
FROM dw.fact_vital_signs_minute vs
JOIN dw.dim_patient  p ON p.patient_sk  = vs.patient_sk AND p.is_current = 1
JOIN dw.dim_hospital h ON h.hospital_sk = vs.hospital_sk;
GO

PRINT 'Reporting views (vw_encounter_enriched, vw_claim_enriched, vw_vital_signs_minute) created.';
GO
