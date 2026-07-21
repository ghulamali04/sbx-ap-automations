# Deployment

How the programme ships, and the main question this doc answers: how the two environments are managed.

Sections 1–4 are the design. **Section 5 is the runbook** — the scripts, settings and commands you actually run to set up or repair an environment. Section 6 lists the Flex Consumption traps that have already bitten us, with the fix for each.

## 1. The branch-per-environment model at a glance

```
  feature branch
       │  PR + review
       ▼
   staging  ─────────────────►  SANDBOX     (auto-deploy on push to staging)
       │
       │  PR from staging to main, reviewed and merged
       ▼
     main   ─────────────────►  PRODUCTION  (auto-deploy on push to main)
```

The branch a change lands on decides where it deploys. `staging` drives the sandbox environment, `main` drives production, and promotion is a reviewed merge from `staging` into `main`.

**Nobody pushes to `staging` or `main` directly — everything arrives by pull request.** That needs no special deploy trigger: merging a PR *is* a push to the target branch, and that push is what deploys. The PR itself runs the same build as a gate, so a package that cannot build never reaches the merge button (section 4.2).

Two rules govern everything below:

1. **Test on staging against sandbox first.** Nothing reaches production without having run in sandbox off the `staging` branch.
2. **Production only ever receives source that passed in sandbox.** The merge from `staging` to `main` carries the exact tree that ran in sandbox, so the production build reproduces what sandbox ran.

> **Outstanding:** rule 2 assumes dependencies are pinned. `backend/requirements.txt` is currently **unpinned**, so two builds of the same source can resolve different versions — which is how an unrelated `azure-functions` 2.x upgrade broke routing (section 6). Pin from a known-good `pip freeze` before the first production release.

> Note on build-once. An earlier design promoted a single built artifact through an approval gate so production received byte-identical bytes. The branch model trades that strict guarantee for a simpler flow: `main` rebuilds its own package rather than reusing the sandbox one. If strict byte-for-byte promotion ever matters more, publish the staging build as a release asset and have the `main` job pull that instead of rebuilding.

## 2. What "two environments" actually is

Not deployment slots. Slots are **not supported on Flex Consumption**, and the programme's model is two genuinely separate environments anyway, so each environment is its own set of Azure resources in its own resource group.

| Resource | Sandbox (provisioned) | Production (not yet provisioned) |
|----------|-----------------------|----------------------------------|
| Resource group | `rg-ap-automations-sbx` | `rg-ap-automations-prod` |
| Function App (Flex, Linux, **Python 3.14**, Australia East) | `advisory-partners-automations-sbx` | `advisory-partners-automations-prod` |
| Deployment storage account | derived from `AzureWebJobsStorage__blobServiceUri` | — |
| Key Vault (RBAC-enabled) | `kv-ap-automations-sbx` | `kv-ap-automations-prod` |
| Application Insights | `appi-...-sbx` | `appi-...-prod` |

The two Function Apps never share anything. A bad sandbox deploy cannot touch production because they are different resources in different resource groups, reached from different branches by different deploy identities.

> Provision these with IaC (Bicep/Terraform in `infra/`) parameterised by environment. The sandbox was built by hand; the scripts in section 5 capture the configuration half of that so production can be set up identically without repeating the archaeology.

## 3. Configuration and secrets

Config lives in **app settings**, which differ per environment. **No secrets in the repo, ever.**

- Secrets live in that environment's **Key Vault**, referenced from app settings:
  ```
  ZOHO_CLIENT_SECRET = @Microsoft.KeyVault(SecretUri=https://kv-ap-automations-sbx.vault.azure.net/secrets/zoho-client-secret/)
  ```
  The reference is deliberately **unversioned** (trailing `/`), so rotating the secret takes effect without touching app settings.
- The Function App reads Key Vault via its **managed identity**.
- Non-secret, environment-varying config (CORS allowlist, API base URLs) is plain app settings.

Two identities, do not confuse them:

- The **app's managed identity** runs at runtime and reads Key Vault, deployment storage, and the queue/table the automations use.
- The **GitHub deploy identity** (section 4.0) is a separate Entra app registration used only by CI to push the package. It never reads your app secrets.

