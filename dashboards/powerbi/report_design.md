# Power BI - report design notes

The `.pbix` file is not committed (binary, large, regenerable). This
document is the source of truth for the report layout; rebuild the file
from these notes if it's lost or corrupted.

## File: `Healthcare_DW.pbix`

Three pages, identical filter pane on each (hospital, date range, encounter
class, payer).

### Page 1 - Hospital Operations

| Slot              | Visual              | Field(s) / measure |
|-------------------|---------------------|--------------------|
| Top-left card     | KPI                 | `[Encounters]` |
| Top-mid card      | KPI                 | `[Avg length of stay (h)]` |
| Top-right card    | KPI                 | `[30d readmission rate]` |
| Top-right card 2  | KPI                 | `[ED encounters]` |
| Mid-left          | Stacked column      | x: `dim_date.calendar_date` (month), y: `[Encounters]`, legend: `encounter_class` |
| Mid-right         | Donut               | `encounter_class` -> `[Encounters]` |
| Bottom-left       | Bar (top 10)        | y: `dim_diagnosis.description`, x: `[Encounters]` |
| Bottom-right      | Map (filled)        | location: `dim_patient.governorate`, size: `[Encounters]` |

### Page 2 - Revenue & Claims

| Slot              | Visual           | Field(s) / measure |
|-------------------|------------------|--------------------|
| Top KPIs          | 4 KPI cards      | `[Billed amount]`, `[Paid amount]`, `[Collection rate]`, `[Denial rate (count)]` |
| Mid-left          | Clustered column | x: `dim_date` (month), y: `[Billed amount]`, `[Paid amount]` |
| Mid-right         | Bar              | y: `dim_payer.payer_name`, x: `[Denial rate (dollars)]` |
| Bottom-left       | Pie              | `status` -> `[Encounters]` -> rename measure to `[Claims]` |
| Bottom-right      | Table            | `dim_payer.payer_name`, `[Claims]`, `[Days to decision (avg)]`, `[Denial rate (count)]` |

### Page 3 - Live Vital Signs

DirectQuery only.

| Slot          | Visual          | Field(s) / measure |
|---------------|-----------------|--------------------|
| Top KPIs      | KPI cards       | `[Devices reporting last hour]`, `[Active alerts last 24h]` |
| Top-right     | Page-level filter | last 24h on `minute_start_utc` |
| Left          | Table           | top 20 anomaly minutes (sorted by `anomaly_event_count` desc) |
| Right (top)   | Line chart      | `minute_start_utc` -> `heart_rate_avg`, `spo2_avg`, `systolic_avg` for selected patient |
| Right (bot.)  | Card / RLS demo | "Patient: " & `[Patient name (current)]` |

## Theme

* Primary color #1B4F72 (blue), accent #E74C3C (red - denial / alerts),
  success #27AE60 (green - paid).
* Font: Segoe UI Semibold for KPI cards, Segoe UI for body. Same palette
  as the LaTeX developer guide so screenshots blend across the report.

## Refresh

* Dataset refresh on Power BI Service: 03:30 UTC, after the nightly ADF
  pipeline completes.
* Incremental refresh on `fact_encounter` and `fact_claim`: keep last 5
  years, refresh last 30 days.
* `fact_vital_signs_minute` is DirectQuery so it doesn't get a refresh
  schedule.

## Row-level security (RLS)

Two roles defined under Modeling -> Manage Roles:

* `HospitalOps` - filter on `dim_hospital[hospital_bk]`
  IN VALUES(USERPRINCIPALNAME() membership table). Limits each ops manager
  to their facility.
* `RevenueCycle` - no row filter; this team needs network-wide view.

The membership table (`security_user_hospital`) lives in Synapse and is
imported alongside the model, joined to `USERPRINCIPALNAME()`.
