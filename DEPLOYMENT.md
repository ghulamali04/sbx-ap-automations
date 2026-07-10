# Deployment

How the programme ships, and — the main question this doc answers — **how the two environments are managed**.

## 1. The two-environment model at a glance

```
                 merge to main
  developer  ─────────────────────►  SANDBOX  (auto-deploy, no gate)
                                         │
                                         │  manual approval (sign-off)
                                         ▼
                                    PRODUCTION  (same artifact, promoted)
```

Two rules govern everything below:

1. **Build and test against sandbox.** Nothing reaches production without explicit sign-off.
2. **Build once, promote the same artifact.** Production deploys the *exact package* that passed in sandbox — it is never rebuilt for prod. This is what makes "tested in sandbox" mean anything.

## 2. What "two environments" actually is

Not deployment slots. Slots are **not reliably available on Flex Consumption**, and the programme's model is two genuinely separate environments with a sign-off gate — so each environment is its own set of Azure resources in its own resource group.

| Resource | Sandbox | Production |
|----------|---------|-----------|
| Resource group | `rg-ap-automations-sbx` | `rg-ap-automations-prod` |
| Function App (Flex, Linux, Python, Australia East) | `func-ap-automations-sbx` | `func-ap-automations-prod` |
| Deployment storage account (Flex requires a blob container for the package) | `stapautomationssbx` | `stapautomationsprod` |
| Key Vault | `kv-ap-automations-sbx` | `kv-ap-automations-prod` |
| Application Insights | `appi-...-sbx` | `appi-...-prod` |

The two Function Apps never share anything. A bad sandbox deploy cannot touch production because they are different resources in different resource groups.

> Provision these with IaC (Bicep/Terraform in `infra/`) parameterised by environment, so the two stay identical except for names and secrets. Manual portal setup drifts — don't.

## 3. Configuration & secrets

Config lives in **app settings**, which differ per environment. **No secrets in the repo, ever.**

- All secrets live in that environment's **Key Vault**, referenced from app settings by name using Key Vault references:
  ```
  ZOHO_CLIENT_SECRET = @Microsoft.KeyVault(SecretUri=https://kv-ap-automations-prod.vault.azure.net/secrets/zoho-client-secret/)
  ```
- The Function App reads Key Vault via its **managed identity** (no secret needed to fetch secrets). Grant each app's identity `get`/`list` on secrets in **its own** Key Vault only.
- **Developers never see production credentials.** They have access to the sandbox Key Vault; the production Key Vault is restricted to the deploy identity plus whoever holds the sign-off.
- Non-secret, environment-varying config (CORS allowlist, log level, API base URLs) is plain app settings, set per environment by IaC.

## 4. CI/CD with GitHub Environments

GitHub's **Environments** feature provides the sign-off gate directly — this is the mechanism, not a bolt-on.

Create two GitHub Environments in repo settings:

- **`sandbox`** — no protection rules. Deploys automatically.
- **`production`** — **Required reviewers** = the sign-off holder (and optionally a second approver). Optionally restrict deployments to the `main` branch. A production deploy then *pauses* until that person clicks approve in the GitHub UI, which is exactly the sign-off gate the programme requires.

Each Environment holds its own secrets (the federated-credential / publish info for its Function App), so a workflow job scoped to `production` physically cannot use sandbox credentials and vice-versa.

**Prefer OIDC over publish profiles:** configure `azure/login` with a federated credential per environment (workload-identity federation) so there are no long-lived deploy secrets stored in GitHub at all.

### 4.1 `deploy-functions.yml` (backend)

Path-filtered so it only runs on backend changes. Build once, then two environment-scoped deploy jobs — `production` depends on `sandbox` and carries the `environment: production` gate.

```yaml
name: deploy-functions
on:
  push:
    branches: [main]
    paths: ['backend/**', 'contracts/**']
  workflow_dispatch:

permissions:
  id-token: write        # for OIDC azure/login
  contents: read

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - name: Install into a clean target dir
        run: |
          cd backend
          pip install -r requirements.txt --target=".python_packages/lib/site-packages"
      - name: Package
        run: |
          cd backend
          zip -r ../functionapp.zip . -x '*.venv*'
      - uses: actions/upload-artifact@v4
        with: { name: functionapp, path: functionapp.zip }   # build ONCE, reuse below

  deploy-sandbox:
    needs: build
    runs-on: ubuntu-latest
    environment: sandbox
    steps:
      - uses: actions/download-artifact@v4
        with: { name: functionapp }
      - uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      - uses: Azure/functions-action@v1
        with:
          app-name: func-ap-automations-sbx
          package: functionapp.zip

  deploy-production:
    needs: deploy-sandbox          # promote only after sandbox succeeds
    runs-on: ubuntu-latest
    environment: production        # ← this line is the sign-off gate
    steps:
      - uses: actions/download-artifact@v4
        with: { name: functionapp }   # SAME artifact, not a rebuild
      - uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      - uses: Azure/functions-action@v1
        with:
          app-name: func-ap-automations-prod
          package: functionapp.zip
```

The `environment: production` line is doing the important work: GitHub pauses that job and notifies the required reviewer; it proceeds only on approval. That is the sign-off, enforced by the platform rather than by convention.

### 4.2 `lint-test.yml` (PR gate)

Runs `ruff`/`flake8` + `pytest` on every PR, and fails if `contracts/openapi.json` is stale:

```yaml
name: lint-test
on: { pull_request: { paths: ['backend/**', 'contracts/**'] } }
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r backend/requirements.txt ruff pytest
      - run: ruff check backend
      - run: pytest backend/tests
      - name: Contract is up to date
        run: |
          python backend/scripts/export_openapi.py
          git diff --exit-code contracts/openapi.json \
            || (echo "openapi.json is stale — run export_openapi.py and commit" && exit 1)
```

### 4.3 `deploy-web.yml` (frontend — later)

Added only when `frontend/` is real. Path-filtered on `frontend/**` so it never fires on backend changes, and uses the same two-environment / approval pattern. Target is SWA or App Service per [ARCHITECTURE.md](./ARCHITECTURE.md) §7.

## 5. Flex Consumption deploy specifics

- Flex pulls the deployment package from a **blob storage container**; the app setting `DEPLOYMENT_STORAGE_CONNECTION_STRING` (or a managed-identity-based deployment config) points at it. `Azure/functions-action@v1` handles the upload — just make sure the storage account exists and is wired before the first deploy.
- **Prove the pipeline first.** Before any real automation, get a minimal `function_app.py` (ASGI mount + one placeholder timer trigger) deploying cleanly to **sandbox** on Flex. That validates plan, region, storage, identity, and Key Vault wiring in one shot.
- Free-grant math on Flex differs from classic Consumption (lower included executions/GB) — irrelevant for this workload's volume, but don't be surprised comparing invoices.

## 6. Promotion checklist (per release to production)

1. PR merged to `main`; `lint-test` green.
2. `deploy-sandbox` succeeded; the automation verified against sandbox systems.
3. Reviewer approves the paused `deploy-production` job in GitHub.
4. `deploy-production` ships the **same artifact** that ran in sandbox.
5. Confirm via Application Insights that the production app is healthy.

## 7. Access summary

| | Sandbox | Production |
|--|---------|-----------|
| Deploy | automatic on merge to `main` | manual approval (required reviewer) |
| Function App / Key Vault access | developers | deploy identity + sign-off holder only |
| Credentials visible to developers | sandbox only | none |

> If a separate access-control document already exists for the GitHub org and Azure subscriptions, treat it as authoritative and keep this table as a summary only.