### 3.1 App settings the code actually reads

Required — set by `scripts/configure-azure-sandbox.sh`:

| Setting | Notes |
|---|---|
| `ZOHO_PORTAL_ID` | |
| `ZOHO_CLIENT_ID` | |
| `ZOHO_CLIENT_SECRET` | Key Vault reference |
| `ZOHO_REDIRECT_URI` | must be `https://<host>/callback` **and** registered in the Zoho API console |
| `ZOHO_ACCOUNTS_URL` | |
| `POWER_AUTOMATE_WEBHOOK_URL` | the `sig=` makes the whole URL sensitive |
| `POWER_AUTOMATE_ALLOWED_HOSTS` | |
| `CORS_ALLOW_ORIGINS` | comma-separated |
| `KEY_VAULT_URI` | switches the token store to Key Vault; **read at module import, so a restart is required** |
| `ZOHO_TOKENS_SECRET_NAME` | defaults to `zoho-tokens` |

Optional, with sensible defaults in code: `COMPLETION_GROUP_BY`, `ZOHO_PROJECTS_API_BASE`, `REPORT_QUEUE_NAME` (`report-jobs`), `REPORT_JOBS_TABLE` (`reportjobs`).

### 3.2 Settings you must NOT set on Flex

Flex manages these itself and **rejects them — one bad key fails the entire save**, which reads like "I can't save app settings":

`FUNCTIONS_WORKER_RUNTIME` · `FUNCTIONS_EXTENSION_VERSION` · `AzureWebJobsStorage` (plain connection string) · `WEBSITE_RUN_FROM_PACKAGE` · `WEBSITE_CONTENTAZUREFILECONNECTIONSTRING`

The runtime stack lives in `functionAppConfig.runtime`; storage is already identity-based via the `AzureWebJobsStorage__*` settings set at provisioning. `local.settings.json` legitimately contains `FUNCTIONS_WORKER_RUNTIME` and `AzureWebJobsStorage=UseDevelopmentStorage=true` — those are **local-only** and must never be copied into Azure.

### 3.3 Token storage

Tokens must not live on the Function App filesystem: Flex mounts the package **read-only** and scales across ephemeral instances, so a local token file cannot even be written (`OSError: [Errno 30] Read-only file system`).

`backend/api/automations/zoho/token_store.py` therefore persists the **whole token bundle** (access + refresh + expiry) as a single Key Vault secret, with an in-process cache so the hot path doesn't make a vault call per request. It falls back to a local JSON file when `KEY_VAULT_URI` is unset, keeping `func start` / uvicorn working unchanged.

Because the app **writes** that secret on every refresh, its managed identity needs `set`, not just `get`/`list` — hence **Key Vault Secrets Officer**, not Secrets User.

### 3.4 Required role assignments

| Principal | Scope | Role | Why |
|---|---|---|---|
| Function App managed identity | Key Vault | **Key Vault Secrets Officer** | reads `zoho-client-secret`; reads *and writes* `zoho-tokens` |
| Function App managed identity | Storage account | **Storage Blob Data Contributor** | host state + deployment package |
| Function App managed identity | Storage account | **Storage Queue Data Contributor** | background-job queue |
| Function App managed identity | Storage account | **Storage Table Data Contributor** | durable job records |
| The operator (you) | Key Vault | **Key Vault Secrets Officer** | to seed secrets |

> On an RBAC-enabled vault, **management-plane roles grant no data-plane access**. Subscription Owner can create the vault but cannot read or write a secret in it until granted one of the above. Creating role assignments additionally requires Owner or User Access Administrator.

## 4. CI/CD with GitHub Actions

GitHub **Environments** hold the per-environment deploy credentials. The branch a push lands on selects which environment job runs.

### 4.0 The deploy identity (OIDC, no stored secrets)

Each environment gets its own Entra app registration, federated to only that environment's GitHub subject. **Provision the environment's resources first** (section 2), because the role assignment is scoped to a resource group that must already exist.

