#!/usr/bin/env bash
#
# Azure configuration for a Function App: managed identity, Key Vault RBAC,
# secrets, app settings, and restart. Nothing is hardcoded — every value comes
# from env vars (see scripts/sandbox.env.example). Idempotent: safe to re-run.
#
# SCOPE: Key Vault and app settings only. The storage data roles needed by the
# background-job queue and job table are handled separately by
# scripts/grant-storage-roles.sh — a new environment needs BOTH.
#
# Note this script writes secrets, rewrites app settings and restarts the app.
# On a live deployment where you only need the storage grants, prefer the
# narrower grant-storage-roles.sh.
#
# Requires: az CLI, and an account with Owner / User Access Administrator on the
# vault (needed to create the role assignments).
#
# Usage:
#   cp scripts/sandbox.env.example scripts/sandbox.env   # then edit it
#   az login
#   ./scripts/configure-azure-sandbox.sh
#   # or target another environment:
#   ENV_FILE=scripts/prod.env ./scripts/configure-azure-sandbox.sh
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ENV_FILE="${ENV_FILE:-scripts/sandbox.env}"
if [[ -f "$ENV_FILE" ]]; then
  echo ">> Loading $ENV_FILE"
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
else
  echo ">> $ENV_FILE not found — using already-exported environment variables"
fi

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
KV_ROLE="Key Vault Secrets Officer"   # get + list + set (the app writes tokens)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
has_role() {  # has_role <assignee-object-id> <scope> <role>
  az role assignment list --assignee "$1" --scope "$2" \
    --query "[?roleDefinitionName=='${3}'] | length(@)" -o tsv 2>/dev/null \
    | grep -qv '^0$'
}

ensure_role() {  # ensure_role <assignee-object-id> <scope> <role> <label>
  local assignee="$1" scope="$2" role="$3" label="$4"
  if has_role "$assignee" "$scope" "$role"; then
    echo "   $label: already has '$role'"
    return 0
  fi
  echo "   $label: granting '$role'"
  if ! az role assignment create --assignee "$assignee" \
        --role "$role" --scope "$scope" -o none 2>/tmp/rbac_err.$$; then
    echo >&2
    echo "ERROR: could not grant '$role' to $label ($assignee)." >&2
    sed 's/^/   /' /tmp/rbac_err.$$ >&2 || true
    rm -f /tmp/rbac_err.$$
    echo >&2
    echo "Creating role assignments requires Owner or User Access Administrator." >&2
    echo "Ask an Azure admin to run:" >&2
    echo "  az role assignment create --assignee $assignee \\" >&2
    echo "    --role '$role' --scope $scope" >&2
    exit 1
  fi
  rm -f /tmp/rbac_err.$$
}

# ---------------------------------------------------------------------------
# 0. Preflight
# ---------------------------------------------------------------------------
command -v az >/dev/null || { echo "ERROR: az CLI not found." >&2; exit 1; }

if ! az account show -o none 2>/dev/null; then
  echo "ERROR: not signed in. Run 'az login' first." >&2
  exit 1
fi

if [[ -n "${SUBSCRIPTION:-}" ]]; then
  echo ">> Selecting subscription $SUBSCRIPTION"
  az account set --subscription "$SUBSCRIPTION"
fi
echo ">> Subscription: $(az account show --query name -o tsv)"

echo ">> Resolving Key Vault $KEY_VAULT"
VAULT_ID="$(az keyvault show -n "$KEY_VAULT" --query id -o tsv)" || {
  echo "ERROR: vault '$KEY_VAULT' not found. Check KEY_VAULT, or create it:" >&2
  echo "  az keyvault create -g $RG -n $KEY_VAULT -l <location> --enable-rbac-authorization true" >&2
  exit 1
}

if [[ "$(az keyvault show -n "$KEY_VAULT" --query properties.enableRbacAuthorization -o tsv)" != "true" ]]; then
  echo "ERROR: vault '$KEY_VAULT' uses access policies, not RBAC." >&2
  echo "Grant access with: az keyvault set-policy -n $KEY_VAULT --object-id <id> --secret-permissions get set" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 1. Grant the caller data-plane access (management-plane Owner does NOT include it)
# ---------------------------------------------------------------------------
echo ">> Ensuring the signed-in caller can write secrets"
if CALLER_OID="$(az ad signed-in-user show --query id -o tsv 2>/dev/null)" && [[ -n "$CALLER_OID" ]]; then
  ensure_role "$CALLER_OID" "$VAULT_ID" "$KV_ROLE" "caller"
else
  echo "   (not a user account — skipping self-grant; the wait below will verify access)"
fi

# ---------------------------------------------------------------------------
# 2. Wait for RBAC propagation, proving the data plane actually works
# ---------------------------------------------------------------------------
echo ">> Waiting for Key Vault data-plane access (RBAC propagation)"
for attempt in $(seq 1 15); do
  if az keyvault secret set --vault-name "$KEY_VAULT" \
       --name "rbac-preflight" --value ok -o none 2>/dev/null; then
    az keyvault secret delete --vault-name "$KEY_VAULT" --name "rbac-preflight" -o none 2>/dev/null || true
    echo "   data plane OK (after ${attempt} attempt(s))"
    break
  fi
  if [[ "$attempt" -eq 15 ]]; then
    echo "ERROR: still cannot write secrets to $KEY_VAULT after ~5 minutes." >&2
    echo "Confirm the role assignment landed:" >&2
    echo "  az role assignment list --scope $VAULT_ID -o table" >&2
    exit 1
  fi
  echo "   not ready yet (attempt ${attempt}/15) — retrying in 20s"
  sleep 20
