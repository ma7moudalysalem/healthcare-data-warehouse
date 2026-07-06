"""Populate the Azure SQL `dw` star schema with a REALISTIC synthetic dataset.

Not just random rows: patient names are Egyptian, diagnoses correlate with age,
encounter class / length-of-stay / cost correlate with diagnosis severity,
provider specialty matches the diagnosis, payer mix and denial rates are
carrier-specific, and there is mild seasonality. Every fact FK resolves to a
real dimension row so all three reporting views (and every dashboard page)
light up with data that reads like a real hospital network.

dim_date is created + populated by the DDL; this loader fills every other table.

Run AFTER the DDL:
    python -m pipelines.gold.seed_warehouse --patients 5000 --encounters 14000 \
        --claims 9000 --vital-minutes 3000
"""
from __future__ import annotations

import argparse
import hashlib
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

import pyodbc

SEED = 20260704

# governorate centroids (lat, lon) — clinics sit at these
GOV_CENTROIDS = {
    "Cairo": (30.05, 31.25), "Giza": (29.99, 31.16), "Alexandria": (31.20, 29.92),
    "Menoufia": (30.55, 31.01), "Sharqia": (30.59, 31.50), "Dakahlia": (31.04, 31.38),
    "Qalyubia": (30.46, 31.18), "Gharbia": (30.79, 31.00), "Beheira": (31.04, 30.47),
    "Aswan": (24.09, 32.90), "Luxor": (25.69, 32.64), "Suez": (29.97, 32.55),
    "Fayoum": (29.31, 30.84), "Minya": (28.11, 30.75), "Beni Suef": (29.07, 31.10),
    "Asyut": (27.18, 31.18), "Sohag": (26.56, 31.70),
}
# 5 tertiary hospitals: (bk, name, gov, city, beds, type, weight, lat, lon)
HOSPITALS = [
    ("HSP-CAI-01", "Cairo Central Hospital", "Cairo", "Cairo", 320, "hospital", 0.16, 30.0626, 31.2497),
    ("HSP-CAI-02", "Nile Heart Institute", "Cairo", "Cairo", 180, "hospital", 0.10, 30.0900, 31.3600),
    ("HSP-GIZ-01", "Giza Specialty Hospital", "Giza", "Giza", 240, "hospital", 0.12, 29.9800, 31.1200),
    ("HSP-ALX-01", "Alexandria Bayside Medical", "Alexandria", "Alexandria", 280, "hospital", 0.11, 31.2001, 29.9187),
    ("HSP-MNF-01", "Menoufia Regional Medical", "Menoufia", "Shibin El Kom", 150, "hospital", 0.07, 30.5590, 31.0110),
]
# 20 specialty clinics across the governorates the network serves
CLINIC_GOVS = ["Cairo", "Cairo", "Giza", "Giza", "Alexandria", "Alexandria", "Menoufia", "Sharqia",
               "Dakahlia", "Qalyubia", "Gharbia", "Beheira", "Aswan", "Luxor", "Suez", "Fayoum",
               "Minya", "Beni Suef", "Asyut", "Sohag"]
CLINIC_PREFIX = ["El Nour", "Al Salam", "El Amal", "Dar El Shifa", "El Rahma", "Al Shifa", "El Safwa",
                 "Al Andalus", "El Yasmin", "Al Ezz", "El Mokhtar", "Al Hayah", "El Waha", "Al Razi",
                 "Ibn Sina", "El Shorouk", "Al Manar", "El Firdaus", "Al Nakheel", "El Horreya"]
CLINIC_SPEC = ["Dental", "Pediatric", "Dermatology", "Ophthalmology", "Family Medicine", "Orthopedic",
               "ENT", "Internal Medicine", "Cardiology", "Women's Health"]


