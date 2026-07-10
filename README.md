# Advisory Partners Automations

Backend and (future) frontend for the Advisory Partners automation programme — roughly 40 scoped automations, about half confirmed for build. This repo is the **skeleton every automation sits inside**, not any single automation.

- **Backend:** Python, Azure Functions (v2 programming model), FastAPI mounted via the ASGI adapter, on the **Flex Consumption** plan, in **Australia East**.
- **Frontend:** not built yet. Reserved (`frontend/`) for a Next.js app when an automation needs an interface (e.g. the XPM natural-language query tool). See [ARCHITECTURE.md](./ARCHITECTURE.md).
- **Environments:** two — `sandbox` and `production`. Nothing reaches production without sign-off. See [DEPLOYMENT.md](./DEPLOYMENT.md).

## Repository layout

```
advisory-partners-automations/
├── README.md                     # this file
├── ARCHITECTURE.md               # why the system is shaped the way it is
├── DEPLOYMENT.md                 # how it deploys + the two-environment model
├── .github/workflows/
│   ├── deploy-functions.yml      # backend → Flex (triggers on backend/**, contracts/**)
│   ├── deploy-web.yml            # frontend → SWA/App Service (added with the frontend)
│   └── lint-test.yml             # lint + pytest on PR
├── backend/
│   ├── function_app.py           # Functions entry point: ASGI mount + trigger registration
│   ├── host.json
│   ├── requirements.txt
│   ├── api/                      # thin FastAPI routers (main.py defines the FastAPI app)
│   ├── automations/              # one folder per automation, business logic only
│   ├── lib/                      # shared clients, knowledge base, doc builders, ID resolution
│   ├── scripts/export_openapi.py # dumps app.openapi() → contracts/openapi.json
│   └── tests/
├── contracts/
│   └── openapi.json              # generated API contract — the frontend's only view of the backend
├── frontend/                     # reserved, empty until Next.js is needed
└── infra/                        # optional IaC (Bicep/Terraform) for the Azure resources
```

## Local development

Prerequisites: Python 3.11+, [Azure Functions Core Tools v4](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local), an Azure CLI login with access to the sandbox subscription.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# run the Functions host locally (serves FastAPI under http://localhost:7071/api/*)
func start
```

Interactive API docs are available locally at `http://localhost:7071/api/docs` (FastAPI's Swagger UI). Remember every route is prefixed with `/api` by the Functions host.

Regenerate the API contract after changing any route:

```bash
python scripts/export_openapi.py   # writes ../contracts/openapi.json
```

CI fails if `contracts/openapi.json` is out of date, so commit it alongside the route change in the same PR.

## Adding a new automation

1. Land a signed-off spec first (dual deliverable: client-facing doc + developer-facing markdown — build against the markdown). **Do not** create an `automations/` folder ahead of that.
2. Add `backend/automations/<name>/` with business logic only — no trigger wiring, no Azure SDK glue.
3. Register its trigger (timer / queue / blob / HTTP router) in `function_app.py`, ideally via a blueprint imported from the automation folder.
4. Reuse `lib/` — knowledge base, system clients, doc builders, identity resolution. If two automations are near-duplicates (e.g. the paired meeting-summary items), parameterise one implementation rather than copy-pasting folders.
5. Add tests under `backend/tests/`. Business logic is plain Python and testable with `pytest` without the Functions runtime.
6. Per-automation Claude/data-flow clearance is **not** blanket — each new data flow needs its own sign-off. See [ARCHITECTURE.md](./ARCHITECTURE.md) §Open questions.

## Documentation map

| Doc | Answers |
|-----|---------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | What the pieces are and why — backend pattern, shared library, systems, the contract seam, frontend plan. |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | How it ships — the two-environment model, Azure resources, Key Vault, CI/CD, the production sign-off gate. |