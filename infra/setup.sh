#!/usr/bin/env bash
# Create the Azure resources and the GitHub settings for the demo. Safe to run again.
# Needs: az signed in with Owner on the resource group, gh signed in as the repository owner.
set -euo pipefail
cd "$(dirname "$0")"
source ./demo.env
tag_key=${TAG%%=*}
tag_value=${TAG#*=}

az account set --subscription "$SUBSCRIPTION_ID"
tenant_id=$(az account show --query tenantId -o tsv)
rg_id=$(az group show -n "$RESOURCE_GROUP" --query id -o tsv)

echo "== Foundry resource and projects"
if ! az cognitiveservices account show -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  az cognitiveservices account create -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" -l "$LOCATION" \
    --kind AIServices --sku S0 --custom-domain "$ACCOUNT_NAME" --allow-project-management \
    --assign-identity --tags "$TAG" --yes -o none
fi
account_id=$(az cognitiveservices account show -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" --query id -o tsv)

for project in "$PROD_PROJECT" "$DEV_PROJECT"; do
  if ! az cognitiveservices account project show -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" --project-name "$project" -o none 2>/dev/null; then
    az cognitiveservices account project create -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" -l "$LOCATION" \
      --project-name "$project" --assign-identity -o none
  fi
done

echo "== Model deployment"
if ! az cognitiveservices account deployment show -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" --deployment-name "$MODEL_DEPLOYMENT" -o none 2>/dev/null; then
  az cognitiveservices account deployment create -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" \
    --deployment-name "$MODEL_DEPLOYMENT" --model-name "$MODEL_NAME" --model-version "$MODEL_VERSION" \
    --model-format OpenAI --sku-name GlobalStandard --sku-capacity "$MODEL_CAPACITY" -o none
fi

echo "== Pipeline identity with federated credentials for two GitHub environments"
if ! az identity show -n "$IDENTITY_NAME" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  az identity create -n "$IDENTITY_NAME" -g "$RESOURCE_GROUP" -l "$LOCATION" --tags "$TAG" -o none
fi
client_id=$(az identity show -n "$IDENTITY_NAME" -g "$RESOURCE_GROUP" --query clientId -o tsv)
principal_id=$(az identity show -n "$IDENTITY_NAME" -g "$RESOURCE_GROUP" --query principalId -o tsv)

# GitHub repositories created after 15 July 2026 use the immutable subject repo:OWNER@ID/REPO@ID:...
owner_id=$(gh api "repos/$GITHUB_REPO" --jq .owner.id)
repo_id=$(gh api "repos/$GITHUB_REPO" --jq .id)
subject_prefix="repo:${GITHUB_REPO%%/*}@${owner_id}/${GITHUB_REPO##*/}@${repo_id}"
for environment in evaluation production; do
  az identity federated-credential create -n "github-$environment" --identity-name "$IDENTITY_NAME" -g "$RESOURCE_GROUP" \
    --issuer https://token.actions.githubusercontent.com --subject "$subject_prefix:environment:$environment" \
    --audiences api://AzureADTokenExchange -o none
done

echo "== Role assignments"
foundry_user="Foundry User"
assign() { # principal, principal type, role, scope
  az role assignment create --assignee-object-id "$1" --assignee-principal-type "$2" --role "$3" --scope "$4" -o none
}
prod_scope="$account_id/projects/$PROD_PROJECT"
dev_scope="$account_id/projects/$DEV_PROJECT"
assign "$principal_id" ServicePrincipal "$foundry_user" "$prod_scope"
assign "$principal_id" ServicePrincipal "$foundry_user" "$dev_scope"
me=$(az ad signed-in-user show --query id -o tsv)
assign "$me" User "$foundry_user" "$prod_scope"
assign "$me" User "$foundry_user" "$dev_scope"
for project in "$PROD_PROJECT" "$DEV_PROJECT"; do
  project_principal=$(az cognitiveservices account project show -n "$ACCOUNT_NAME" -g "$RESOURCE_GROUP" \
    --project-name "$project" --query identity.principalId -o tsv)
  assign "$project_principal" ServicePrincipal "$foundry_user" "$account_id"
done

echo "== Budget alert on the resources tagged $TAG"
start_date=$(date -u +%Y-%m-01)
az rest --method PUT \
  --url "https://management.azure.com${rg_id}/providers/Microsoft.Consumption/budgets/${BUDGET_NAME}?api-version=2024-08-01" \
  --body "$(jq -n --arg amount "$BUDGET_AMOUNT" --arg start "${start_date}T00:00:00Z" --arg key "$tag_key" --arg value "$tag_value" '{
    properties: {
      category: "Cost", amount: ($amount | tonumber), timeGrain: "Monthly",
      timePeriod: {startDate: $start, endDate: "2027-12-31T00:00:00Z"},
      filter: {tags: {name: $key, operator: "In", values: [$value]}},
      notifications: {
        actual50: {enabled: true, operator: "GreaterThanOrEqualTo", threshold: 50, contactRoles: ["Owner"], thresholdType: "Actual"},
        actual90: {enabled: true, operator: "GreaterThanOrEqualTo", threshold: 90, contactRoles: ["Owner"], thresholdType: "Actual"},
        forecast100: {enabled: true, operator: "GreaterThanOrEqualTo", threshold: 100, contactRoles: ["Owner"], thresholdType: "Forecasted"}
      }
    }}')" -o none

echo "== GitHub environments, secrets and variables"
gh api -X PUT "repos/$GITHUB_REPO/environments/evaluation" --silent
gh api -X PUT "repos/$GITHUB_REPO/environments/production" --input - --silent <<'JSON'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
gh api -X POST "repos/$GITHUB_REPO/environments/production/deployment-branch-policies" \
  -f name=main -f type=branch --silent 2>/dev/null || true
# Identifiers, not credentials. They are stored as secrets only so that the public logs mask them.
gh secret set AZURE_CLIENT_ID -R "$GITHUB_REPO" -b "$client_id"
gh secret set AZURE_TENANT_ID -R "$GITHUB_REPO" -b "$tenant_id"
gh secret set AZURE_SUBSCRIPTION_ID -R "$GITHUB_REPO" -b "$SUBSCRIPTION_ID"
gh variable set FOUNDRY_PROJECT_ENDPOINT -R "$GITHUB_REPO" -b "https://${ACCOUNT_NAME}.services.ai.azure.com/api/projects/${PROD_PROJECT}"
gh variable set FOUNDRY_DEV_PROJECT_ENDPOINT -R "$GITHUB_REPO" -b "https://${ACCOUNT_NAME}.services.ai.azure.com/api/projects/${DEV_PROJECT}"
gh variable set MODEL_DEPLOYMENT_NAME -R "$GITHUB_REPO" -b "$MODEL_DEPLOYMENT"

echo "Done. Production project endpoint: https://${ACCOUNT_NAME}.services.ai.azure.com/api/projects/${PROD_PROJECT}"
