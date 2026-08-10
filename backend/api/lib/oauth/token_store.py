"""
Per-provider store for OAuth token bundles — Azure Key Vault in the cloud, a local
JSON file in dev. Generalised from the Zoho token store so every provider gets the
same durable, Flex-Consumption-safe persistence without reimplementing it.

Each :class:`TokenStore` instance owns one provider's bundle:

  * ``KEY_VAULT_URI`` set (sandbox / prod): the whole bundle (access + refresh +
    expiry) is a single JSON secret in that Key Vault, read/written through the
    Function App's managed identity (DefaultAzureCredential). Required on Flex
    Consumption, whose package mount is read-only and whose instances are ephemeral —
    a local token file neither survives a restart nor is shared across instances.

  * ``KEY_VAULT_URI`` unset (local dev / tests): falls back to a JSON file next to the
    backend root, one per provider, preserving ``func start`` / uvicorn behaviour.

An in-process cache holds the last-known bundle so the hot path (every API call reads
the token) doesn't hit Key Vault per request. Each instance refreshes independently
off the stable refresh token, which the providers permit.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

# backend/  ->  four levels up from api/lib/oauth/token_store.py
_BACKEND_ROOT = Path(__file__).resolve().parents[3]

_KEY_VAULT_URI = os.getenv("KEY_VAULT_URI", "").strip()

# Key Vault client, shared across stores, created lazily on first use. Never at import
# time: a missing/misconfigured vault must not break module import (which would fail
# the whole Functions host at startup rather than just one automation).
_secret_client = None
_secret_client_lock = threading.Lock()


def _get_secret_client():
    global _secret_client
    with _secret_client_lock:
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


def _use_key_vault() -> bool:
    return bool(_KEY_VAULT_URI)


class TokenStore:
    """Durable storage for one provider's OAuth token bundle.

    Args:
        name: Provider identifier (e.g. ``"class"``); used to derive the default
            Key Vault secret name and the local file name.
        secret_name: Explicit Key Vault secret name; defaults to ``{name}-tokens``.
            Usually supplied from ``{PREFIX}_TOKENS_SECRET_NAME`` app setting.
    """

    def __init__(self, name: str, secret_name: str | None = None):
        safe = re.sub(r"[^a-z0-9-]", "-", name.lower())
        self._secret_name = secret_name or f"{safe}-tokens"
        self._token_file = _BACKEND_ROOT / f".{safe}_tokens.json"
        self._cache: dict | None = None
        self._lock = threading.Lock()

    def save(self, tokens: dict) -> None:
        """Persist the token bundle and refresh the in-process cache."""
        with self._lock:
            self._cache = dict(tokens)

        if _use_key_vault():
            _get_secret_client().set_secret(self._secret_name, json.dumps(tokens))
        else:
            self._token_file.write_text(json.dumps(tokens, indent=2))

    def load(self) -> dict:
        """Return the stored bundle ({} if none), reading the backend once then caching."""
        with self._lock:
            if self._cache is not None:
                return dict(self._cache)

        tokens = self._read_from_backend()

        with self._lock:
            # Only seed the cache if nothing was written while we were reading.
            if self._cache is None:
                self._cache = dict(tokens)
            return dict(self._cache)

    def _read_from_backend(self) -> dict:
        if _use_key_vault():
            from azure.core.exceptions import ResourceNotFoundError

            try:
                secret = _get_secret_client().get_secret(self._secret_name)
            except ResourceNotFoundError:
                return {}  # secret not created yet -> user hasn't logged in
            if not secret.value:
                return {}
            try:
                return json.loads(secret.value)
            except json.JSONDecodeError:
                return {}

        # Local-file mode (dev).
        if not self._token_file.exists():
            return {}
        try:
            return json.loads(self._token_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
