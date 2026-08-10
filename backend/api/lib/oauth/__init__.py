"""
Reusable OAuth2 authorization-code toolkit.

Generalises the pattern first proven in the Zoho automation so every provider that
needs a browser-consent → callback → token flow (Class PIE, Praemium, …) reuses one
tested implementation instead of copying four files each time. An automation supplies
a :class:`OAuthProvider` (all endpoints/credentials env-driven), gets a
:class:`TokenSession` that keeps a valid access token available with auto-refresh,
and mounts the :func:`build_oauth_router` router to expose ``/login`` + ``/callback``.
"""
from api.lib.oauth.provider import OAuthProvider
from api.lib.oauth.token_store import TokenStore
from api.lib.oauth.session import TokenSession
from api.lib.oauth.routes import build_oauth_router

__all__ = [
    "OAuthProvider",
    "TokenStore",
    "TokenSession",
    "build_oauth_router",
]
