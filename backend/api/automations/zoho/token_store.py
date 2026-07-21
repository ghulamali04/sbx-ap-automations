"""
Store for Zoho OAuth tokens — Azure Key Vault in the cloud, a local JSON file in dev.

session.py depends only on save_tokens() / load_tokens(); this module picks the
backend at runtime so that refresh logic never has to change:

  * KEY_VAULT_URI set (sandbox / prod): the whole token bundle (access + refresh +
    expiry) is persisted as a single JSON secret in that Key Vault, read and written
    through the Function App's managed identity (DefaultAzureCredential). This is
    required on Flex Consumption, whose package mount is read-only and whose
    instances are ephemeral — a local token file neither survives a restart nor is
    shared across instances.

  * KEY_VAULT_URI unset (local dev / tests): falls back to a small JSON file next to
    the backend root, preserving the previous behaviour for `func start` / uvicorn.

An in-process cache holds the last-known bundle so the hot path — every Zoho API
call reads the token — does not make a Key Vault round trip per request. The network
call happens on cold start and whenever a refresh writes a new bundle. Each instance
refreshes independently off the (stable) refresh token, which Zoho permits.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

# backend/  ->  four levels up from api/automations/zoho/token_store.py
_TOKEN_FILE = Path(__file__).resolve().parents[3] / ".zoho_tokens.json"

# Where the tokens live in the cloud. Empty -> local-file mode (dev).
_KEY_VAULT_URI = os.getenv("KEY_VAULT_URI", "").strip()
_SECRET_NAME = os.getenv("ZOHO_TOKENS_SECRET_NAME", "zoho-tokens")

# In-process cache of the token bundle, guarded for thread safety, so repeated
# reads don't each hit Key Vault. save_tokens() keeps it current after a refresh.
_cache: dict | None = None
_cache_lock = threading.Lock()

# Key Vault client, created lazily on first use. Never at import time: a missing or
# misconfigured vault must not break module import, which would fail the whole
# Functions host at startup rather than just this one automation.
_secret_client = None


def _use_key_vault() -> bool:
    return bool(_KEY_VAULT_URI)


def _get_secret_client():
    global _secret_client
    if _secret_client is None:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        # DefaultAzureCredential uses the Function App's managed identity in Azure
        # (and az login / env vars locally). For a user-assigned identity, set
        # AZURE_CLIENT_ID so it selects the right one.
        _secret_client = SecretClient(
            vault_url=_KEY_VAULT_URI,
            credential=DefaultAzureCredential(),
        )
    return _secret_client


def save_tokens(tokens: dict) -> None:
    """Persist the token bundle and refresh the in-process cache."""
    global _cache
    with _cache_lock:
        _cache = dict(tokens)

    if _use_key_vault():
        _get_secret_client().set_secret(_SECRET_NAME, json.dumps(tokens))
    else:
        _TOKEN_FILE.write_text(json.dumps(tokens, indent=2))


def load_tokens() -> dict:
    """Return the stored token bundle ({} if none), reading the backend once then caching."""
    global _cache
    with _cache_lock:
        if _cache is not None:
            return dict(_cache)

    tokens = _read_from_backend()

    with _cache_lock:
        # Only seed the cache if nothing was written while we were reading.
        if _cache is None:
            _cache = dict(tokens)
        return dict(_cache)


def _read_from_backend() -> dict:
    if _use_key_vault():
        from azure.core.exceptions import ResourceNotFoundError

        try:
            secret = _get_secret_client().get_secret(_SECRET_NAME)
        except ResourceNotFoundError:
            return {}  # secret not created yet -> user hasn't logged in
        if not secret.value:
            return {}
        try:
            return json.loads(secret.value)
        except json.JSONDecodeError:
            return {}

    # Local-file mode (dev).
    if not _TOKEN_FILE.exists():
        return {}
    try:
        return json.loads(_TOKEN_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
