# Architecture

> **Merge note:** if an `ARCHITECTURE.md` already exists covering environments, access, and the GitHub org, keep that content as the source of truth for those topics and merge only the *technical* sections below into it. The **Environments** and **Access** topics here are summaries — the authoritative detail lives in [DEPLOYMENT.md](./DEPLOYMENT.md) and any pre-existing access documentation.

## 1. Backend pattern

Python on **Azure Functions (v2 programming model)**. HTTP-triggered surface is a **FastAPI** app mounted through the ASGI adapter (`func.AsgiFunctionApp`); scheduled and event-driven work uses standard **timer / queue / blob** triggers in the same Function App. Hosted on the **Flex Consumption** plan, **Australia East**.

**Why this shape:**

- Most of the programme is background work — a document lands in SharePoint, a cron fires, a Zoho pull runs — not a live request-driven application. Functions is the right cost/ops model for that.
- Flex Consumption specifically: Linux Consumption is being retired (hosting Linux function apps on the Consumption plan retires **30 September 2028** and receives no new features/runtimes), so we build on Flex from day one to avoid a forced migration.
- FastAPI-via-ASGI gives normal FastAPI ergonomics (routing, Pydantic validation, auto-generated OpenAPI) without giving up the Functions hosting model. **One deployment pattern, not two.**

**Consequences to remember:**

- The Functions host prefixes all HTTP routes with `/api`, so FastAPI routes are served under `/api/*`.
- In the Azure portal the whole FastAPI app appears as a **single function** that fans traffic out to your routes — not one function per route.
- Python on Flex is Linux-only and defaults to one concurrent invocation per instance; raise per-instance concurrency for the I/O-bound automations (Graph / Zoho / Claude calls) rather than paying for an instance per in-flight request.

## 2. Repository structure

```
backend/
├── function_app.py     # entry point — see §3
├── host.json
├── requirements.txt
├── api/                # thin FastAPI routers; api/main.py defines the FastAPI app object
├── automations/        # one folder per automation, business logic only
├── lib/                # shared library — see §4 (the real leverage)
├── scripts/
│   └── export_openapi.py
└── tests/
contracts/
└── openapi.json        # generated API contract — the frontend's only view of the backend
frontend/               # reserved, empty until Next.js is needed
```

Do not build out `automations/` folders ahead of a signed-off spec. Paired builds (the meeting-summary items) should be one parameterised implementation, not near-duplicate folders.

## 3. `function_app.py` — the entry point

The Functions host loads this file by convention and binds to the `app` object it defines. It does exactly two jobs and holds **no business logic**:

1. **Mounts FastAPI as the HTTP surface** via the ASGI adapter:
   ```python
   import azure.functions as func
   from api.main import app as fastapi_app
   app = func.AsgiFunctionApp(app=fastapi_app, http_auth_level=func.AuthLevel.FUNCTION)
   ```
2. **Registers non-HTTP triggers** — timer (daily Zoho pulls), queue, blob/SharePoint-event — directly or via blueprints imported from `automations/`.

It is the seam between Azure's hosting model (triggers, bindings, the `app` object) and ordinary Python. Business logic lives in `automations/` and `lib/` so it stays testable with plain `pytest`, independent of the runtime.

## 4. Shared library (`backend/lib/`)

The same handful of patterns recur across most of the 40 automations. Building these once, well, is most of the value in the repo.

- **System clients** — one wrapper per external system, handling auth/retry/rate-limiting once: `zoho_client.py`, `graph_client.py` (Teams/Outlook/Calendar/SharePoint), `claude_client.py`, `praemium_client.py`, `class_client.py`.
- **Document builders** — `doc_builder.py` (Word), `pdf_builder.py`, `excel_builder.py`. Output is Word or PDF in nearly every automation; standardise branding/styling once.
- **Knowledge base** — `knowledge_base.py`: versioned storage, retrieval, prompt assembly. **10+ automations** share the identical shape (load reference material → inject into a Claude call → get structured commentary back). Build to a stable interface early even though most source content isn't ready.
- **Cross-system client identity resolution** — `identity_resolution.py`: mapping one client across Praemium, Zoho, Class, XPLAN and SharePoint where they share no common ID. Flagged in the tracker (item 8) as the single most complex architectural decision in the programme. Solve once as a shared utility — do not let it get solved implicitly inside one automation.
- **Common output patterns** — a shared heatmap/traffic-light renderer and a shared two-agent (drafter + checker) review pattern, generalised rather than rebuilt per automation.