def _build_facilities():
    facs = list(HOSPITALS)
    for i, g in enumerate(CLINIC_GOVS, 1):
        lat, lon = GOV_CENTROIDS.get(g, (27.0, 30.5))
        j = (int(hashlib.md5(f"{g}{i}".encode()).hexdigest()[:4], 16) % 100 - 50) / 900.0
        spec = CLINIC_SPEC[(i - 1) % len(CLINIC_SPEC)]
        name = f"{CLINIC_PREFIX[i - 1]} {spec} Clinic"
        facs.append((f"CLN-{g[:3].upper()}-{i:02d}", name, g, g, 0, "clinic",
                     0.018, round(lat + j, 6), round(lon + j, 6)))
    return facs


HOSPITALS = _build_facilities()

# icd10, description, chapter, severity(1-3), band_weights, specialty
DIAGNOSES = [
    ("I10", "Essential hypertension", "Circulatory", 1,
     {"50-64": 4, "65-79": 5, "80+": 4, "35-49": 2}, "Cardiology"),
    ("E11.9", "Type 2 diabetes mellitus", "Endocrine", 2,
     {"50-64": 4, "65-79": 4, "35-49": 3, "80+": 2}, "Endocrinology"),
    ("I25.10", "Atherosclerotic heart disease", "Circulatory", 3,
     {"65-79": 5, "80+": 4, "50-64": 3}, "Cardiology"),
    ("I50.9", "Heart failure, unspecified", "Circulatory", 3,
     {"65-79": 4, "80+": 5, "50-64": 2}, "Cardiology"),
    ("J45.909", "Asthma, unspecified", "Respiratory", 2,
     {"0-17": 5, "18-34": 3, "35-49": 2}, "Pulmonology"),
    ("J18.9", "Pneumonia, unspecified", "Respiratory", 3,
     {"0-17": 3, "65-79": 4, "80+": 5, "50-64": 2}, "Pulmonology"),
    ("N39.0", "Urinary tract infection", "Genitourinary", 1,
     {"18-34": 3, "65-79": 3, "80+": 3, "35-49": 2}, "Internal Medicine"),
    ("N18.3", "Chronic kidney disease, stage 3", "Genitourinary", 3,
     {"65-79": 4, "80+": 4, "50-64": 3}, "Internal Medicine"),
    ("M54.5", "Low back pain", "Musculoskeletal", 1,
     {"35-49": 4, "50-64": 4, "18-34": 3, "65-79": 2}, "Orthopedics"),
    ("S72.0", "Fracture of femur", "Injury", 3,
     {"80+": 5, "65-79": 3, "0-17": 2}, "Orthopedics"),
    ("R07.9", "Chest pain, unspecified", "Symptoms", 2,
     {"50-64": 3, "35-49": 3, "65-79": 3}, "Emergency Medicine"),
    ("F32.9", "Major depressive disorder", "Mental", 2,
     {"18-34": 4, "35-49": 3, "50-64": 2}, "Internal Medicine"),
    ("E78.5", "Hyperlipidemia", "Endocrine", 1,
     {"50-64": 4, "35-49": 3, "65-79": 3}, "Cardiology"),
    ("K35.80", "Acute appendicitis", "Digestive", 3,
     {"0-17": 4, "18-34": 4, "35-49": 2}, "Emergency Medicine"),
    ("O80", "Normal delivery", "Pregnancy", 1,
     {"18-34": 6, "35-49": 2}, "Family Medicine"),
]

# name, is_government, market_share, coverage_lo, coverage_hi, base_denial
PAYERS = [
    ("Health Insurance Org. (HIO)", True, 0.30, 0.75, 0.92, 0.06),
    ("Misr Insurance", False, 0.16, 0.70, 0.90, 0.09),
    ("Allianz Egypt", False, 0.12, 0.72, 0.90, 0.08),
    ("AXA Egypt", False, 0.11, 0.70, 0.88, 0.10),
    ("MetLife Egypt", False, 0.10, 0.68, 0.88, 0.11),
    ("Bupa Global", False, 0.08, 0.80, 0.95, 0.07),
    ("Self-Pay", False, 0.13, 0.0, 0.0, 0.0),
]

