"""
Praemium API OAuth client.

Thin instantiation of the shared OAuth toolkit for the Praemium API. All endpoints and
credentials are env-driven (``PRAEMIUM_*``) so the exact authorize/token hosts stay
overridable per environment — nothing about Praemium is hardcoded here beyond wiring.

Import ``praemium_session`` from automations that need to call Praemium:

    from api.automations.praemium.client import praemium_session
    headers = await praemium_session.auth_headers()  # Authorization: Bearer <token>

The ``/praemium/login`` → ``/praemium/callback`` flow (see routes.py) mints the tokens
once; ``praemium_session`` refreshes them automatically from then on.
"""
from __future__ import annotations

import os

from api.lib.oauth import OAuthProvider, TokenSession, TokenStore

# Env prefix: PRAEMIUM_CLIENT_ID / PRAEMIUM_CLIENT_SECRET / PRAEMIUM_REDIRECT_URI /
# PRAEMIUM_AUTHORIZE_URL / PRAEMIUM_TOKEN_URL / PRAEMIUM_SCOPE / PRAEMIUM_TOKEN_AUTH.
# Set PRAEMIUM_REDIRECT_URI to the deployed "/api/praemium/callback" URL and register
# it with Praemium. Authorize/token URLs are left blank so they must be supplied from
# config for the target Praemium environment.
praemium_provider = OAuthProvider.from_env(
    name="praemium",
    prefix="PRAEMIUM",
)

praemium_session = TokenSession(
    provider=praemium_provider,
    store=TokenStore("praemium", secret_name=os.getenv("PRAEMIUM_TOKENS_SECRET_NAME") or None),
)
