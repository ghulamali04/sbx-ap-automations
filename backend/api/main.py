"""
FastAPI application for the Advisory Partners automations backend.

This is a plain ASGI app. It has no dependency on the Azure Functions runtime,
so it can be run two ways:
  1. Standalone for quick testing:   uvicorn api.main:app --reload --port 8000
  2. Inside the Functions host:       func start   (mounted by ../function_app.py)

Under uvicorn, routes are served at the root (e.g. /health).
Under the Functions host, the runtime prefixes every route with /api (e.g. /api/health).
"""
import httpx
import os

# Load local.settings.json into the environment (no-op under `func start`, which
# already does this). Must run before anything reads os.getenv below.
from api.settings import load_local_settings
load_local_settings()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

# Zoho auth module
from api.zoho.auth import ZohoAuth
# File-backed token storage so tokens survive uvicorn --reload / restarts.
# (Replace with a per-account DB / Key Vault store for production multi-portal use.)
from api.zoho.token_store import save_tokens, load_tokens

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

# Instantiate ZohoAuth (must be before route definitions)
zoho_auth = ZohoAuth()


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


# ---------- Zoho OAuth2 endpoints ----------

@app.get("/login")
async def login():
    """Redirect user to Zoho for authorization."""
    auth_url = zoho_auth.get_authorization_url()
    return RedirectResponse(url=auth_url)


@app.get("/callback")
async def callback(code: str):
    """Handle Zoho callback, exchange code for tokens, and store them."""
    tokens = await zoho_auth.exchange_code_for_tokens(code)
    stored = {
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "expires_in": tokens.get("expires_in"),
    }
    save_tokens(stored)
    return {
        "message": "Tokens stored successfully",
        "access_token": stored["access_token"],
        "refresh_token": stored["refresh_token"],
    }

@app.get("/portals")
async def list_portals():
    """List every Zoho Projects portal the current token can access.

    Use this to discover the portal id for any Zoho account: log in via /login
    with that account, then read the `id_string` field from this response.
    """
    tokens = load_tokens()
    if not tokens.get("access_token"):
        raise HTTPException(status_code=401, detail="No access token. Please login first via /login")

    headers = {"Authorization": f"Zoho-oauthtoken {tokens['access_token']}"}
    url = "https://projectsapi.zoho.com/restapi/portals/"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

    if response.status_code == 204:
        # Zoho sends 204 when the account has no portals visible to this token.
        return {
            "portals": [],
            "note": (
                "Zoho returned 204 No Content — this token's account has no Zoho "
                "Projects portal, or the client belongs to a different account/data "
                "center than the portal you expect."
            ),
        }
    if response.status_code != 200:
        # Surface upstream failures as 502 so the status/body are never stripped
        # (passing e.g. Zoho's 204 through as our status would drop the detail).
        raise HTTPException(
            status_code=502,
            detail=f"Zoho API error (HTTP {response.status_code}): {response.text}",
        )

    return response.json()


@app.get("/projects")
async def list_projects():
    tokens = load_tokens()
    if not tokens.get("access_token"):
        raise HTTPException(status_code=401, detail="No access token. Please login first via /login")

    headers = {
        "Authorization": f"Zoho-oauthtoken {tokens['access_token']}"
    }

    # Portal id comes from config (ZOHO_PORTAL_ID in local.settings.json / app settings).
    # Discover it for any account via the /portals route.
    portal_id = os.getenv("ZOHO_PORTAL_ID")
    if not portal_id:
        raise HTTPException(
            status_code=500,
            detail="ZOHO_PORTAL_ID is not set. Call /portals to find it, then add it to config.",
        )

    # Correct endpoint: portal (singular), not portals
    url = f"https://projectsapi.zoho.com/restapi/portal/{portal_id}/projects/"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Zoho API error (HTTP {response.status_code}): {response.text}"
        )

    return response.json()