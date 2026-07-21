#!/usr/bin/env bash
#
# Grant the Function App's managed identity the storage data roles needed by the
# background-job queue and job table.
#
# Deliberately narrow: it only creates role assignments. It does NOT write secrets,
# change app settings, or restart the app — so it cannot disturb a working
# deployment. Idempotent; safe to re-run.
#
# SCOPE: storage data roles only. Key Vault access and app settings are handled
# separately by scripts/configure-azure-sandbox.sh — a new environment needs BOTH.
#
# Usage:
#   az login
#   ./scripts/grant-storage-roles.sh
#   # or:
#   ENV_FILE=scripts/prod.env ./scripts/grant-storage-roles.sh
#   # or with no env file at all:
#   RG=rg-... FUNCTION_APP=... ./scripts/grant-storage-roles.sh
#
set -euo pipefail

ENV_FILE="${ENV_FILE:-scripts/sandbox.env}"
if [[ -f "$ENV_FILE" ]]; then
  echo ">> Loading $ENV_FILE"
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

# Only these two are needed — no Zoho/Power Automate values required.
: "${RG:?set RG}"
: "${FUNCTION_APP:?set FUNCTION_APP}"

STORAGE_ROLES=(
  "Storage Queue Data Contributor"   # queue trigger + enqueue
  "Storage Table Data Contributor"   # durable job records
  "Storage Blob Data Contributor"    # host state + deployment package
)

ensure_role() {  # ensure_role <assignee> <scope> <role> <label>
  local assignee="$1" scope="$2" role="$3" label="$4"
  if az role assignment list --assignee "$assignee" --scope "$scope" \
       --query "[?roleDefinitionName=='${role}'] | length(@)" -o tsv 2>/dev/null \
       | grep -qv '^0$'; then
    echo "   already has '$role'"
    return 0
  fi
  echo "   granting '$role'"
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

command -v az >/dev/null || { echo "ERROR: az CLI not found." >&2; exit 1; }
az account show -o none 2>/dev/null || { echo "ERROR: not signed in. Run 'az login'." >&2; exit 1; }
[[ -n "${SUBSCRIPTION:-}" ]] && az account set --subscription "$SUBSCRIPTION"

echo ">> Reading the managed identity of $FUNCTION_APP"
PRINCIPAL_ID="$(az functionapp identity show -g "$RG" -n "$FUNCTION_APP" \
  --query principalId -o tsv 2>/dev/null || true)"
if [[ -z "$PRINCIPAL_ID" || "$PRINCIPAL_ID" == "None" ]]; then
  echo "ERROR: no system-assigned managed identity on $FUNCTION_APP." >&2
  echo "Enable it with: az functionapp identity assign -g $RG -n $FUNCTION_APP" >&2
  exit 1
fi
echo "   principalId=$PRINCIPAL_ID"

echo ">> Resolving the storage account from AzureWebJobsStorage__blobServiceUri"
BLOB_URI="$(az functionapp config appsettings list -g "$RG" -n "$FUNCTION_APP" \
  --query "[?name=='AzureWebJobsStorage__blobServiceUri'].value | [0]" -o tsv)"
if [[ -z "$BLOB_URI" || "$BLOB_URI" == "None" ]]; then
  echo "ERROR: AzureWebJobsStorage__blobServiceUri not set on $FUNCTION_APP." >&2
  exit 1
fi
STORAGE_ACCOUNT="$(sed -E 's#^https://([^.]+)\..*#\1#' <<<"$BLOB_URI")"
STORAGE_ID="$(az storage account show -n "$STORAGE_ACCOUNT" --query id -o tsv)"
echo "   storage account: $STORAGE_ACCOUNT"

for role in "${STORAGE_ROLES[@]}"; do
  ensure_role "$PRINCIPAL_ID" "$STORAGE_ID" "$role" "managed identity"
done

cat <<EOF

============================================================
Storage roles are in place. Nothing else was changed —
no secrets written, no app settings touched, no restart.

RBAC can take a few minutes to propagate. Verify with:
  az role assignment list --assignee $PRINCIPAL_ID \\
    --scope $STORAGE_ID -o table

Then push the code to deploy the queue trigger.
============================================================
EOF
