"""
Router factory for the OAuth consent flow.

:func:`build_oauth_router` returns an APIRouter exposing ``{prefix}/login`` and
``{prefix}/callback`` for a given :class:`TokenSession`. The ``callback`` path is the
redirect URI that must be registered with the provider and set as ``*_REDIRECT_URI``;
keep the prefix stable once registered. Unlike the raw tokens the Zoho callback
echoes, this one returns only a success message and non-secret metadata — the tokens
live in the store, not in a browser-visible response.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from api.lib.oauth.session import TokenSession


def build_oauth_router(
    session: TokenSession,
    *,
    prefix: str,
    tags: list[str] | None = None,
) -> APIRouter:
    """Build a ``/login`` + ``/callback`` router bound to ``session``.

    Args:
        session: The TokenSession that owns this provider's tokens.
        prefix: URL prefix for the routes, e.g. ``"/class"`` -> ``/class/login`` and
            ``/class/callback``. The callback must match the provider's registered
            redirect URI.
        tags: OpenAPI tags for the two routes.
    """
    prefix = "/" + prefix.strip("/")
    router = APIRouter(prefix=prefix, tags=tags or [session.provider.name])
    name = session.provider.name

    @router.get("/login")
    async def login():
        """Redirect the user to the provider for authorization."""
        return RedirectResponse(url=session.provider.get_authorization_url())

    @router.get("/callback")
    async def callback(code: str | None = None, error: str | None = None):
        """Handle the provider callback: exchange the code and store the tokens.

        Returns a success message and non-secret metadata only; the tokens are
        persisted server-side and auto-refresh from here on.
        """
        if error:
            raise HTTPException(
                status_code=400,
                detail=f"{name} authorization failed: {error}",
            )
        if not code:
            raise HTTPException(
                status_code=400,
                detail=f"{name} callback missing 'code' query parameter.",
            )

        stored = await session.complete_login(code)
        return {
            "message": (
                f"{name} authorized successfully. Access tokens now auto-refresh — "
                "no need to log in again."
            ),
            "provider": name,
            "has_refresh_token": bool(stored.get("refresh_token")),
            "expires_at": stored.get("expires_at"),
        }

    return router
