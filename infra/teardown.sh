#!/usr/bin/env bash
# Delete every Azure resource that setup.sh created. The resource group itself stays.
set -euo pipefail
cd "$(dirname "$0")"
source ./demo.env

az account set --subscription "$SUBSCRIPTION_ID"
rg_id=$(az group show -n "$RESOURCE_GROUP" --query id -o tsv)

echo "Resources tagged $TAG in $RESOURCE_GROUP:"
az resource list -g "$RESOURCE_GROUP" --query "[?tags.${TAG%%=*}=='${TAG#*=}'].{name:name, type:type}" -o table
read -r -p "Delete them and the budget? Type yes: " answer
[[ "$answer" == "yes" ]] || { echo "Nothing deleted."; exit 1; }

# Deleting the Foundry resource deletes its projects, agents and model deployment.
if az cognitiveservices account show -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  for project in "$PROD_PROJECT" "$DEV_PROJECT"; do
    az cognitiveservices account project delete -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" --project-name "$project" -o none || true
  done
  az cognitiveservices account delete -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP"
fi
# A deleted Foundry resource stays soft-deleted for 48 hours and keeps its name. Purge it.
az cognitiveservices account purge -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" -l "$LOCATION" 2>/dev/null || true

az identity delete -n "$IDENTITY_NAME" -g "$RESOURCE_GROUP" 2>/dev/null || true
az rest --method DELETE \
  --url "https://management.azure.com${rg_id}/providers/Microsoft.Consumption/budgets/${BUDGET_NAME}?api-version=2024-08-01" 2>/dev/null || true

echo "Left in $RESOURCE_GROUP with tag $TAG:"
az resource list -g "$RESOURCE_GROUP" --query "[?tags.${TAG%%=*}=='${TAG#*=}'].{name:name, type:type}" -o table
