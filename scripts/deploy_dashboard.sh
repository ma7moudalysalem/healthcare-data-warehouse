#!/usr/bin/env bash
# Deploy / redeploy the Streamlit clinical-ops dashboard to Azure Container Apps.
#
# WHY this shape:
#   * The full medallion warehouse (Synapse dedicated pool + Databricks) is NOT
#     cost-viable on an "Azure for Students" subscription. The deliverable that
#     ships is the Streamlit dashboard (a free stand-in for Power BI), running in
#     demo mode off bundled Parquet fixtures — no cloud data backend required.
#   * ACR Tasks (server-side `az acr build`) are BLOCKED on student subscriptions
#     ("TasksOperationsNotAllowed"), so the image is built LOCALLY with Docker and
#     pushed to ACR. Docker Desktop must be running.
#
# Prereqs: az cli logged in (`az login`), Docker Desktop running.
# Usage:   bash scripts/deploy_dashboard.sh
set -euo pipefail

RG="${RG:-rg-healthcare-dw}"
LOC="${LOC:-westeurope}"
ACR="${ACR:-hcdwacr44ba4327}"          # must be globally unique, lowercase alnum
ENVN="${ENVN:-hcdw-env}"
APP="${APP:-hcdw-dashboard}"
TAG="${TAG:-v1}"
IMG="${ACR}.azurecr.io/healthcare-dashboard:${TAG}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo ">> [1/6] resource group"
az group create -n "$RG" -l "$LOC" -o none

echo ">> [2/6] container registry (Basic, admin enabled)"
az acr show -g "$RG" -n "$ACR" -o none 2>/dev/null \
  || az acr create -g "$RG" -n "$ACR" --sku Basic --admin-enabled true -o none

echo ">> [3/6] build image locally + push (ACR Tasks are blocked on student subs)"
az acr login -n "$ACR"
docker build -f docker/Dockerfile.dashboard -t "$IMG" .
docker push "$IMG"

echo ">> [4/6] container apps environment"
az containerapp env show -g "$RG" -n "$ENVN" -o none 2>/dev/null \
  || az containerapp env create -g "$RG" -n "$ENVN" -l "$LOC" --logs-destination none -o none

echo ">> [5/6] create or update the app"
ACR_USER="$(az acr credential show -n "$ACR" --query username -o tsv)"
ACR_PASS="$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv)"
if az containerapp show -g "$RG" -n "$APP" -o none 2>/dev/null; then
  az containerapp registry set -g "$RG" -n "$APP" \
    --server "${ACR}.azurecr.io" --username "$ACR_USER" --password "$ACR_PASS" -o none
  az containerapp update -g "$RG" -n "$APP" --image "$IMG" -o none
else
  az containerapp create -g "$RG" -n "$APP" --environment "$ENVN" \
    --image "$IMG" \
    --registry-server "${ACR}.azurecr.io" \
    --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --target-port 8501 --ingress external \
    --cpu 0.5 --memory 1.0Gi --min-replicas 0 --max-replicas 1 \
    --env-vars HCDW_DEMO_MODE=1 -o none
fi

echo ">> [6/6] done. public URL:"
echo "https://$(az containerapp show -g "$RG" -n "$APP" --query 'properties.configuration.ingress.fqdn' -o tsv)"
