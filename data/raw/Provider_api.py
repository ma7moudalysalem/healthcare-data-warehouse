from flask import Flask, jsonify, request
from faker import Faker
import uuid
import random
import json
import os

app = Flask(__name__)
fake = Faker()

DATA_FILE = "providers.json"


# Generate providers dataset

SPECIALTIES = [
    "Cardiology",
    "Neurology",
    "Orthopedics",
    "Pediatrics",
    "Dermatology",
    "General Medicine"
]

def generate_providers(n=200):
    providers = []
    for _ in range(n):
        providers.append({
            "provider_id": str(uuid.uuid4()),
            "name": fake.name(),
            "specialty": random.choice(SPECIALTIES),
            "hospital": fake.company(),
            "years_experience": random.randint(1, 35)
        })
    return providers

def load_providers():
    if not os.path.exists(DATA_FILE):
        data = generate_providers()
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return data
    else:
        with open(DATA_FILE) as f:
            return json.load(f)

providers = load_providers()


# Endpoints

@app.route("/")
def home():
    return {
        "message": "Provider API is running",
        "endpoints": [
            "/providers",
            "/providers/<id>",
            "/providers?specialty=Cardiology"
        ]
    }

# GET /providers
# GET /providers?specialty=Cardiology
@app.route("/providers", methods=["GET"])
def get_providers():
    specialty = request.args.get("specialty")

    if specialty:
        filtered = [
            p for p in providers
            if p["specialty"].lower() == specialty.lower()
        ]
        return jsonify(filtered)

    return jsonify(providers)


# GET /providers/<id>
@app.route("/providers/<provider_id>", methods=["GET"])
def get_provider_by_id(provider_id):
    for provider in providers:
        if provider["provider_id"] == provider_id:
            return jsonify(provider)

    return jsonify({"error": "Provider not found"}), 404



# Run server

if __name__ == "__main__":
    app.run(debug=True, port=5000)