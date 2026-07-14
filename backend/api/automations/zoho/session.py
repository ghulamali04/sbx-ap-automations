"""
Access-token provider with automatic refresh.

Keeps a valid Zoho access token available without user interaction: it reads the
persisted tokens and, when the access token is near expiry, uses the long-lived
refresh token to mint a new one and persists it. So /login (the OAuth consent) is
a one-time step, not a daily one.

The store is abstracted behind save_tokens / load_tokens, so swapping the JSON
file for a DB / Key Vault later requires no change to this refresh logic.
"""
import asyncio
import time

from fastapi import HTTPException

from api.automations.zoho.auth import ZohoAuth
from api.automations.zoho.token_store import save_tokens, load_tokens

# Refresh this many seconds before the access token actually expires, so a slow
# request never races the expiry boundary.
_EXPIRY_BUFFER_SECONDS = 120

# Single shared instance (stateless — reads config from env).
zoho_auth = ZohoAuth()

# Serialise refreshes so concurrent requests don't all call Zoho at once.
_refresh_lock = asyncio.Lock()


def _is_expired(tokens: dict) -> bool:
    expires_at = tokens.get("expires_at")
    if not expires_at:
        return True  # unknown expiry -> refresh to be safe
    return time.time() >= (expires_at - _EXPIRY_BUFFER_SECONDS)


def store_new_tokens(payload: dict, existing_refresh_token: str = "") -> dict:
    """Normalise a Zoho token payload into our stored shape and persist it.

    Zoho omits the refresh token on a refresh call, so fall back to the existing
    one to avoid clobbering it.
    """
    expires_in = int(payload.get("expires_in", 3600))
    tokens = {
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token") or existing_refresh_token,
        "expires_at": time.time() + expires_in,
    }
    save_tokens(tokens)
    return tokens


async def get_access_token() -> str:
    """Return a valid access token, refreshing via the refresh token if needed."""
    tokens = load_tokens()
    if not tokens.get("access_token") and not tokens.get("refresh_token"):
        raise HTTPException(
            status_code=401, detail="No tokens stored. Please login first via /login"
        )

    if not _is_expired(tokens):
        return tokens["access_token"]

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=401,
            detail="Access token expired and no refresh token. Please login again via /login",
        )

    async with _refresh_lock:
        # Re-check after acquiring the lock — another request may have refreshed.
        tokens = load_tokens()
        if not _is_expired(tokens):
            return tokens["access_token"]
        payload = await zoho_auth.refresh_access_token(refresh_token)
        tokens = store_new_tokens(payload, refresh_token)

    return tokens["access_token"]
