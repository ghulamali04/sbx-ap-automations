"""
Class (PIE API) OAuth endpoints.

Exposes ``/class/login`` (redirect to consent) and ``/class/callback`` (code exchange),
built from the shared router factory. Mounted by api/main.py. Because the Functions
host prefixes HTTP routes with ``/api``, the redirect URI to register with Class is
``https://<host>/api/class/callback`` (locally ``http://localhost:7071/api/class/callback``).
"""
from api.automations.class_pie.client import class_session
from api.lib.oauth import build_oauth_router

router = build_oauth_router(class_session, prefix="/class", tags=["class"])
