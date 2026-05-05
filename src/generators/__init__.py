"""Synthetic data generators for the healthcare warehouse.

Three modules are exposed:

* `generate_claims` - one-shot batch JSONL writer (~200K claims).
* `simulate_vitals` - long-running stream of IoT vital sign events.
* `provider_api`   - Flask service that imitates an external provider registry.

`common.py` holds shared reference data (ICD-10, CPT, hospital network, etc.)
and the seeded RNG helpers.
"""
