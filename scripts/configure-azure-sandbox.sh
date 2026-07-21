#!/usr/bin/env bash
#
# Configure a Function App's settings + Key Vault wiring from the environment.
# Nothing is hardcoded here — every value comes from env vars (see
# scripts/sandbox.env.example). Idempotent; safe to re-run. Requires: az login.
#
# Usage:
#   cp scripts/sandbox.env.example scripts/sandbox.env   # then edit it
#   ./scripts/configure-azure-sandbox.sh                 # sources scripts/sandbox.env
#   # or point at another file / rely on already-exported vars:
#   ENV_FILE=scripts/prod.env ./scripts/configure-azure-sandbox.sh
#
set -euo pipefail

# Load an env file if present (default scripts/sandbox.env). Already-exported
# vars still work if the file is absent.
ENV_FILE="${ENV_FILE:-scripts/sandbox.env}"
if [[ -f "$ENV_FILE" ]]; then
  echo ">> Loading $ENV_FILE"
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

# Require every value from the environment — fail early with a clear message.
: "${RG:?set RG (see scripts/sandbox.env.example)}"
: "${FUNCTION_APP:?set FUNCTION_APP}"
: "${KEY_VAULT:?set KEY_VAULT}"
: "${ZOHO_PORTAL_ID:?set ZOHO_PORTAL_ID}"
: "${ZOHO_CLIENT_ID:?set ZOHO_CLIENT_ID}"
: "${ZOHO_CLIENT_SECRET:?set ZOHO_CLIENT_SECRET}"
: "${ZOHO_ACCOUNTS_URL:?set ZOHO_ACCOUNTS_URL}"
: "${ZOHO_REDIRECT_URI:?set ZOHO_REDIRECT_URI}"
: "${POWER_AUTOMATE_WEBHOOK_URL:?set POWER_AUTOMATE_WEBHOOK_URL}"
: "${POWER_AUTOMATE_ALLOWED_HOSTS:?set POWER_AUTOMATE_ALLOWED_HOSTS}"
: "${CORS_ALLOW_ORIGINS:?set CORS_ALLOW_ORIGINS}"
: "${ZOHO_TOKENS_SECRET_NAME:=zoho-tokens}"

VAULT_URI="https://${KEY_VAULT}.vault.azure.net/"

echo ">> Ensuring system-assigned managed identity on $FUNCTION_APP"
PRINCIPAL_ID="$(az functionapp identity assign -g "$RG" -n "$FUNCTION_APP" \
  --query principalId -o tsv)"
echo "   principalId=$PRINCIPAL_ID"

VAULT_ID="$(az keyvault show -n "$KEY_VAULT" --query id -o tsv)"

echo ">> Granting the identity Key Vault access (RBAC vault)"
# Secrets Officer = get/list/set. The app READS the Zoho client secret via a
# reference AND WRITES the rotating '${ZOHO_TOKENS_SECRET_NAME}' bundle, so it
# needs set, not just get. For tighter prod least-privilege, scope Officer to the
# token secret only and grant Secrets User (read) at the vault for references.
az role assignment create --assignee "$PRINCIPAL_ID" \
  --role "Key Vault Secrets Officer" --scope "$VAULT_ID" 2>/dev/null || \
  echo "   (already assigned, or vault uses access policies — see README note)"

echo ">> Storing the Zoho client secret in Key Vault"
az keyvault secret set --vault-name "$KEY_VAULT" \
  --name "zoho-client-secret" --value "$ZOHO_CLIENT_SECRET" -o none

echo ">> Setting app settings (secret via Key Vault reference, rest as plain values)"
az functionapp config appsettings set -g "$RG" -n "$FUNCTION_APP" --settings \
  "ZOHO_PORTAL_ID=${ZOHO_PORTAL_ID}" \
  "ZOHO_CLIENT_ID=${ZOHO_CLIENT_ID}" \
  "ZOHO_CLIENT_SECRET=@Microsoft.KeyVault(SecretUri=${VAULT_URI}secrets/zoho-client-secret/)" \
  "ZOHO_REDIRECT_URI=${ZOHO_REDIRECT_URI}" \
  "ZOHO_ACCOUNTS_URL=${ZOHO_ACCOUNTS_URL}" \
  "POWER_AUTOMATE_WEBHOOK_URL=${POWER_AUTOMATE_WEBHOOK_URL}" \
  "POWER_AUTOMATE_ALLOWED_HOSTS=${POWER_AUTOMATE_ALLOWED_HOSTS}" \
  "CORS_ALLOW_ORIGINS=${CORS_ALLOW_ORIGINS}" \
  "KEY_VAULT_URI=${VAULT_URI}" \
  "ZOHO_TOKENS_SECRET_NAME=${ZOHO_TOKENS_SECRET_NAME}" \
  -o none

APP_HOST="$(az functionapp show -g "$RG" -n "$FUNCTION_APP" --query defaultHostName -o tsv)"
echo ">> Done. Restart to pick up changes:"
echo "   az functionapp restart -g $RG -n $FUNCTION_APP"
echo
echo "Then complete the one-time OAuth: https://${APP_HOST}/login"
echo "(ensure ${ZOHO_REDIRECT_URI} is registered in the Zoho API console)."