# Chronic ICD-10 set used to seed comorbidities (matches Q7's chronic_codes list).
CHRONIC_CODES = {"I10", "E11.9", "E78.5", "N18.3", "I25.10", "J45.909"}

# rxnorm_code, description, (unit_cost_lo, unit_cost_hi) — drug_sk is the 1-based index.
DRUGS = [
    ("860975", "Metformin 500 MG oral tablet", (4, 12)),
    ("314076", "Lisinopril 10 MG oral tablet", (5, 14)),
    ("197361", "Amlodipine 5 MG oral tablet", (5, 15)),
    ("617312", "Atorvastatin 20 MG oral tablet", (8, 22)),
    ("243670", "Aspirin 81 MG oral tablet", (2, 6)),
    ("310429", "Furosemide 40 MG oral tablet", (4, 10)),
    ("745679", "Albuterol 90 MCG/actuation inhaler", (18, 45)),
    ("308182", "Amoxicillin 500 MG oral capsule", (6, 16)),
    ("308460", "Azithromycin 250 MG oral tablet", (10, 26)),
    ("197516", "Ciprofloxacin 500 MG oral tablet", (8, 20)),
    ("312940", "Sertraline 50 MG oral tablet", (7, 18)),
    ("285018", "Insulin glargine 100 UNT/ML pen injector", (40, 95)),
    ("310965", "Ibuprofen 400 MG oral tablet", (3, 9)),
    ("200031", "Carvedilol 12.5 MG oral tablet", (6, 16)),
]

# icd10 -> candidate drug_sk list (1-based into DRUGS), so prescriptions match the diagnosis.
DX_DRUGS = {
    "I10": [2, 3], "E11.9": [1, 12], "I25.10": [4, 5], "I50.9": [6, 14],
    "J45.909": [7], "J18.9": [8, 9], "N39.0": [10], "N18.3": [6],
    "M54.5": [13], "S72.0": [13, 5], "R07.9": [5], "F32.9": [11],
    "E78.5": [4], "K35.80": [8],
}

# cpt_code, description, base_charge_usd — procedure_sk is the 1-based index (small ref set).
PROCEDURES = [
    ("99213", "Office/outpatient visit, established patient", 120.00),
    ("99223", "Initial hospital care, high complexity", 310.00),
    ("93000", "Electrocardiogram, complete", 55.00),
    ("80053", "Comprehensive metabolic panel", 48.00),
    ("71046", "Chest X-ray, 2 views", 85.00),
    ("59400", "Routine obstetric care, vaginal delivery", 2600.00),
]

FIRST_M = ["Mohamed", "Ahmed", "Mahmoud", "Mostafa", "Ali", "Omar", "Youssef", "Khaled",
           "Hassan", "Hussein", "Ibrahim", "Karim", "Tarek", "Amr", "Sherif", "Sayed",
           "Ramy", "Waleed", "Sameh", "Hany", "Ashraf", "Ayman", "Adel", "Nabil"]
FIRST_F = ["Fatma", "Aya", "Mariam", "Nour", "Sara", "Heba", "Rana", "Yasmin", "Mona",
           "Dina", "Salma", "Nada", "Reham", "Amira", "Hoda", "Ghada", "Shaimaa", "Esraa",
           "Doaa", "Passant", "Marwa", "Asmaa", "Rania", "Walaa"]
LAST = ["Hassan", "Ibrahim", "Abdelrahman", "El-Sayed", "Mahmoud", "Ali", "Mohamed", "Fouad",
        "Kamal", "Saad", "Mansour", "Abdallah", "Gaber", "Soliman", "Rashad", "Zaki",
        "Farouk", "Nasr", "Hamed", "Shawky", "Badr", "Ezzat", "Sabry", "Lotfy"]

