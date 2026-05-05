# Power BI - DAX measures

Author these as a single Tabular Editor script under the `Measures` table
(or use Tabular Editor's "Apply to model" action). Names match the
on-screen labels used by the three-page report.

## Counts and volumes

```dax
[Encounters] = COUNTROWS('fact_encounter')

[Inpatient encounters] =
    CALCULATE([Encounters], 'fact_encounter'[is_inpatient] = TRUE())

[ED encounters] =
    CALCULATE([Encounters], 'fact_encounter'[is_emergency] = TRUE())

[Distinct patients] =
    DISTINCTCOUNT('fact_encounter'[patient_sk])

[Distinct providers] =
    DISTINCTCOUNT('fact_encounter'[provider_sk])
```

## Length of stay

```dax
[Avg length of stay (h)] =
    AVERAGEX(
        FILTER('fact_encounter', 'fact_encounter'[is_inpatient] = TRUE()),
        'fact_encounter'[length_of_stay_hours]
    )

[Median LOS (h)] =
    MEDIANX(
        FILTER('fact_encounter', 'fact_encounter'[is_inpatient] = TRUE()),
        'fact_encounter'[length_of_stay_hours]
    )
```

## Readmission

```dax
[30d readmissions] =
    CALCULATE([Inpatient encounters],
              'fact_encounter'[is_readmission_30d] = TRUE())

[30d readmission rate] =
    DIVIDE([30d readmissions], [Inpatient encounters])

-- Display as percentage with 2 decimals.
```

## Revenue

```dax
[Billed amount] = SUM('fact_claim'[billed_amount])
[Paid amount]   = SUM('fact_claim'[paid_amount])
[Allowed amount]= SUM('fact_claim'[allowed_amount])

[Collection rate] = DIVIDE([Paid amount], [Billed amount])

[Denial rate (count)] =
    DIVIDE(
        CALCULATE(COUNTROWS('fact_claim'), 'fact_claim'[is_denied] = TRUE()),
        COUNTROWS('fact_claim')
    )

[Denial rate (dollars)] =
    DIVIDE(
        CALCULATE(SUM('fact_claim'[denied_amount]), 'fact_claim'[is_denied] = TRUE()),
        [Billed amount]
    )

[Days to decision (avg)] =
    AVERAGE('fact_claim'[days_to_decision])
```

## Time intelligence (uses dim_date marked as date table)

```dax
[Encounters MTD]   = CALCULATE([Encounters], DATESMTD('dim_date'[calendar_date]))
[Encounters YTD]   = CALCULATE([Encounters], DATESYTD('dim_date'[calendar_date]))
[Encounters PYTD]  = CALCULATE([Encounters], DATESYTD(SAMEPERIODLASTYEAR('dim_date'[calendar_date])))
[Encounters YoY %] = DIVIDE([Encounters YTD] - [Encounters PYTD], [Encounters PYTD])
```

## Vital signs

```dax
[Active alerts last 24h] =
    CALCULATE(
        SUM('fact_vital_signs_minute'[anomaly_event_count]),
        'fact_vital_signs_minute'[minute_start_utc] >=
            UTCNOW() - TIME(24, 0, 0)
    )

[Devices reporting last hour] =
    CALCULATE(
        DISTINCTCOUNT('fact_vital_signs_minute'[device_id]),
        'fact_vital_signs_minute'[minute_start_utc] >=
            UTCNOW() - TIME(1, 0, 0)
    )

[Heart rate (avg, last minute)] =
    CALCULATE(
        AVERAGE('fact_vital_signs_minute'[heart_rate_avg]),
        TOPN(1, 'fact_vital_signs_minute', 'fact_vital_signs_minute'[minute_start_utc], DESC)
    )
```

## Helper / display

```dax
[Patient name (current)] =
    -- The dim_patient model has SCD2 history; reports almost always want
    -- the current attributes. Filter to is_current = 1 in the relationship
    -- (handled in model view) and surface this measure for safety.
    SELECTEDVALUE('dim_patient'[full_name])

[Hospital label] =
    SELECTEDVALUE('dim_hospital'[hospital_name]) & " ("
        & SELECTEDVALUE('dim_hospital'[governorate]) & ")"
```

## Modelling notes

* `dim_date` should be marked as a date table on `calendar_date`.
* `dim_patient` and `dim_provider` connect to facts via the surrogate key.
  Hide the SCD2 columns (`record_hash`, `effective_*`) from report view.
* All `*_sk` columns are hidden; expose readable columns
  (`hospital_name`, `payer_name`, `icd10_code` + `description`).
* Cross-filter direction: single (dim -> fact). Two-way only where strictly
  needed; the bridge `bridge_encounter_diagnosis` uses two-way to allow
  diagnosis filters to reach the encounter fact.
* Storage mode: **Import** for dims and the daily KPI table,
  **DirectQuery** for `fact_vital_signs_minute` so live alerts don't lag
  the next refresh.
