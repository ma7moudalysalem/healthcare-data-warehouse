import pandas as pd
import numpy as np
import random
import time
from datetime import datetime
from faker import Faker
import json

fake = Faker()


# Load patients

patients = pd.read_csv(r"E:\Medical_Healthcare_Project\output\csv\patients.csv")
patient_ids = patients["Id"].astype(str).tolist()

print("Streaming started...")
print("Press CTRL+C to stop\n")


# Configurations

STREAM_DELAY = 1        # ثانية بين كل batch
BATCH_SIZE = 20         # عدد القراءات في كل ثانية
ANOMALY_RATE = 0.05


# Generators

def generate_device_id(patient_id):
    return f"DEV-{patient_id[:8]}-{random.randint(1,3)}"

def generate_normal_vitals():
    heart_rate = random.randint(60, 100)
    systolic = int(np.random.normal(120, 5))
    diastolic = int(np.random.normal(80, 5))
    temperature = round(np.random.uniform(36.5, 37.5), 1)
    spo2 = random.randint(95, 100)
    return heart_rate, systolic, diastolic, temperature, spo2

def generate_anomaly_vitals():
    heart_rate = random.randint(110, 140)
    systolic = random.randint(85, 100)
    diastolic = random.randint(55, 70)
    temperature = round(np.random.uniform(38, 39.5), 1)
    spo2 = random.randint(88, 94)
    return heart_rate, systolic, diastolic, temperature, spo2

# Continuous Streaming Loop

with open("vital_signs_stream.json", "a") as f:

    while True:
        batch = []

        for _ in range(BATCH_SIZE):
            patient_id = random.choice(patient_ids)
            device_id = generate_device_id(patient_id)

            if random.random() < ANOMALY_RATE:
                hr, sys, dia, temp, spo2 = generate_anomaly_vitals()
            else:
                hr, sys, dia, temp, spo2 = generate_normal_vitals()

            record = {
                "device_id": device_id,
                "patient_id": patient_id,
                "heart_rate": hr,
                "systolic_bp": sys,
                "diastolic_bp": dia,
                "temperature": temp,
                "spo2": spo2,
                "timestamp": datetime.utcnow().isoformat()
            }

            batch.append(record)

        #  streaming JSON lines
        for r in batch:
            f.write(json.dumps(r) + "\n")

        print(f"Generated {BATCH_SIZE} records at {datetime.now()}")

        time.sleep(STREAM_DELAY)