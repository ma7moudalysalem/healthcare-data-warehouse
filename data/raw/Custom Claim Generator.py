import pandas as pd
import numpy as np
from faker import Faker
import random

fake = Faker()

# Load encounters from Synthea

encounters = pd.read_csv(r"E:\Medical_Healthcare_Project\output\csv\encounters.csv")
encounters["START"] = pd.to_datetime(encounters["START"])

print("Total encounters:", len(encounters))

# ترتيب الزيارات لكل مريضً
encounters = encounters.sort_values(["PATIENT", "START"])


# Configurations

DENIAL_RATE = 0.18

PAYER_DISTRIBUTION = {
    "Private Insurance": 0.50,
    "Medicare": 0.25,
    "Medicaid": 0.20,
    "Self-Pay": 0.05
}

APPROVED_TO_PAID_RATE = 0.85
DENIED_TO_APPEAL_RATE = 0.30
BASE_COST_RANGE = (100, 5000)

DENIAL_REASONS = [
    "Missing documentation",
    "Service not covered",
    "Invalid coding",
    "Duplicate claim",
    "Eligibility expired"
]


# Helper functions

def choose_payer():
    return random.choices(
        list(PAYER_DISTRIBUTION.keys()),
        weights=list(PAYER_DISTRIBUTION.values())
    )[0]

def generate_amount():
    return round(np.random.uniform(*BASE_COST_RANGE), 2)

def determine_claim_status():
    if random.random() < DENIAL_RATE:
        if random.random() < DENIED_TO_APPEAL_RATE:
            return "appealed"
        return "denied"
    else:
        if random.random() < APPROVED_TO_PAID_RATE:
            return "paid"
        return "approved"


# Generate claims
# (زيارة مدفوعة + متابعة بدون فاتورة)

claims = []

for patient_id, patient_visits in encounters.groupby("PATIENT"):

    visits = patient_visits.sort_values("START").reset_index(drop=True)

    # زيارة مدفوعة فقط (كل زيارة أولى من كل زيارتين)
    paid_visits = visits.iloc[::2]

    for _, visit in paid_visits.iterrows():

        amount_billed = generate_amount()
        status = determine_claim_status()

        if status == "paid":
            amount_paid = amount_billed
            denial_reason = None
        elif status in ["approved"]:
            amount_paid = 0
            denial_reason = None
        else:
            amount_paid = 0
            denial_reason = random.choice(DENIAL_REASONS)

        claims.append({
            "claim_id": str(fake.uuid4()),
            "patient_id": str(visit["PATIENT"]),   # من encounters
            "encounter_id": str(visit["Id"]),      # من encounters
            "payer_name": choose_payer(),
            "amount_billed": amount_billed,
            "amount_paid": amount_paid,
            "status": status,
            "denial_reason": denial_reason
        })

claims_df = pd.DataFrame(claims)


# Save JSON

claims_df.to_json(
    "claims.json",
    orient="records",
    indent=2
)


# Quality checks

print("\nClaims created:", len(claims_df))
print("\nStatus distribution:")
print(claims_df["status"].value_counts(normalize=True))
print("\nActual denial rate:", round((claims_df["status"] == "denied").mean(), 3))