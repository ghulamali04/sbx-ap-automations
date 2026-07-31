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

import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

from api.automations.meeting_notes import graph, subscriptions

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/meeting-notes", tags=["meeting-notes"])


class TranscriptFetchIn(BaseModel):
    # The transcriptContentUrl returned by getAllTranscripts (already ends in /content),
    # or a transcript resource path. Pass in the body so the long URL needs no encoding.
    content_url: str


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


@router.post("/subscriptions", status_code=201)
async def create_subscription():
    """Create the tenant-wide transcript subscription.

    Graph validates MEETING_NOTES_NOTIFICATION_URL synchronously here: it POSTs a
    validationToken to that URL, which the /notifications route below echoes back.
    So the receiver must be publicly reachable *before* this call, or you get
    "Subscription validation request failed".
    """
    try:
        body = subscriptions.subscription_body()
        created = await graph.create_subscription(body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return created


@router.delete("/subscriptions/{subscription_id}")
async def delete_subscription(subscription_id: str):
    """Delete a subscription (cleanup / re-create after changing the notification URL)."""
    try:
        await graph.delete_subscription(subscription_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"deleted": subscription_id}


@router.post("/notifications")
async def notifications(request: Request):
    """Receive transcript-created change notifications from Graph.

    Two shapes:
      * Validation handshake (subscription create/renew): Graph sends
        ?validationToken=... and expects it echoed back verbatim as text/plain
        with 200 within ~10s.
      * Real notifications: a JSON body with a `value` array; each item carries the
        transcript `resource` path (no content, since includeResourceData=false).
    """
    token = request.query_params.get("validationToken")
    if token is not None:
        return Response(content=token, media_type="text/plain")

    payload = await request.json()
    expected = subscriptions.client_state()
    resources: list[str] = []
    for note in payload.get("value", []):
        if expected and note.get("clientState") != expected:
            _LOG.warning("meeting-notes: notification with bad clientState ignored")
            continue
        resources.append(note.get("resource"))
    # For now just log what arrived — the summarize/email steps are out of scope.
    _LOG.info("meeting-notes: %d transcript notification(s): %s", len(resources), resources)
    return Response(status_code=202)


@router.post("/lifecycle")
async def lifecycle(request: Request):
    """Receive lifecycle notifications (reauthorizationRequired / subscriptionRemoved).

    Same validation handshake as /notifications. Real production would renew or
    re-create the subscription here; for now it logs.
    """
    token = request.query_params.get("validationToken")
    if token is not None:
        return Response(content=token, media_type="text/plain")

    payload = await request.json()
    _LOG.info("meeting-notes lifecycle event(s): %s", payload.get("value"))
    return Response(status_code=202)


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


@router.post("/transcript/fetch")
async def fetch_transcript(body: TranscriptFetchIn):
    """Fetch a transcript's WebVTT text from its transcriptContentUrl.

    POST the long content URL in the body (no query-string encoding needed). On
    failure the exact Graph status + body is returned in `detail` so you can see
    the real error (e.g. the 403 Application Access Policy message).
    """
    try:
        vtt = await graph.get_transcript_content(body.content_url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"length": len(vtt), "vtt": vtt}


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