done

# ---------------------------------------------------------------------------
# 3. Managed identity + its vault access (what the app uses at runtime)
# ---------------------------------------------------------------------------
echo ">> Ensuring system-assigned managed identity on $FUNCTION_APP"
PRINCIPAL_ID="$(az functionapp identity assign -g "$RG" -n "$FUNCTION_APP" \
  --query principalId -o tsv)"
[[ -n "$PRINCIPAL_ID" ]] || { echo "ERROR: could not enable managed identity." >&2; exit 1; }
echo "   principalId=$PRINCIPAL_ID"

echo ">> Ensuring the managed identity can read/write vault secrets"
ensure_role "$PRINCIPAL_ID" "$VAULT_ID" "$KV_ROLE" "managed identity"

# ---------------------------------------------------------------------------
# 4. Secrets + app settings
# ---------------------------------------------------------------------------
echo ">> Storing the Zoho client secret in Key Vault"
az keyvault secret set --vault-name "$KEY_VAULT" \
  --name "zoho-client-secret" --value "$ZOHO_CLIENT_SECRET" -o none

echo ">> Setting app settings (secret via Key Vault reference, rest as plain values)"
# Deliberately NOT set: FUNCTIONS_WORKER_RUNTIME and AzureWebJobsStorage. Flex
# Consumption manages those itself (runtime lives in functionAppConfig, storage is
# already identity-based via AzureWebJobsStorage__*), and setting them is rejected.
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

# ---------------------------------------------------------------------------
# 4b. Clear any stale OAuth token bundle.
# The stored bundle's refresh token is bound to the PREVIOUS ZOHO_CLIENT_ID, so
# after a credential swap it can no longer be refreshed (Zoho returns
# invalid_client) — leaving it in place would just serve a dead token until it
# expires. Deleting it forces the fresh /login below, which writes a new bundle.
# NOTE: this runs on every invocation, so re-running the script always requires
# re-consenting via /login afterwards, even for unrelated changes.
# ---------------------------------------------------------------------------
echo ">> Clearing any existing '${ZOHO_TOKENS_SECRET_NAME}' bundle (forces a fresh /login)"
if az keyvault secret show --vault-name "$KEY_VAULT" \
     --name "$ZOHO_TOKENS_SECRET_NAME" -o none 2>/dev/null; then
  az keyvault secret delete --vault-name "$KEY_VAULT" \
    --name "$ZOHO_TOKENS_SECRET_NAME" -o none
  # Soft-delete leaves a recoverable secret of the same name, which blocks the
  # next /login from re-creating it (409 Conflict). Purge it when the vault has
  # soft-delete enabled so the name is free again.
  if [[ "$(az keyvault show -n "$KEY_VAULT" \
             --query properties.enableSoftDelete -o tsv 2>/dev/null)" == "true" ]]; then
    echo "   purging the soft-deleted secret"
    az keyvault secret purge --vault-name "$KEY_VAULT" \
      --name "$ZOHO_TOKENS_SECRET_NAME" -o none 2>/dev/null \
      || echo "   (purge skipped — purge protection may require manual cleanup)"
  fi
  echo "   cleared — re-consent via /login (see below)"
else
  echo "   none found — nothing to clear"
fi

# ---------------------------------------------------------------------------
# 5. Restart (KEY_VAULT_URI is read at module import — needs a fresh process)
# ---------------------------------------------------------------------------
echo ">> Restarting the Function App"
az functionapp restart -g "$RG" -n "$FUNCTION_APP" -o none

APP_HOST="$(az functionapp show -g "$RG" -n "$FUNCTION_APP" --query defaultHostName -o tsv)"

echo ">> Verifying /health (may take a few seconds to warm up)"
for attempt in $(seq 1 10); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' "https://${APP_HOST}/health" || true)"
  if [[ "$CODE" == "200" ]]; then
    echo "   /health -> 200 OK"
    break
  fi
  [[ "$attempt" -eq 10 ]] && echo "   WARNING: /health returned $CODE — check Application Insights"
  sleep 6
done

cat <<EOF

============================================================
Done. Next (one-time):

  1. Complete the Zoho OAuth consent:
       https://${APP_HOST}/login

     Ensure this exact redirect URI is registered in the Zoho API console:
       ${ZOHO_REDIRECT_URI}

  2. Confirm the app wrote the token bundle to Key Vault:
       az keyvault secret show --vault-name ${KEY_VAULT} \\
         --name ${ZOHO_TOKENS_SECRET_NAME} --query id

  3. For background jobs, grant the storage data roles (separate script):
       ./scripts/grant-storage-roles.sh
============================================================
EOF
