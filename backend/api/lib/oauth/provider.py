"""
Provider configuration + the raw OAuth2 authorization-code calls.

One :class:`OAuthProvider` instance describes a single upstream (Class PIE, Praemium,
…). Everything that varies between vendors — the authorize/token URLs, credentials,
redirect URI, scopes, whether the token endpoint wants credentials in the body or as
HTTP Basic — is configuration, so the three network methods below are identical for
every provider. Nothing is hardcoded per vendor: build instances with
:meth:`OAuthProvider.from_env` so the exact endpoints stay overridable via app
settings, matching how the Zoho client reads ``ZOHO_ACCOUNTS_URL`` etc.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException


@dataclass
class OAuthProvider:
    """Immutable description of one OAuth2 authorization-code provider.

    Attributes:
        name: Short identifier, used for logs, the token-store key and error text.
        authorize_url: The provider's authorization endpoint (where the user consents).
        token_url: The provider's token endpoint (code/refresh-token exchange).
        client_id / client_secret: OAuth client credentials.
        redirect_uri: The callback URL registered with the provider; must match the
            route mounted by build_oauth_router exactly.
        scope: Space- or comma-separated scope string (provider-specific).
        token_auth: ``"body"`` sends client_id/secret in the POST body (Zoho style);
            ``"basic"`` sends them as an HTTP Basic Authorization header (required by
            some providers). Defaults to ``"body"``.
        auth_header_scheme: Scheme used when calling the *data* API with the access
            token, e.g. ``"Bearer"`` -> ``Authorization: Bearer <token>``.
        extra_authorize_params: Extra query params appended to the authorize URL
            (e.g. ``{"access_type": "offline", "prompt": "consent"}``).
    """

    name: str
    authorize_url: str
    token_url: str
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None
    scope: str = ""
    token_auth: str = "body"
    auth_header_scheme: str = "Bearer"
    extra_authorize_params: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(
        cls,
        name: str,
        prefix: str,
        *,
        default_authorize_url: str = "",
        default_token_url: str = "",
        default_scope: str = "",
        default_token_auth: str = "body",
        default_auth_header_scheme: str = "Bearer",
        extra_authorize_params: dict[str, str] | None = None,
    ) -> "OAuthProvider":
        """Build a provider from ``{PREFIX}_*`` environment variables.

        Reads ``{PREFIX}_CLIENT_ID``, ``{PREFIX}_CLIENT_SECRET``,
        ``{PREFIX}_REDIRECT_URI``, ``{PREFIX}_AUTHORIZE_URL``, ``{PREFIX}_TOKEN_URL``,
        ``{PREFIX}_SCOPE`` and ``{PREFIX}_TOKEN_AUTH``. The ``default_*`` arguments let
        an automation bake in a vendor's well-known URLs while still allowing an env
        override (e.g. staging vs production hosts, or a regional endpoint).
        """
        def env(suffix: str, default: str = "") -> str:
            return (os.getenv(f"{prefix}_{suffix}") or default).strip()

        return cls(
            name=name,
            authorize_url=env("AUTHORIZE_URL", default_authorize_url).rstrip("/") or default_authorize_url,
            token_url=env("TOKEN_URL", default_token_url).rstrip("/") or default_token_url,
            client_id=env("CLIENT_ID") or None,
            client_secret=env("CLIENT_SECRET") or None,
            redirect_uri=env("REDIRECT_URI") or None,
            scope=env("SCOPE", default_scope),
            token_auth=env("TOKEN_AUTH", default_token_auth).lower() or default_token_auth,
            auth_header_scheme=default_auth_header_scheme,
            extra_authorize_params=dict(extra_authorize_params or {}),
        )

    # ---------- configuration guards ----------

    def require_configured(self) -> None:
        """Raise a clear 500 if the provider is missing the settings a flow needs."""
        missing = [
            label
            for label, value in (
                (f"{self.name} authorize URL", self.authorize_url),
                (f"{self.name} token URL", self.token_url),
                (f"{self.name} client id", self.client_id),
                (f"{self.name} client secret", self.client_secret),
                (f"{self.name} redirect URI", self.redirect_uri),
            )
            if not value
        ]
        if missing:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"{self.name} OAuth is not configured. Missing: "
                    + ", ".join(missing)
                    + ". Set the corresponding app settings."
                ),
            )

    # ---------- OAuth2 authorization-code flow ----------

    def get_authorization_url(self, state: str | None = None) -> str:
        """Build the URL to redirect the user to for consent."""
        self.require_configured()
        params: dict[str, str] = {
            "client_id": self.client_id or "",
            "response_type": "code",
            "redirect_uri": self.redirect_uri or "",
        }
        if self.scope:
            params["scope"] = self.scope
        if state:
            params["state"] = state
        params.update(self.extra_authorize_params)
        return f"{self.authorize_url}?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str) -> dict:
        """Exchange an authorization code for an access/refresh token pair."""
        self.require_configured()
        data = {
            "code": code,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        return await self._token_request(data, failure_status=400)

    async def refresh_access_token(self, refresh_token: str) -> dict:
        """Exchange a long-lived refresh token for a fresh access token.

        Some providers omit the refresh token on this call; callers must preserve the
        existing one when persisting (TokenSession handles that).
        """
        self.require_configured()
        data = {
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        return await self._token_request(data, failure_status=401)

    async def _token_request(self, data: dict, *, failure_status: int) -> dict:
        """POST to the token endpoint, placing credentials per ``token_auth``."""
        auth = None
        if self.token_auth == "basic":
            auth = (self.client_id or "", self.client_secret or "")
        else:  # "body"
            data = {
                **data,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }

        async with httpx.AsyncClient() as client:
            response = await client.post(self.token_url, data=data, auth=auth)

        if response.status_code != 200:
            detail = response.json() if response.text else "Unknown error"
            raise HTTPException(
                status_code=failure_status,
                detail=f"{self.name} token request failed: {detail}",
            )
        return response.json()

    def auth_headers(self, access_token: str) -> dict[str, str]:
        """Authorization header for calling the provider's data API."""
        return {"Authorization": f"{self.auth_header_scheme} {access_token}".strip()}
