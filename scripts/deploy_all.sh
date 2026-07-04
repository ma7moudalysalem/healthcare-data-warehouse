#!/usr/bin/env bash
# Provision + deploy the FULL stack on Azure (student-subscription friendly):
#   Azure SQL (warehouse) + schema/views + seed  →  dashboard + provider API on
#   Azure Container Apps.
#
# Prereqs:
#   * az login
#   * Docker Desktop running  (ACR Tasks are blocked on student subs → local build)
#   * a Python env with pyodbc + the repo deps (for apply_sql.py / seed_warehouse.py)
#   * export HCDW_SQL_PASSWORD='...'   (the Azure SQL admin password)
#
# Usage:  HCDW_SQL_PASSWORD='Your#Strong0Pass' bash scripts/deploy_all.sh
set -euo pipefail

RG="${RG:-rg-healthcare-dw}"
LOC="${LOC:-westeurope}"
SQL_LOC="${SQL_LOC:-northeurope}"          # westeurope frequently blocks new SQL servers
ACR="${ACR:-hcdwacr44ba4327}"
ENVN="${ENVN:-hcdw-env}"
SQL_SERVER="${SQL_SERVER:-hcdw-sqlne-44ba4327}"
SQL_DB="${SQL_DB:-healthcare}"
SQL_ADMIN="${SQL_ADMIN:-hcdwadmin}"
PY="${PY:-python}"
: "${HCDW_SQL_PASSWORD:?export HCDW_SQL_PASSWORD with the Azure SQL admin password}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$REPO_ROOT"
DASH_IMG="${ACR}.azurecr.io/healthcare-dashboard:db1"
API_IMG="${ACR}.azurecr.io/healthcare-provider-api:v1"

echo ">> [1/9] resource group + providers"
az group create -n "$RG" -l "$LOC" -o none
for p in Microsoft.App Microsoft.ContainerRegistry Microsoft.OperationalInsights Microsoft.Sql; do
  az provider register --namespace "$p" --wait -o none || true
done

echo ">> [2/9] container registry"
az acr show -g "$RG" -n "$ACR" -o none 2>/dev/null \
  || az acr create -g "$RG" -n "$ACR" --sku Basic --admin-enabled true -o none

echo ">> [3/9] Azure SQL server + firewall + db"
az sql server show -g "$RG" -n "$SQL_SERVER" -o none 2>/dev/null \
  || az sql server create -g "$RG" -n "$SQL_SERVER" -l "$SQL_LOC" \
        --admin-user "$SQL_ADMIN" --admin-password "$HCDW_SQL_PASSWORD" -o none
az sql server firewall-rule create -g "$RG" -s "$SQL_SERVER" -n AllowAzureServices \
  --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 -o none 2>/dev/null || true
MYIP="$(curl -s https://api.ipify.org || echo 0.0.0.0)"
az sql server firewall-rule create -g "$RG" -s "$SQL_SERVER" -n MyClientIP \
  --start-ip-address "$MYIP" --end-ip-address "$MYIP" -o none 2>/dev/null || true
az sql db show -g "$RG" -s "$SQL_SERVER" -n "$SQL_DB" -o none 2>/dev/null \
  || az sql db create -g "$RG" -s "$SQL_SERVER" -n "$SQL_DB" --edition Basic \
        --backup-storage-redundancy Local -o none

echo ">> [4/9] apply warehouse schema + views, then seed the star schema"
export HCDW_SQL_SERVER="${SQL_SERVER}.database.windows.net"
export HCDW_SQL_DB="$SQL_DB" HCDW_SQL_USER="$SQL_ADMIN"
"$PY" scripts/apply_sql.py sql/ddl/azuresql/warehouse_azuresql.sql
"$PY" -m pipelines.gold.seed_warehouse --patients 2000 --encounters 6000 --claims 4000 --vital-minutes 6000

echo ">> [5/9] build + push images (local Docker)"
az acr login -n "$ACR"
docker build -f docker/Dockerfile.dashboard-db   -t "$DASH_IMG" .
docker build -f docker/Dockerfile.provider-api   -t "$API_IMG"  .
docker push "$DASH_IMG"
docker push "$API_IMG"

echo ">> [6/9] container apps environment"
az containerapp env show -g "$RG" -n "$ENVN" -o none 2>/dev/null \
  || az containerapp env create -g "$RG" -n "$ENVN" -l "$LOC" --logs-destination none -o none

ACR_USER="$(az acr credential show -n "$ACR" --query username -o tsv)"
ACR_PASS="$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv)"

echo ">> [7/9] dashboard app (live on Azure SQL)"
if az containerapp show -g "$RG" -n hcdw-dashboard -o none 2>/dev/null; then
  az containerapp secret set -g "$RG" -n hcdw-dashboard --secrets sqlpass="$HCDW_SQL_PASSWORD" -o none
  az containerapp update -g "$RG" -n hcdw-dashboard --image "$DASH_IMG" -o none
else
  az containerapp create -g "$RG" -n hcdw-dashboard --environment "$ENVN" --image "$DASH_IMG" \
    --registry-server "${ACR}.azurecr.io" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --target-port 8501 --ingress external --cpu 0.5 --memory 1.0Gi --min-replicas 0 --max-replicas 1 \
    --secrets sqlpass="$HCDW_SQL_PASSWORD" \
    --env-vars SYNAPSE_SERVER="$HCDW_SQL_SERVER" SYNAPSE_DATABASE="$SQL_DB" \
               SYNAPSE_USER="$SQL_ADMIN" SYNAPSE_PASSWORD=secretref:sqlpass \
               SYNAPSE_AUTH_METHOD=sql HCDW_DEMO_MODE=0 -o none
fi

echo ">> [8/9] provider API app"
if az containerapp show -g "$RG" -n hcdw-provider-api -o none 2>/dev/null; then
  az containerapp update -g "$RG" -n hcdw-provider-api --image "$API_IMG" -o none
else
  az containerapp create -g "$RG" -n hcdw-provider-api --environment "$ENVN" --image "$API_IMG" \
    --registry-server "${ACR}.azurecr.io" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --target-port 5000 --ingress external --cpu 0.25 --memory 0.5Gi --min-replicas 0 --max-replicas 1 -o none
fi

echo ">> [9/9] done"
echo "dashboard : https://$(az containerapp show -g "$RG" -n hcdw-dashboard    --query 'properties.configuration.ingress.fqdn' -o tsv)"
echo "provider  : https://$(az containerapp show -g "$RG" -n hcdw-provider-api --query 'properties.configuration.ingress.fqdn' -o tsv)"
