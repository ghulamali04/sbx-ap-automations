"""
Zoho automation — HTTP endpoints and integration logic.

Every Zoho-specific route lives here behind an APIRouter, mounted by api/main.py.
Paths are intentionally kept at the root (no /zoho prefix): the OAuth redirect URI
(/callback) is registered in the Zoho API console and must stay stable.
"""
import os

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from api.automations.zoho.session import zoho_auth, get_access_token, store_new_tokens

# Zoho Projects data API base. Region-specific — override via env for AU/EU/IN
# (e.g. https://projectsapi.zoho.com.au). The accounts/OAuth host is configured
# separately through ZOHO_ACCOUNTS_URL inside ZohoAuth.
PROJECTS_API_BASE = (
    os.getenv("ZOHO_PROJECTS_API_BASE") or "https://projectsapi.zoho.com"
).rstrip("/")

router = APIRouter(tags=["zoho"])


async def _auth_headers() -> dict:
    """Build the Zoho auth header, auto-refreshing the access token when expired."""
    access_token = await get_access_token()
    return {"Authorization": f"Zoho-oauthtoken {access_token}"}


# ---------- OAuth2 ----------

@router.get("/login")
async def login():
    """Redirect the user to Zoho for authorization."""
    return RedirectResponse(url=zoho_auth.get_authorization_url())


@router.get("/callback")
async def callback(code: str):
    """Handle the Zoho callback, exchange the code for tokens, and store them."""
    payload = await zoho_auth.exchange_code_for_tokens(code)
    stored = store_new_tokens(payload, payload.get("refresh_token", ""))
    return {
        "message": "Tokens stored successfully. Access tokens now auto-refresh — no need to log in again.",
        "access_token": stored["access_token"],
        "refresh_token": stored["refresh_token"],
    }


# ---------- Zoho Projects ----------

@router.get("/portals")
async def list_portals():
    """List every Zoho Projects portal the current token can access.

    Note: Zoho's list endpoint only returns portals the account *owns*, not ones
    it is merely a *member* of — those come back as 204. To use a member portal,
    read its id from the browser URL (projects.zoho.com/portal/<id>) and set
    ZOHO_PORTAL_ID.
    """
    headers = await _auth_headers()
    url = f"{PROJECTS_API_BASE}/restapi/portals/"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

    if response.status_code == 204:
        return {
            "portals": [],
            "note": (
                "Zoho returned 204 No Content — the account owns no portals. "
                "Member portals are not listed here; use their id from the URL "
                "(projects.zoho.com/portal/<id>)."
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


@router.get("/projects")
async def list_projects():
    """List projects under the configured portal (ZOHO_PORTAL_ID)."""
    headers = await _auth_headers()

    portal_id = os.getenv("ZOHO_PORTAL_ID")
    if not portal_id:
        raise HTTPException(
            status_code=500,
            detail="ZOHO_PORTAL_ID is not set. Find it at projects.zoho.com/portal/<id> and add it to config.",
        )

    url = f"{PROJECTS_API_BASE}/restapi/portal/{portal_id}/projects/"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Zoho API error (HTTP {response.status_code}): {response.text}",
        )

    return response.json()