## 5. Systems

**Core (most of the programme):**

| System | Approx. usage | Notes |
|--------|---------------|-------|
| Claude API | ~25 of 40 | Dominant integration. The "Azure OpenAI or Claude" question has resolved to Claude. |
| SharePoint | ~20 of 40 | Primary trigger + document store for upload-triggered automations. |
| Microsoft Graph API | ~12 of 40 | Teams (meetings/transcripts), Outlook, Calendar. |
| Zoho Projects API | 7 of 40 | Daily FP workflows, summaries, term deposits. |

**Secondary (real, but specific automations):** Praemium (3), Class (2), XPLAN (1 — confirm whether Iress Xplan), XPM (3 — confirm whether Xero Practice Manager; named separately from XPLAN and likely a different system), Bstar/Ibis World (likely document upload, not live API), web scraping (Bell Potter/AFR/Morningstar — **blocked** pending legal review).

**Explicitly not scaffolded now:** Twilio (real future need for SMS reminders, add when that automation is built — don't scaffold speculatively).

## 6. The frontend contract seam

The frontend integrates through a **generated artifact**, never by reaching into backend code:

1. FastAPI produces its OpenAPI schema for free.
2. `scripts/export_openapi.py` dumps it to `contracts/openapi.json` (committed; CI diffs it so it can't drift).
3. When Next.js arrives, a typed client is codegen'd from that file (`openapi-typescript` / `orval`).

Because Python and TypeScript can't share runtime code, `contracts/` holds **only** the schema and generated clients — there is no shared runtime package across the boundary, and the design should not assume one.

Routers stay consumer-agnostic: they call `automations/`/`lib/`, return Pydantic models, and never assume who's calling. The same route serves a future Next.js app, a Power Automate HTTP action, or curl identically.

## 7. Frontend hosting (when it lands)

Two viable targets — decide by how much server-side rendering the frontend needs:

- **Mostly static dashboard** → Azure Static Web Apps, deployed from `frontend/`. Note: deploying a Next.js *monorepo* to SWA has documented build-detection friction (the SWA build system gets confused by root lockfile vs. app subfolder), so expect some workflow tuning.
- **Real SSR** → Azure App Service, which handles full Next.js SSR more cleanly and is the smoother monorepo target.

Either way the backend is untouched: the frontend calls FastAPI over HTTPS using the `contracts/openapi.json` client. **Do not** use the SWA "linked backend" feature — it requires the Standard plan, caps requests at 45s, only proxies HTTP functions, requires the backend be publicly reachable, and is **not** a supported combination with Flex Consumption.

Cross-origin means two config seams to handle (both left as config, not built speculatively):

- **CORS** — env-driven `CORSMiddleware` allowlist in FastAPI (localhost in dev, the SWA/App Service hostname in sandbox/prod).
- **Auth** — the natural fit for this Entra-heavy stack is Entra ID; validate the Entra JWT in FastAPI middleware rather than relying on SWA's `x-ms-client-principal` header (that header only flows through the linked path we're not using).

## 8. Decisions locked in

- Heatmap routing uses the **Owner** field, not Partner.
- GitHub org owned/administered by AP; outside-collaborator admin access held by the programme lead.
- **Dual deliverables:** every spec exists as a client-facing document + a developer-facing markdown — build against the markdown.
- Cross-system client ID mapping (item 8) is the key architecture decision — solve it explicitly and once.

## 9. Open questions

- Are **XPLAN** and **XPM** two separate systems (as the tracker implies) or one platform named inconsistently? Confirm before building either client wrapper.
- Scraping legality for the portfolio-scrape sources — pending legal review; don't build against it until cleared.
- Knowledge-base source material is pending for most automations that need it — build the `knowledge_base.py` interface to a stable shape now even though content isn't ready.
- **Claude API clearance is per-data-flow, not blanket** — each automation's data flow needs its own sign-off; clearance does not carry across automations.