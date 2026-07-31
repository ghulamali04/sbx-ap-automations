"""
Read-only test endpoints for the Meeting Notes Graph integration.

These exist so you can verify, from the running API, that:
  * the app-only Graph credentials resolve and can mint a token,
  * we can reach Graph (list subscriptions — the transcript notification feed), and
  * we can actually fetch a user's online-meeting transcripts.

Every route here is a GET and does only reads. Nothing creates subscriptions,
sends mail, or mutates state.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.automations.meeting_notes import graph

router = APIRouter(prefix="/meeting-notes", tags=["meeting-notes"])


@router.get("/health")
async def health():
    """Is app-only Graph configured at all? (No network call.)"""
    return {"status": "ok", "graph_configured": graph.is_configured()}


@router.get("/graph-test")
async def graph_test():
    """Acquire an app-only Graph token. Proves client id/secret/tenant are valid."""
    if not graph.is_configured():
        raise HTTPException(
            status_code=400,
            detail="Graph is not configured. Set GRAPH_CLIENT_ID / GRAPH_CLIENT_SECRET / "
            "GRAPH_TENANT_ID (or run in Azure with a managed identity).",
        )
    try:
        info = await graph.acquire_token_info()
    except Exception as exc:  # noqa: BLE001 - surface the auth failure to the caller
        raise HTTPException(status_code=502, detail=f"Token acquisition failed: {exc}") from exc
    return {"status": "ok", **info}


@router.get("/subscriptions")
async def list_subscriptions():
    """List active Graph subscriptions — the tenant-wide transcript feed lives here."""
    try:
        subs = await graph.list_subscriptions()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"count": len(subs), "subscriptions": subs}


@router.get("/users/{user}")
async def resolve_user(user: str):
    """Resolve a user by id or UPN/email. Exercises User.Read.All."""
    try:
        return await graph.get_user(user)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/users/{user}/transcripts")
async def user_transcripts(user: str):
    """Fetch all online-meeting transcripts organised by this user.

    This is the real 'can we fetch meetings?' test. A 403 means
    OnlineMeetingTranscript.Read.All is not consented on the app registration.
    """
    try:
        u = await graph.get_user(user, select="id,displayName,mail,userPrincipalName")
        transcripts = await graph.list_user_transcripts(u["id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"user": u, "count": len(transcripts), "transcripts": transcripts}


@router.get("/users/{user}/meetings")
async def user_meetings(user: str, top: int = 20):
    """List a user's calendar meetings, newest first (includes non-transcribed ones).

    A 403 means Calendars.Read is not consented on the app registration.
    """
    try:
        u = await graph.get_user(user, select="id,displayName,mail,userPrincipalName")
        events = await graph.list_user_events(u["id"], top=top)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"user": u, "count": len(events), "meetings": events}


@router.get("/transcript/content")
async def transcript_content(
    resource: str = Query(
        ...,
        description="A callTranscript resource path or absolute Graph URL, e.g. "
        "users/{id}/onlineMeetings/{mid}/transcripts/{tid}",
    ),
):
    """Fetch a single transcript's body as WebVTT text."""
    try:
        vtt = await graph.get_transcript_content(resource)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"resource": resource, "vtt": vtt}
