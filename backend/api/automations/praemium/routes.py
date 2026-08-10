"""
Praemium API OAuth endpoints.

Exposes ``/praemium/login`` (redirect to consent) and ``/praemium/callback`` (code
exchange), built from the shared router factory. Mounted by api/main.py. Because the
Functions host prefixes HTTP routes with ``/api``, the redirect URI to register with
Praemium is ``https://<host>/api/praemium/callback`` (locally
``http://localhost:7071/api/praemium/callback``).
"""
from api.automations.praemium.client import praemium_session
from api.lib.oauth import build_oauth_router

router = build_oauth_router(praemium_session, prefix="/praemium", tags=["praemium"])