AGE_BANDS = ["0-17", "18-34", "35-49", "50-64", "65-79", "80+"]
AGE_WEIGHTS = [0.14, 0.26, 0.22, 0.20, 0.13, 0.05]
AGE_DOB_RANGE = {"0-17": (1, 17), "18-34": (18, 34), "35-49": (35, 49),
                 "50-64": (50, 64), "65-79": (65, 79), "80+": (80, 95)}
CREDENTIALS = ["MD", "MBBS", "MD, PhD", "MD, FRCS"]
ANOMALY_KINDS = ["tachycardia", "bradycardia", "hypoxia", "hypertension", "fever"]


def _hash(*p):
    return hashlib.sha256("|".join(str(x) for x in p).encode()).hexdigest()


def _wchoice(pairs):
    items, weights = zip(*pairs)
    return random.choices(items, weights=weights, k=1)[0]


def connect():
    cs = ("DRIVER={ODBC Driver 18 for SQL Server};"
          f"SERVER={os.environ['HCDW_SQL_SERVER']};DATABASE={os.environ['HCDW_SQL_DB']};"
          f"UID={os.environ['HCDW_SQL_USER']};PWD={os.environ['HCDW_SQL_PASSWORD']};"
          "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60")
    return pyodbc.connect(cs, autocommit=False)


