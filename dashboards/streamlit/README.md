# Streamlit dashboard

Three pages mirroring the Power BI report:

1. **Hospital Operations** - encounter volume, length-of-stay, 30d
   readmission rate, ED throughput, top diagnoses.
2. **Revenue & Claims** - billed/paid trend, denial rate by payer,
   collection rate, claim status mix.
3. **Live Vital Signs** - last-24h minute aggregates, active alerts,
   patient drill-down. Auto-refreshes every 60s when wired to Synapse.

## Run locally

```bash
pip install -r requirements.txt streamlit-autorefresh

# Option A: connect to Synapse
export SYNAPSE_SERVER=...
export SYNAPSE_DATABASE=...
export SYNAPSE_USER=...
export SYNAPSE_PASSWORD=...
streamlit run dashboards/streamlit/app.py

# Option B: demo mode (no Synapse needed)
python dashboards/streamlit/build_demo_data.py
HCDW_DEMO_MODE=1 streamlit run dashboards/streamlit/app.py
```

The demo dataset is regenerated from a fixed seed, so screenshots taken on
different machines line up.

## Deploy

Containerised via `docker/Dockerfile.streamlit` (built from
`docker/docker-compose.yml`). For Azure, push the image to ACR and deploy
to App Service for Containers with managed identity, then grant the MI
`db_datareader` on the Synapse database.
