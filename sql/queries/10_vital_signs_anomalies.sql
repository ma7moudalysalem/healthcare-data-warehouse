/* Q10. Vital sign anomalies in the last 24 hours.
   Pulls minute-level summaries; used by the streaming dashboard's "Active
   alerts" tile. Each row is one minute where the device emitted at least
   one anomalous sample.
   ----------------------------------------------------------------------- */
SELECT
    vs.minute_start_utc,
    vs.device_id,
    vs.bed_number,
    p.patient_bk                              AS patient_id,
    p.full_name                               AS patient_name,
    h.hospital_name,
    vs.heart_rate_avg, vs.heart_rate_max,
    vs.spo2_min,
    vs.systolic_avg, vs.diastolic_avg,
    vs.temperature_c_max,
    vs.anomaly_event_count,
    vs.primary_anomaly_kind
FROM dw.fact_vital_signs_minute vs
JOIN dw.dim_patient   p ON p.patient_sk  = vs.patient_sk AND p.is_current = 1
JOIN dw.dim_hospital  h ON h.hospital_sk = vs.hospital_sk
WHERE vs.anomaly_event_count > 0
  AND vs.minute_start_utc >= DATEADD(HOUR, -24, SYSUTCDATETIME())
ORDER BY vs.minute_start_utc DESC, vs.anomaly_event_count DESC;