def _insert(cur, table, cols, rows):
    if not rows:
        return
    cur.fast_executemany = True
    cur.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=5000)
    ap.add_argument("--providers", type=int, default=80)
    ap.add_argument("--encounters", type=int, default=14000)
    ap.add_argument("--claims", type=int, default=9000)
    ap.add_argument("--vital-minutes", type=int, default=3000)
    ap.add_argument("--vital-devices", type=int, default=40)
    args = ap.parse_args(argv)

    random.seed(SEED)
    now = datetime.now(timezone.utc)
    load_ts = now.replace(tzinfo=None, microsecond=0)

    cn = connect()
    cur = cn.cursor()
    for t in ["fact_vital_signs_minute", "fact_claim", "fact_encounter", "fact_prescription",
              "bridge_encounter_diagnosis", "dim_patient", "dim_provider", "dim_hospital",
              "dim_payer", "dim_diagnosis", "dim_drug", "dim_procedure"]:
        cur.execute(f"DELETE FROM dw.{t}")
    cn.commit()

    # ---- dim_hospital (5 hospitals + 20 clinics, with coordinates) ----
    hosp_rows = [(i, f[0], f[1], f[5], f[3], f[2], f[4], 1, f[7], f[8])
                 for i, f in enumerate(HOSPITALS, 1)]
    _insert(cur, "dw.dim_hospital",
            ["hospital_sk", "hospital_bk", "hospital_name", "facility_type", "city",
             "governorate", "bed_count", "is_active", "lat", "lon"], hosp_rows)
    hosp_pick = [(i, HOSPITALS[i - 1][6]) for i in range(1, len(HOSPITALS) + 1)]
    hosp_gov = {i: (HOSPITALS[i - 1][2], HOSPITALS[i - 1][3]) for i in range(1, len(HOSPITALS) + 1)}
    hosp_is_clinic = {i: (HOSPITALS[i - 1][5] == "clinic") for i in range(1, len(HOSPITALS) + 1)}

    # ---- dim_payer ----
    payer_rows = [(i, i, p[0], 1 if p[1] else 0, 1) for i, p in enumerate(PAYERS, 1)]
    _insert(cur, "dw.dim_payer", ["payer_sk", "payer_bk", "payer_name", "is_government", "is_active"], payer_rows)
    payer_pick = [(i, PAYERS[i - 1][2]) for i in range(1, len(PAYERS) + 1)]
    payer_meta = {i: PAYERS[i - 1] for i in range(1, len(PAYERS) + 1)}

    # ---- dim_diagnosis ----
    dx_rows = [(i, d[0], d[1], d[2]) for i, d in enumerate(DIAGNOSES, 1)]
    _insert(cur, "dw.dim_diagnosis", ["diagnosis_sk", "icd10_code", "description", "chapter"], dx_rows)
    dx_meta = {i: DIAGNOSES[i - 1] for i in range(1, len(DIAGNOSES) + 1)}
    # per-age-band weighted diagnosis picker
    band_dx = {b: [] for b in AGE_BANDS}
    for i, d in enumerate(DIAGNOSES, 1):
        for b in AGE_BANDS:
            band_dx[b].append((i, d[4].get(b, 1)))

    # ---- dim_drug + dim_procedure (reference dims for prescriptions/procedures) ----
    drug_rows = [(i, dr[0], dr[1]) for i, dr in enumerate(DRUGS, 1)]
    _insert(cur, "dw.dim_drug", ["drug_sk", "rxnorm_code", "description"], drug_rows)
    proc_rows = [(i, p[0], p[1], p[2]) for i, p in enumerate(PROCEDURES, 1)]
    _insert(cur, "dw.dim_procedure",
            ["procedure_sk", "cpt_code", "description", "base_charge_usd"], proc_rows)

    # ---- dim_provider (specialty-aware) ----
    specialties = {}
    for d in DIAGNOSES:
        specialties.setdefault(d[5], 0)
    spec_list = list(specialties.keys())
    prov_rows, prov_by_spec = [], {s: [] for s in spec_list}
    for i in range(1, args.providers + 1):
        spec = random.choice(spec_list)
        prov_by_spec[spec].append(i)
        gender_m = random.random() < 0.62
        name = f"Dr. {random.choice(FIRST_M if gender_m else FIRST_F)} {random.choice(LAST)}"
        fac = _wchoice(hosp_pick)
        prov_rows.append((i, f"{random.randint(1000000000, 9999999999)}", name,
                          random.choice(CREDENTIALS), spec, fac,
                          (now + timedelta(days=random.randint(120, 1600))).date(),
                          (now - timedelta(days=random.randint(400, 9000))).date(), 1,
                          load_ts, None, 1, _hash("prov", i)))
    _insert(cur, "dw.dim_provider",
            ["provider_sk", "provider_bk", "full_name", "credential", "specialty",
             "primary_facility_sk", "license_expiry", "hire_date", "is_active",
             "effective_from", "effective_to", "is_current", "record_hash"], prov_rows)
    any_prov = list(range(1, args.providers + 1))

    # ---- dim_patient (Egyptian names, weighted age) ----
    pat_rows, pat_meta = [], {}
    for i in range(1, args.patients + 1):
        band = random.choices(AGE_BANDS, weights=AGE_WEIGHTS, k=1)[0]
        gender = random.choice(["M", "F"])
        fn = random.choice(FIRST_M if gender == "M" else FIRST_F)
        ln = random.choice(LAST)
        lo, hi = AGE_DOB_RANGE[band]
        dob = (now - timedelta(days=random.randint(lo * 365, hi * 365 + 364))).date()
        hsk = _wchoice(hosp_pick)
        gov, city = hosp_gov[hsk]
        pat_meta[i] = (band, hsk)
        pat_rows.append((i, str(uuid.uuid4()), f"MRN{i:07d}", fn, ln, f"{fn} {ln}", dob, band, gender,
                         random.choice(["single", "married", "divorced", "widowed"]),
                         "Egyptian", "Arab", gov, city, 0, load_ts, None, 1, _hash("pat", i)))
    _insert(cur, "dw.dim_patient",
            ["patient_sk", "patient_bk", "mrn", "first_name", "last_name", "full_name",
             "date_of_birth", "age_band", "gender", "marital_status", "race", "ethnicity",
             "governorate", "city", "is_deceased", "effective_from", "effective_to",
             "is_current", "record_hash"], pat_rows)
    cn.commit()

    def dsk(dt):
        return int(dt.strftime("%Y%m%d"))

    # ---- fact_encounter (correlated) ----
    enc_rows, enc_idx = [], {}
    pats = list(pat_meta.keys())
    for i in range(1, args.encounters + 1):
        pat = random.choice(pats)
        band, home_hsk = pat_meta[pat]
        dx = _wchoice(band_dx[band])
        sev = dx_meta[dx][3]
        spec = dx_meta[dx][5]
        prov = random.choice(prov_by_spec.get(spec) or any_prov)
        hsk = home_hsk if random.random() < 0.72 else _wchoice(hosp_pick)
        # class depends on facility type + severity (clinics are outpatient-only)
        if hosp_is_clinic.get(hsk):
            ec = random.choices(["ambulatory", "wellness"], [0.8, 0.2])[0]
        elif dx_meta[dx][0] == "O80":
            ec = "inpatient"
        elif sev >= 3:
            ec = random.choices(["inpatient", "emergency", "ambulatory"], [0.55, 0.30, 0.15])[0]
        elif sev == 2:
            ec = random.choices(["ambulatory", "emergency", "inpatient"], [0.55, 0.25, 0.20])[0]
        else:
            ec = random.choices(["ambulatory", "wellness", "emergency"], [0.72, 0.18, 0.10])[0]
        # seasonality: respiratory skews to cooler months
        day = random.randint(0, 149)
        d = now - timedelta(days=day, seconds=random.randint(0, 86399))
        if dx_meta[dx][2] == "Respiratory" and d.month in (5, 6, 7) and random.random() < 0.5:
            d = now - timedelta(days=random.randint(90, 149))
        los = (None if ec in ("ambulatory", "wellness")
               else round(random.uniform(2, 9), 1) if ec == "emergency"
               else round(random.uniform(24, 72) * sev, 1))
        if ec in ("ambulatory", "wellness"):
            total = round(random.uniform(50, 500) * (1 + 0.25 * sev), 2)
        elif ec == "emergency":
            total = round(random.uniform(400, 3200) * (1 + 0.3 * sev), 2)
        else:
            total = round((los or 24) / 24 * random.uniform(3200, 7800) * (0.8 + 0.2 * sev), 2)
        cover = round(total * random.uniform(0.55, 0.9), 2)
        readmit = 1 if (ec == "inpatient" and sev >= 2 and random.random() < 0.10 + 0.03 * sev) else 0
        enc_rows.append((i, str(uuid.uuid4()), pat, prov, hsk, dx, dsk(d),
                         dsk(d + timedelta(hours=los or 0)), ec, los,
                         round(total * 0.8, 2), total, cover, round(total - cover, 2),
                         1 if ec == "inpatient" else 0, 1 if ec == "emergency" else 0, readmit,
                         random.choice(["routine", "routine", "transfer", "ama", None]), load_ts, load_ts))
        enc_idx[i] = (pat, hsk, dx, d, total)
    _insert(cur, "dw.fact_encounter",
            ["encounter_sk", "encounter_bk", "patient_sk", "provider_sk", "hospital_sk",
             "primary_diagnosis_sk", "start_date_sk", "end_date_sk", "encounter_class",
             "length_of_stay_hours", "base_cost_usd", "total_cost_usd", "payer_coverage_usd",
             "out_of_pocket_usd", "is_inpatient", "is_emergency", "is_readmission_30d",
             "discharge_status", "silver_loaded_at", "gold_loaded_at"], enc_rows)
    cn.commit()

    # ---- fact_claim (payer-specific denial, cost-correlated) ----
    claim_rows, enc_keys = [], list(enc_idx.keys())
    for i in range(1, args.claims + 1):
        enc_sk = random.choice(enc_keys) if random.random() < 0.8 else None
        if enc_sk:
            pat, hsk, dx, d, ecost = enc_idx[enc_sk]
        else:
            pat = random.choice(pats)
            hsk = _wchoice(hosp_pick)
            dx = random.randint(1, len(DIAGNOSES))
            d = now - timedelta(days=random.randint(0, 149), seconds=random.randint(0, 86399))
            ecost = None
        payer = _wchoice(payer_pick)
        pm = payer_meta[payer]
        billed = round((ecost or random.uniform(200, 4000)) * random.uniform(0.9, 1.3), 2)
        if pm[0] == "Self-Pay":
            status = random.choices(["approved", "partially_paid", "pending_review"], [0.7, 0.2, 0.1])[0]
            denial_p = 0.0
        else:
            denial_p = pm[5]
            status = random.choices(["approved", "denied", "partially_paid", "submitted", "pending_review"],
                                    [0.62, denial_p * 1.4, 0.12, 0.10, 0.08])[0]
        if status == "approved":
            allowed = round(billed * random.uniform(pm[3] or 0.8, pm[4] or 0.95), 2)
            paid = allowed
        elif status == "partially_paid":
            allowed = round(billed * random.uniform(0.4, 0.7), 2)
            paid = allowed
        elif status == "denied":
            allowed = paid = 0.0
        else:
            allowed = paid = 0.0
        decided = status in ("approved", "denied", "partially_paid")
        dec = d + timedelta(days=random.randint(3, 28)) if decided else None
        claim_rows.append((i, str(uuid.uuid4()), f"CLM-{d.year}-{i:08d}", enc_sk, pat, None, hsk, payer, dx,
                           dsk(d), dsk(d), dsk(dec) if dec else None,
                           random.randint(3, 28) if decided else None, status,
                           1 if status == "denied" else 0, 1 if (paid == billed and billed > 0) else 0,
                           random.choice([1, 2, 3, 4, 5]), billed, allowed, paid,
                           round(billed - allowed, 2) if status != "approved" else 0.0,
                           round(billed - paid, 2), "EGP", load_ts, load_ts))
    _insert(cur, "dw.fact_claim",
            ["claim_sk", "claim_bk", "claim_number", "encounter_sk", "patient_sk", "provider_sk",
             "hospital_sk", "payer_sk", "primary_diagnosis_sk", "service_date_sk", "submission_date_sk",
             "decision_date_sk", "days_to_decision", "status", "is_denied", "is_paid_in_full",
             "line_count", "billed_amount", "allowed_amount", "paid_amount", "denied_amount",
             "patient_responsibility", "currency", "silver_loaded_at", "gold_loaded_at"], claim_rows)
    cn.commit()

    # ---- fact_vital_signs_minute (baseline; live stream adds fresh rows) ----
    vital_rows, end = [], now.replace(second=0, microsecond=0, tzinfo=None)
    per = max(1, args.vital_minutes // args.vital_devices)
    vsk = 0
    for dev in range(args.vital_devices):
        pat = random.choice(pats)
        hsk = pat_meta[pat][1]
        bed = f"{chr(65 + dev % 5)}-{dev:02d}"
        did = f"DEV-{dev:03d}"
        for _ in range(per):
            vsk += 1
            ts = end - timedelta(minutes=random.randint(0, 1439))
            an = random.random() < 0.05
            vital_rows.append((vsk, pat, hsk, did, bed, ts, dsk(ts), random.randint(50, 60),
                               round(random.gauss(80 if not an else 145, 5), 1), round(random.gauss(85, 5), 1),
                               round(random.gauss(75, 5), 1), round(random.gauss(96 if not an else 86, 1), 1),
                               round(random.gauss(95 if not an else 84, 1), 1),
                               round(random.gauss(120 if not an else 175, 8), 1), round(random.gauss(78, 5), 1),
                               round(random.gauss(16, 1.5), 1), round(random.gauss(36.8 if not an else 39.6, .2), 2),
                               round(random.gauss(36.9 if not an else 39.8, .2), 2),
                               random.randint(1, 12) if an else 0, random.choice(ANOMALY_KINDS) if an else None))
    _insert(cur, "dw.fact_vital_signs_minute",
            ["vital_sk", "patient_sk", "hospital_sk", "device_id", "bed_number", "minute_start_utc",
             "date_sk", "sample_count", "heart_rate_avg", "heart_rate_max", "heart_rate_min", "spo2_avg",
             "spo2_min", "systolic_avg", "diastolic_avg", "respiratory_rate_avg", "temperature_c_avg",
             "temperature_c_max", "anomaly_event_count", "primary_anomaly_kind"], vital_rows)
    cn.commit()

    # ---- bridge_encounter_diagnosis (primary dx + chronic comorbidities for older patients) ----
    # Placed after the facts commit so a failure here can never leave the core warehouse half-loaded.
    sev_label = {1: "mild", 2: "moderate", 3: "severe"}
    chronic_dx_sks = [i for i, d in enumerate(DIAGNOSES, 1) if d[0] in CHRONIC_CODES]
    bridge_rows = []
    for esk, (pat, hsk, dx, d, total) in enc_idx.items():
        bridge_rows.append((esk, dx, 1, sev_label[dx_meta[dx][3]]))
        if pat_meta[pat][0] in ("50-64", "65-79", "80+") and random.random() < 0.5:
            pool = [s for s in chronic_dx_sks if s != dx]
            for ssk in random.sample(pool, k=min(random.randint(1, 2), len(pool))):
                bridge_rows.append((esk, ssk, 0, "moderate"))
    _insert(cur, "dw.bridge_encounter_diagnosis",
            ["encounter_sk", "diagnosis_sk", "is_primary", "severity"], bridge_rows)
    cn.commit()

    # ---- fact_prescription (diagnosis-driven; chronic dx => longer, multi-dispense therapy) ----
    presc_rows, psk = [], 0
    for esk, (pat, hsk, dx, d, total) in enc_idx.items():
        cand = DX_DRUGS.get(dx_meta[dx][0])
        if not cand:
            continue
        for _ in range(random.randint(1, 2)):
            drug_i = random.choice(cand)
            lo, hi = DRUGS[drug_i - 1][2]
            if dx_meta[dx][0] in CHRONIC_CODES:
                dur = random.choice([30, 60, 90])
                disp = dur // 30
            else:
                dur = random.randint(5, 14)
                disp = 1
            psk += 1
            presc_rows.append((psk, esk, pat, drug_i, dsk(d), dsk(d + timedelta(days=dur)),
                               dur, disp, round(random.uniform(lo, hi) * disp, 2)))
    _insert(cur, "dw.fact_prescription",
            ["prescription_sk", "encounter_sk", "patient_sk", "drug_sk", "start_date_sk",
             "stop_date_sk", "therapy_duration_days", "dispenses", "total_cost_usd"], presc_rows)
    cn.commit()

    cur.execute("INSERT INTO dw.load_audit (layer, object_name, rows_written, started_at, finished_at, status) "
                "VALUES (?,?,?,?,?,?)",
                ("gold", "seed_warehouse (realistic)",
                 len(hosp_rows) + len(payer_rows) + len(dx_rows) + len(prov_rows) + len(pat_rows)
                 + len(enc_rows) + len(claim_rows) + len(vital_rows)
                 + len(drug_rows) + len(proc_rows) + len(bridge_rows) + len(presc_rows), load_ts,
                 datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0), "success"))
    cn.commit()
    print("Realistic warehouse seeded:")
    for label, n in [("dim_hospital", len(hosp_rows)), ("dim_payer", len(payer_rows)),
                     ("dim_diagnosis", len(dx_rows)), ("dim_drug", len(drug_rows)),
                     ("dim_provider", len(prov_rows)), ("dim_patient", len(pat_rows)),
                     ("fact_encounter", len(enc_rows)), ("fact_claim", len(claim_rows)),
                     ("bridge_dx", len(bridge_rows)), ("fact_prescription", len(presc_rows)),
                     ("fact_vitals", len(vital_rows))]:
        print(f"  {label:16}: {n:>6}")
    cn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
