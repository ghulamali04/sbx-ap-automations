"""
Class (PIE API) OAuth client.

Thin instantiation of the shared OAuth toolkit for Class's PIE API. All endpoints and
credentials are env-driven (``CLASS_*``) so the exact authorize/token hosts stay
overridable per environment — nothing about Class is hardcoded here beyond wiring.

Import ``class_session`` from automations that need to call Class:

    from api.automations.class_pie.client import class_session
    headers = await class_session.auth_headers()  # Authorization: Bearer <token>

The ``/class/login`` → ``/class/callback`` flow (see routes.py) mints the tokens once;
``class_session`` refreshes them automatically from then on.
"""
from __future__ import annotations

import os

from api.lib.oauth import OAuthProvider, TokenSession, TokenStore

# Env prefix: CLASS_CLIENT_ID / CLASS_CLIENT_SECRET / CLASS_REDIRECT_URI /
# CLASS_AUTHORIZE_URL / CLASS_TOKEN_URL / CLASS_SCOPE / CLASS_TOKEN_AUTH.
# Set CLASS_REDIRECT_URI to the deployed "/api/class/callback" URL and register it in
# the Class API console. Authorize/token URLs are left blank so they must be supplied
# from config for the target Class environment.
class_provider = OAuthProvider.from_env(
    name="class",
    prefix="CLASS",
)

class_session = TokenSession(
    provider=class_provider,
    store=TokenStore("class", secret_name=os.getenv("CLASS_TOKENS_SECRET_NAME") or None),
)