```bash
az ad app create --display-name "gh-deploy-ap-automations-sbx"
APP_ID=$(az ad app list --display-name "gh-deploy-ap-automations-sbx" --query "[0].appId" -o tsv)
az ad sp create --id $APP_ID

# Only the 'sandbox' environment of this repo can exchange its OIDC token for this identity
az ad app federated-credential create --id $APP_ID --parameters '{
  "name": "gh-sandbox",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:YOUR_ORG/YOUR_REPO:environment:sandbox",
  "audiences": ["api://AzureADTokenExchange"]
}'

# Deploy rights on the sandbox resource group only
SUB=$(az account show --query id -o tsv)
az role assignment create --assignee $APP_ID \
  --role "Website Contributor" \
  --scope /subscriptions/$SUB/resourceGroups/rg-ap-automations-sbx
```

This creates a deploy identity and its permissions. It does **not** create the Function App or any runtime resource.

### 4.1 GitHub Environments

- **`sandbox`** — deployment branch restricted to `staging`. Holds `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID`.
- **`production`** — deployment branch restricted to `main`. Holds the production identity's three values. Optionally add a **Required reviewer**.

GitHub secrets are available to the **workflow**, not to the running app. There is no pipe from a GitHub secret into `os.getenv` in Azure — app config must reach the Function App's app settings (section 5).

### 4.2 `deploy-functions.yml` (backend)

Path-filtered to backend changes, zipping from **inside** `backend` so `host.json` and `function_app.py` sit at the zip root (the classic monorepo mistake is zipping the folder itself, which buries the host one level too deep and deploys an empty app).

**Triggers, matching the PR-only workflow:**

| Event | `build` | `deploy-sandbox` | `deploy-production` |
|---|---|---|---|
| PR → `staging` or `main` | ✅ validation gate | ❌ | ❌ |
| push to `staging` (a merged PR) | ✅ | ✅ | ❌ |
| push to `main` (a merged PR) | ✅ | ❌ | ✅ |
| `workflow_dispatch` | ✅ | on `staging` | on `main` |

Both deploy jobs are guarded with `github.event_name != 'pull_request'`, so a PR can never deploy — it only proves the build. The artifact that deploys is produced by the exact steps that passed on the PR.

The `build` job runs two checks that turn post-deploy mysteries into pre-merge failures:

- **`Verify the function app indexes`** imports `function_app.py` and asserts `get_functions()` is non-empty. An import error or an unindexable trigger otherwise surfaces only as a dead host after deploy.
- **`Verify host.json is at the zip root`** asserts `host.json` and `function_app.py` are at the root of the package.

```yaml
env:
  PYTHON_VERSION: '3.14'   # MUST match the Function App's runtime — see below
```

Two Flex-specific parameters carry the weight: `sku: flexconsumption` selects the Flex deploy path (omit it and the action can quietly take a non-Flex path), and `remote-build: false` ships the deps built in the `build` job rather than rebuilding on the server.

