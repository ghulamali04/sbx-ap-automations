"""
Access-token provider with automatic refresh, one per upstream.

A :class:`TokenSession` binds an :class:`OAuthProvider` to a :class:`TokenStore` and
keeps a valid access token available without user interaction: it reads the persisted
tokens and, when the access token is near expiry, uses the long-lived refresh token to
mint a new one and persists it. So ``/login`` (the OAuth consent) is a one-time step,
not a per-call one. Generalised from the Zoho session so every provider shares the
same refresh/locking logic.
"""
from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException

from api.lib.oauth.provider import OAuthProvider
from api.lib.oauth.token_store import TokenStore

# Refresh this many seconds before the access token actually expires, so a slow
# request never races the expiry boundary.
_EXPIRY_BUFFER_SECONDS = 120


class TokenSession:
    def __init__(self, provider: OAuthProvider, store: TokenStore):
        self.provider = provider
        self.store = store
        # Serialise refreshes so concurrent requests don't all call the provider at once.
        self._refresh_lock = asyncio.Lock()

    # ---------- persistence helpers ----------

    def store_new_tokens(self, payload: dict, existing_refresh_token: str = "") -> dict:
        """Normalise a provider token payload into our stored shape and persist it.

        Providers that omit the refresh token on a refresh call fall back to the
        existing one so it is never clobbered.
        """
        expires_in = int(payload.get("expires_in", 3600))
        tokens = {
            "access_token": payload.get("access_token"),
            "refresh_token": payload.get("refresh_token") or existing_refresh_token,
            "expires_at": time.time() + expires_in,
        }
        self.store.save(tokens)
        return tokens

    @staticmethod
    def _is_expired(tokens: dict) -> bool:
        expires_at = tokens.get("expires_at")
        if not expires_at:
            return True  # unknown expiry -> refresh to be safe
        return time.time() >= (expires_at - _EXPIRY_BUFFER_SECONDS)

    # ---------- flow entry points ----------

    async def complete_login(self, code: str) -> dict:
        """Exchange an authorization code and persist the resulting tokens."""
        payload = await self.provider.exchange_code_for_tokens(code)
        return self.store_new_tokens(payload, payload.get("refresh_token", ""))

    async def get_access_token(self) -> str:
        """Return a valid access token, refreshing via the refresh token if needed."""
        tokens = self.store.load()
        if not tokens.get("access_token") and not tokens.get("refresh_token"):
            raise HTTPException(
                status_code=401,
                detail=f"No {self.provider.name} tokens stored. Please login first.",
            )

        if not self._is_expired(tokens):
            return tokens["access_token"]

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise HTTPException(
                status_code=401,
                detail=(
                    f"{self.provider.name} access token expired and no refresh token. "
                    "Please login again."
                ),
            )

        async with self._refresh_lock:
            # Re-check after acquiring the lock — another request may have refreshed.
            tokens = self.store.load()
            if not self._is_expired(tokens):
                return tokens["access_token"]
            payload = await self.provider.refresh_access_token(refresh_token)
            tokens = self.store_new_tokens(payload, refresh_token)

        return tokens["access_token"]

    async def auth_headers(self) -> dict[str, str]:
        """Authorization header for a data-API call, refreshing the token if needed."""
        return self.provider.auth_headers(await self.get_access_token())
