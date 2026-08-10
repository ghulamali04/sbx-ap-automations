"""
FastAPI application for the Advisory Partners automations backend.

This is a plain ASGI app. It has no dependency on the Azure Functions runtime,
so it can be run two ways:
  1. Standalone for quick testing:   uvicorn api.main:app --reload --port 8000
  2. Inside the Functions host:       func start   (mounted by ../function_app.py)

Under uvicorn, routes are served at the root (e.g. /health).
Under the Functions host, the runtime prefixes every route with /api (e.g. /api/health).

Per-automation logic and routes live under api/automations/<name>/ and are mounted
here as routers. main.py itself only owns app setup and cross-cutting concerns.
"""
import os

# Load local.settings.json into the environment (no-op under `func start`, which
# already does this). Must run before anything reads os.getenv below.
from api.settings import load_local_settings
load_local_settings()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.automations.zoho.routes import router as zoho_router
from api.automations.completion_overview.routes import router as completion_router
from api.automations.meeting_notes.routes import router as meeting_notes_router

app = FastAPI(
    title="Advisory Partners Automations API",
    version="0.1.0",
)

# Env-driven CORS allowlist. Localhost in dev; the SWA/App Service hostname in
# sandbox/prod. Comma-separated. Never hardcode "*" for anything real.
_origins = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Liveness probe — the first thing to hit once deployed to sandbox."""
    return {"status": "ok", "service": "ap-automations"}


class EchoIn(BaseModel):
    message: str


class EchoOut(BaseModel):
    echoed: str
    length: int


@app.post("/echo", response_model=EchoOut)
async def echo(body: EchoIn):
    """Trivial route that exercises Pydantic request/response validation."""
    return EchoOut(echoed=body.message, length=len(body.message))


# ---------- Automations ----------
app.include_router(zoho_router)
app.include_router(completion_router)
app.include_router(meeting_notes_router)