> **The CI Python version must equal the Function App's runtime version.** The app runs Python **3.14**; CI originally built on 3.11. Compiled wheels are interpreter-specific, so the cp311 `pydantic_core` binary was invisible to the cp314 interpreter and the worker died with `ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'`. If you change one, change the other in the same commit. Confirm the runtime with:
> ```bash
> az functionapp show -g rg-ap-automations-sbx -n advisory-partners-automations-sbx \
>   --query "functionAppConfig.runtime"
> ```

### 4.3 `lint-test.yml` (PR gate) — **not yet implemented**

Planned: `ruff` plus `pytest` on every PR into `staging` or `main`, failing if `contracts/openapi.json` is stale. It does not exist yet, and two prerequisites are missing — there is no `backend/tests/` directory and no ruff configuration, so the workflow as originally drafted would fail on every PR.

Until it lands, the PR gate is the `build` job in section 4.2, which catches dependency and import failures but **not** lint or test regressions. Keep any future `python-version` aligned with section 4.2.

### 4.4 `deploy-web.yml` (frontend, later)

Added only when `frontend/` is real. Path-filtered on `frontend/**`, same branch-per-environment OIDC pattern. Target is SWA or App Service per [ARCHITECTURE.md](./ARCHITECTURE.md) section 7.

## 5. Environment setup runbook

Two scripts, deliberately **separate** so each has a predictable blast radius. A new environment needs **both**.

| Script | Does | Never touches |
|---|---|---|
| `scripts/configure-azure-sandbox.sh` | managed identity, Key Vault RBAC, `zoho-client-secret`, the 10 app settings, restart, `/health` check | storage roles |
| `scripts/grant-storage-roles.sh` | Storage Blob/Queue/Table Data Contributor | secrets, app settings, restart |

Because `configure-azure-sandbox.sh` rewrites secrets and restarts the app, prefer `grant-storage-roles.sh` when a live deployment only needs the storage grants.

### 5.1 Prerequisites

- `az` CLI, signed in: `az login`
- Owner or User Access Administrator on the resource group (needed to create role assignments)

### 5.2 Configure the environment

All values come from an env file — **nothing is hardcoded in the scripts**:

```bash
cp scripts/sandbox.env.example scripts/sandbox.env   # gitignored; holds real values
# edit scripts/sandbox.env
./scripts/configure-azure-sandbox.sh
```

The script is idempotent and self-verifying. It will:

1. Verify sign-in; confirm the vault exists and is RBAC-enabled.
2. Resolve your object ID and grant you **Key Vault Secrets Officer**.
3. **Poll until the data plane actually works** (up to 15 × 20s) so RBAC propagation can't fail it mid-run.
4. Enable the system-assigned identity and grant it **Key Vault Secrets Officer**.
5. Store `zoho-client-secret`; set the 10 app settings (secret as a Key Vault reference).
6. Restart the app and poll `/health` until 200.

Target another environment with `ENV_FILE=scripts/prod.env ./scripts/configure-azure-sandbox.sh`.

### 5.3 Grant storage roles (required for background jobs)

```bash
./scripts/grant-storage-roles.sh
```

Derives the storage account from the existing `AzureWebJobsStorage__blobServiceUri` setting, so there is nothing extra to configure. Only needs `RG` and `FUNCTION_APP`.

> **Grant these before deploying a queue trigger.** If the trigger binds while the identity lacks Queue access, the host can fail to start *every* trigger, taking the HTTP endpoints down with it. Allow ~3–5 minutes for RBAC propagation before pushing.

### 5.4 One-time Zoho OAuth

Register `https://<host>/callback` in the Zoho API console, then visit `https://<host>/login` and complete consent. Confirm the app persisted the bundle:

```bash
az keyvault secret show --vault-name kv-ap-automations-sbx --name zoho-tokens --query id
```

An id here proves the whole chain: managed identity → Key Vault write → durable tokens across restarts and scale-out.

### 5.5 Verification

```bash
# health
curl -s https://<host>/health

# effective auth level (must be 'anonymous' — see section 6)
az functionapp function show -g rg-ap-automations-sbx -n advisory-partners-automations-sbx \
  --function-name http_app_func --query "config.bindings[0].authLevel"

# background job round trip: expect 202 + a Location header, then poll it
curl -s -X POST https://<host>/reports/completion \
  -H 'content-type: application/json' -d '{"dry_run": true}' -i | head -20

# role assignments
az role assignment list --assignee <principalId> -o table
```

### 5.6 Where to look when something breaks

Application Insights → **Logs**:

```kusto
exceptions
| where timestamp > ago(30m)
| order by timestamp desc
| project timestamp, type, outerMessage, innermostMessage, details
```

Also useful: Function App → **Log stream** (live), and **Diagnose and solve problems** → "Functions that are not triggering" for host-level boot failures.

## 6. Flex Consumption specifics (and the traps already hit)

- **Monorepo zip root.** The package must have `host.json` and `function_app.py` at its root, which is why the workflow zips from inside `backend`. Verify with `unzip -l functionapp.zip | head` if a deploy comes up empty.
- **Identity-based storage needs data roles, or nothing boots.** With `AzureWebJobsStorage__credential=managedidentity`, the host cannot start without Blob/Queue/Table roles on the identity, and every request returns **"Function host is not running"**. This is the first thing to check on that error.
- **CI Python must match the runtime Python.** See section 4.2 — mismatched compiled wheels fail at import, not at build.
- **`routePrefix` must be `""` for the ASGI app.** With the default `api` prefix, `AsgiFunctionApp` builds the invalid template `api//{*route}` and the host fails with *"The route template separator character '/' cannot appear consecutively"* ([azure-functions-python-worker#1310](https://github.com/Azure/azure-functions-python-worker/issues/1310)). `host.json` sets `routePrefix: ""`, so routes are served at the root: `/health`, not `/api/health`.
- **`AuthLevel.ANONYMOUS` is mandatory, not a convenience.** Azure Functions reads its function key from `?code=`, and OAuth2 returns its authorization code as `?code=`. With `AuthLevel.FUNCTION`, Zoho's redirect to `/callback?code=<oauth-code>` is rejected as an invalid function key with **401 before FastAPI ever runs**. The `x-functions-key` header is no escape — a browser redirect cannot set headers. Since `AsgiFunctionApp` is a single catch-all, this makes **every** route public; real authorization must live inside FastAPI or an upstream gateway.
- **The filesystem is read-only.** Anything that must persist goes to Key Vault, Blob, or Table (section 3.3).
- **A queue trigger with an unresolvable connection stops all triggers.** The host boots into an error state and processes nothing, not just that queue. Set the connection and its roles before deploying the trigger.
- **Blob triggers need the Event Grid source on Flex.** Wire SharePoint or blob-upload automations as Event Grid blob triggers, not the classic polling trigger, or they never fire.
- **No deployment slots on Flex.** For zero-downtime concerns, see Flex's site-update strategies rather than reaching for slots.

## 7. Background jobs

The completion-overview report can outrun both Power Automate's 120s cap and Azure's 230s HTTP cap, so `POST /reports/completion` returns **202 + a `Location` header** and the caller polls until `completed`/`failed`.

That contract is served by a real queue, because in-process background work cannot survive Flex:

```
POST /reports/completion ──► job record (Table Storage)
                         └─► message (Queue Storage)
                                   │
                                   ▼
                     process_report_job (queue trigger)
                                   │
                                   ▼
                     job record updated ──► GET /reports/completion/{job_id}
```

- `jobs.py` — durable job store (Table Storage; in-memory fallback locally)
- `queue.py` — enqueue + worker entry point (Queue Storage; asyncio fallback locally)
- `function_app.py` — the `process_report_job` queue trigger alongside the ASGI app

Two failure modes this fixes: once the 202 response is written the host may freeze or scale in the instance, killing an `asyncio` background task mid-report; and with the old in-memory store the status poll could land on a different instance and 404.

Queue behaviour is tuned in `host.json` (`batchSize: 2` to bound matplotlib memory, `maxDequeueCount: 3`). Job failures are **recorded, not retried** — re-raising would re-run an expensive report that will fail again. Change that in `queue.run_job` if transient retries become worth the cost.

Local development needs no storage account: with the `AzureWebJobsStorage__*` settings absent, both modules fall back to in-process behaviour.

## 8. Promotion checklist (per release to production)

1. Change merged to `staging`; `lint-test` green on the PR.
2. `deploy-functions` deployed to sandbox off `staging`; the automation verified against sandbox systems.
3. PR opened from `staging` to `main`, reviewed (branch protection on `main` requires the review).
4. PR merged to `main`; `deploy-functions` deploys production. If a Required reviewer is set on the `production` Environment, approve the paused deploy.
5. Confirm via Application Insights that the production app is healthy.

For a **new** production environment, sections 5.2–5.4 must be run against it first, with its own `scripts/prod.env`. Deploying code to an unconfigured environment fails at runtime, not at deploy time.

## 9. Access summary

| | Sandbox | Production |
|--|---------|-----------|
| Deploys from branch | `staging` | `main` |
| Deploy trigger | automatic on push to `staging` | automatic on merge to `main` (optionally reviewer-gated) |
| Deploy identity | sandbox Entra app, scoped to `rg-ap-automations-sbx` | production Entra app, scoped to `rg-ap-automations-prod` |
| Function App / Key Vault access | developers | deploy identity + sign-off holder only |
| Credentials visible to developers | sandbox only | none |

> If a separate access-control document already exists for the GitHub org and Azure subscriptions, treat it as authoritative and keep this table as a summary only.
