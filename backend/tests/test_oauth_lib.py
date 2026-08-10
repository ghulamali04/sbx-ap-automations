from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.lib.oauth import OAuthProvider, TokenSession, TokenStore, build_oauth_router


def _provider(**overrides) -> OAuthProvider:
    base = dict(
        name="acme",
        authorize_url="https://auth.acme.test/oauth/authorize",
        token_url="https://auth.acme.test/oauth/token",
        client_id="cid",
        client_secret="secret",
        redirect_uri="https://app.test/api/acme/callback",
        scope="read write",
    )
    base.update(overrides)
    return OAuthProvider(**base)


class AuthorizationUrlTests(TestCase):
    def test_builds_url_with_required_params(self) -> None:
        provider = _provider(extra_authorize_params={"access_type": "offline"})
        url = provider.get_authorization_url(state="xyz")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.scheme + "://" + parsed.netloc + parsed.path,
                         "https://auth.acme.test/oauth/authorize")
        self.assertEqual(query["client_id"], ["cid"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["redirect_uri"], ["https://app.test/api/acme/callback"])
        self.assertEqual(query["scope"], ["read write"])
        self.assertEqual(query["state"], ["xyz"])
        self.assertEqual(query["access_type"], ["offline"])

    def test_missing_config_raises_500(self) -> None:
        provider = _provider(client_id=None)
        with self.assertRaises(HTTPException) as ctx:
            provider.get_authorization_url()
        self.assertEqual(ctx.exception.status_code, 500)

    def test_from_env_reads_prefixed_vars(self) -> None:
        env = {
            "ACME_CLIENT_ID": "envcid",
            "ACME_CLIENT_SECRET": "envsecret",
            "ACME_REDIRECT_URI": "https://app.test/api/acme/callback",
            "ACME_AUTHORIZE_URL": "https://auth.acme.test/oauth/authorize",
            "ACME_TOKEN_URL": "https://auth.acme.test/oauth/token",
            "ACME_SCOPE": "read",
            "ACME_TOKEN_AUTH": "basic",
        }
        with patch.dict("os.environ", env, clear=False):
            provider = OAuthProvider.from_env("acme", "ACME")
        self.assertEqual(provider.client_id, "envcid")
        self.assertEqual(provider.token_auth, "basic")
        self.assertEqual(provider.auth_headers("tok"), {"Authorization": "Bearer tok"})


class TokenStoreTests(TestCase):
    def _store(self) -> TokenStore:
        store = TokenStore("acme")
        # Redirect the file to a temp location so the test never touches the repo root.
        store._token_file = Path(tempfile.mkdtemp()) / ".acme_tokens.json"
        return store

    def test_round_trip_and_cache(self) -> None:
        store = self._store()
        self.assertEqual(store.load(), {})
        store.save({"access_token": "a", "refresh_token": "r", "expires_at": 123})
        self.assertEqual(store.load()["access_token"], "a")

        # A fresh store reading the same file returns the persisted bundle.
        fresh = TokenStore("acme")
        fresh._token_file = store._token_file
        self.assertEqual(fresh.load()["refresh_token"], "r")


class TokenSessionTests(IsolatedAsyncioTestCase):
    def _session(self) -> TokenSession:
        store = TokenStore("acme")
        store._token_file = Path(tempfile.mkdtemp()) / ".acme_tokens.json"
        return TokenSession(_provider(), store)

    async def test_valid_token_returned_without_refresh(self) -> None:
        session = self._session()
        session.store.save(
            {"access_token": "good", "refresh_token": "r", "expires_at": time.time() + 3600}
        )
        with patch.object(session.provider, "refresh_access_token", new=AsyncMock()) as refresh:
            token = await session.get_access_token()
        self.assertEqual(token, "good")
        refresh.assert_not_awaited()

    async def test_expired_token_triggers_refresh(self) -> None:
        session = self._session()
        session.store.save(
            {"access_token": "old", "refresh_token": "r", "expires_at": time.time() - 10}
        )
        refreshed = {"access_token": "new", "expires_in": 3600}  # note: no refresh_token
        with patch.object(
            session.provider, "refresh_access_token", new=AsyncMock(return_value=refreshed)
        ):
            token = await session.get_access_token()
        self.assertEqual(token, "new")
        # Existing refresh token preserved when the provider omits it.
        self.assertEqual(session.store.load()["refresh_token"], "r")

    async def test_no_tokens_raises_401(self) -> None:
        session = self._session()
        with self.assertRaises(HTTPException) as ctx:
            await session.get_access_token()
        self.assertEqual(ctx.exception.status_code, 401)


class RouterTests(TestCase):
    def _client(self) -> tuple[TestClient, TokenSession]:
        store = TokenStore("acme")
        store._token_file = Path(tempfile.mkdtemp()) / ".acme_tokens.json"
        session = TokenSession(_provider(), store)
        app = FastAPI()
        app.include_router(build_oauth_router(session, prefix="/acme"))
        return TestClient(app), session

    def test_login_redirects_to_provider(self) -> None:
        client, _ = self._client()
        resp = client.get("/acme/login", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 307))
        self.assertTrue(resp.headers["location"].startswith("https://auth.acme.test/oauth/authorize"))

    def test_callback_exchanges_code_and_hides_tokens(self) -> None:
        client, session = self._client()
        payload = {"access_token": "a", "refresh_token": "r", "expires_in": 3600}
        with patch.object(
            session.provider, "exchange_code_for_tokens", new=AsyncMock(return_value=payload)
        ):
            resp = client.get("/acme/callback?code=abc")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["provider"], "acme")
        self.assertTrue(body["has_refresh_token"])
        self.assertNotIn("access_token", body)  # secrets never echoed to the browser
        self.assertEqual(session.store.load()["access_token"], "a")

    def test_callback_reports_provider_error(self) -> None:
        client, _ = self._client()
        resp = client.get("/acme/callback?error=access_denied")
        self.assertEqual(resp.status_code, 400)
