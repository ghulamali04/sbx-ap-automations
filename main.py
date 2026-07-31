"""
Standalone Microsoft Graph connectivity smoke test for the Meeting Notes pipeline.

Run this to confirm, without booting the whole automation, that:
  1. the app-only Graph credentials resolve and can mint a token, and
  2. we can actually reach Graph and fetch the meeting/transcript data the
     pipeline depends on.

It mirrors the auth resolution in backend/api/automations/meeting_notes/graph.py:
  * GRAPH_CLIENT_ID / GRAPH_CLIENT_SECRET / GRAPH_TENANT_ID  -> ClientSecretCredential
  * otherwise DefaultAzureCredential (Function App managed identity, or `az login`)

Usage (from the repo root, using the backend venv):
    backend/.venv/bin/python main.py
    backend/.venv/bin/python main.py <userIdOrUPN>   # also fetch that user's meetings

Nothing here is destructive: every call is a read.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parent
_LOCAL_SETTINGS = _REPO_ROOT / "backend" / "local.settings.json"

_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def _load_local_settings() -> None:
    """Merge backend/local.settings.json "Values" into os.environ (real env wins)."""
    if not _LOCAL_SETTINGS.exists():
        print(f"  (no local.settings.json at {_LOCAL_SETTINGS}; relying on real env)")
        return
    try:
        data = json.loads(_LOCAL_SETTINGS.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  ! could not parse {_LOCAL_SETTINGS}: {exc}")
        return
    for key, value in data.get("Values", {}).items():
        os.environ.setdefault(key, str(value))


def _graph_base() -> str:
    return os.getenv("GRAPH_API_BASE", "https://graph.microsoft.com/v1.0").rstrip("/")


def _credential():
    """Resolve app-only credentials, same precedence as the pipeline's graph.py."""
    client_id = os.getenv("GRAPH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GRAPH_CLIENT_SECRET", "").strip()
    tenant_id = os.getenv("GRAPH_TENANT_ID", "").strip()
    if client_id and client_secret and tenant_id:
        from azure.identity import ClientSecretCredential

        print(f"  auth: ClientSecretCredential (tenant {tenant_id}, client {client_id})")
        return ClientSecretCredential(
            tenant_id=tenant_id, client_id=client_id, client_secret=client_secret
        )

    from azure.identity import DefaultAzureCredential

    print("  auth: DefaultAzureCredential (managed identity / az login)")
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def _acquire_token() -> str:
    token = _credential().get_token(_GRAPH_SCOPE)
    import datetime as _dt

    expires = _dt.datetime.fromtimestamp(token.expires_on, _dt.timezone.utc)
    print(f"  OK  token acquired, expires {expires.isoformat()}")
    return token.token


async def _get(client: httpx.AsyncClient, url: str, token: str, **kwargs) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
    return await client.get(url, headers=headers, **kwargs)


async def _check_subscriptions(client: httpx.AsyncClient, token: str) -> None:
    """List active Graph subscriptions — the tenant-wide transcript feed lives here."""
    print("\n[2] GET /subscriptions  (the meeting-transcript notification feed)")
    resp = await _get(client, f"{_graph_base()}/subscriptions", token)
    if resp.status_code != 200:
        print(f"  ! HTTP {resp.status_code}: {resp.text[:300]}")
        return
    subs = resp.json().get("value", [])
    print(f"  OK  {len(subs)} active subscription(s)")
    for sub in subs:
        print(
            f"      - {sub.get('resource')}  "
            f"(changeType={sub.get('changeType')}, expires={sub.get('expirationDateTime')})"
        )


async def _fetch_meetings_for_user(client: httpx.AsyncClient, token: str, user: str) -> None:
    """Concretely 'fetch meetings': resolve the user, then their online-meeting transcripts."""
    print(f"\n[3] Fetch meetings/transcripts for user: {user}")

    resp = await _get(
        client,
        f"{_graph_base()}/users/{user}",
        token,
        params={"$select": "id,displayName,mail,userPrincipalName"},
    )
    if resp.status_code != 200:
        print(f"  ! user lookup HTTP {resp.status_code}: {resp.text[:300]}")
        return
    u = resp.json()
    user_id = u.get("id")
    print(f"  OK  resolved {u.get('displayName')} <{u.get('mail') or u.get('userPrincipalName')}> id={user_id}")

    # getAllTranscripts returns every transcript for meetings this user organized.
    resp = await _get(
        client,
        f"{_graph_base()}/users/{user_id}/onlineMeetings/getAllTranscripts",
        token,
    )
    if resp.status_code != 200:
        print(f"  ! getAllTranscripts HTTP {resp.status_code}: {resp.text[:300]}")
        return
    transcripts = resp.json().get("value", [])
    print(f"  OK  {len(transcripts)} transcript(s) available for this user")
    for t in transcripts[:5]:
        print(f"      - transcript {t.get('id')}  meeting={t.get('meetingId')}  created={t.get('createdDateTime')}")


async def _run(target_user: str | None) -> int:
    print("=== Microsoft Graph connectivity check (Meeting Notes) ===")

    print("\n[0] Loading config")
    _load_local_settings()
    if not (os.getenv("GRAPH_CLIENT_ID") and os.getenv("GRAPH_CLIENT_SECRET") and os.getenv("GRAPH_TENANT_ID")):
        if not (os.getenv("WEBSITE_HOSTNAME") or os.getenv("IDENTITY_ENDPOINT")):
            print(
                "  ! No GRAPH_CLIENT_ID/SECRET/TENANT_ID found and not running in Azure.\n"
                "    Set them in backend/local.settings.json or the environment."
            )
            return 2

    print("\n[1] Acquiring app-only Graph token")
    try:
        token = await asyncio.to_thread(_acquire_token)
    except Exception as exc:  # noqa: BLE001 - surface any auth failure plainly
        print(f"  ! token acquisition FAILED: {type(exc).__name__}: {exc}")
        return 1

    async with httpx.AsyncClient(timeout=30) as client:
        await _check_subscriptions(client, token)
        user = target_user or os.getenv("MEETING_NOTES_MAIL_SENDER", "").strip()
        if user:
            await _fetch_meetings_for_user(client, token, user)
        else:
            print(
                "\n[3] Skipped per-user meeting fetch (no user given).\n"
                "    Pass a user id/UPN as an argument, or set MEETING_NOTES_MAIL_SENDER,\n"
                "    to fetch that user's online-meeting transcripts."
            )

    print("\n=== Connection check complete ===")
    return 0


if __name__ == "__main__":
    arg_user = sys.argv[1] if len(sys.argv) > 1 else None
    raise SystemExit(asyncio.run(_run(arg_user)))
