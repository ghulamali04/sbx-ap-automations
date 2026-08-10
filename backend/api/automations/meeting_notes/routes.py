
from __future__ import annotations

import logging
import os
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from api.automations.meeting_notes import graph, jobs, queue, subscriptions
from api.automations.meeting_notes.models import (
    ChangeNotificationCollection,
    NoteJobRequest,
    NoteJobResult,
    SubscriptionInfo,
    TranscriptFetchIn,
)

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/meeting-notes", tags=["meeting-notes"])


def _dry_run_default() -> bool:
    return os.getenv("MEETING_NOTES_DRY_RUN", "false").strip().lower() in ("1", "true", "yes")


def _client_state_ok(received: str | None) -> bool:
    """Constant-time check that the notification carries our secret clientState."""
    expected = subscriptions.client_state()
    if not expected:
        return True  # no secret configured -> nothing to verify
    return bool(received) and secrets.compare_digest(received, expected)


def require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    """Gate the admin/status endpoints behind a shared secret.

    The Function App itself runs with AuthLevel.ANONYMOUS (api/main.py's ASGI
    app has no per-route auth otherwise), so without this, anyone who can reach
    the deployed URL could create/list Graph subscriptions or read a job's
    organiser email. No key configured -> fail closed once a webhook is set up
    for real use; local dev with nothing configured stays open for convenience.
    """
    expected = os.getenv("MEETING_NOTES_ADMIN_KEY", "").strip()
    if not expected:
        return
    if not x_admin_key or not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Admin-Key header.")


# ---------- Graph webhook ----------

@router.post("/notifications")
async def notifications(request: Request, validationToken: str | None = None):
    
    if validationToken is not None:
        return PlainTextResponse(content=validationToken, status_code=200)

    try:
        body = await request.json()
        collection = ChangeNotificationCollection.model_validate(body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid notification body: {exc}")

    accepted = 0
    for note in collection.value:
        if not _client_state_ok(note.clientState):
            _LOG.warning("Dropped notification with bad clientState (sub %s)", note.subscriptionId)
            continue
        if not note.resource:
            continue
        job_id = jobs.create_job(note.resource)
        queue.dispatch_note(
            job_id,
            NoteJobRequest(
                transcript_resource=note.resource,
                subscription_id=note.subscriptionId,
                tenant_id=note.tenantId,
                dry_run=_dry_run_default(),
            ),
        )
        accepted += 1

    # 202: accepted for async processing. Graph only needs a prompt 2xx.
    return Response(status_code=202)


# ---------- Graph lifecycle ----------

@router.post("/lifecycle")
async def lifecycle(
    request: Request,
    background: BackgroundTasks,
    validationToken: str | None = None,
):
    
    if validationToken is not None:
        return PlainTextResponse(content=validationToken, status_code=200)

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    events = {item.get("lifecycleEvent") for item in body.get("value", []) if isinstance(item, dict)}
    if events & {"reauthorizationRequired", "subscriptionRemoved", "missed"}:
        _LOG.info("Lifecycle event(s) %s -> scheduling subscription renewal", events)
        background.add_task(_safe_renew)

    return Response(status_code=202)


async def _safe_renew() -> None:
    try:
        await subscriptions.renew_due()
    except Exception as exc:  # noqa: BLE001 - a lifecycle handler must not throw
        _LOG.error("Subscription renewal from lifecycle event failed: %s", exc)


# ---------- Subscription admin ----------

@router.post(
    "/subscriptions",
    response_model=SubscriptionInfo,
    status_code=201,
    dependencies=[Depends(require_admin_key)],
)
async def create_subscription():
    """Create the tenant-wide transcript subscription (run once by an admin)."""
    try:
        return await subscriptions.create()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Subscription create failed: {exc}")


@router.get(
    "/subscriptions",
    response_model=list[SubscriptionInfo],
    dependencies=[Depends(require_admin_key)],
)
async def get_subscriptions():
    """List the transcript subscriptions this app owns."""
    try:
        return await subscriptions.list_ours()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Subscription list failed: {exc}")


@router.post(
    "/subscriptions/renew",
    response_model=list[SubscriptionInfo],
    dependencies=[Depends(require_admin_key)],
)
async def renew_subscriptions():
    """Renew any transcript subscription near expiry (or create one if missing)."""
    try:
        return await subscriptions.renew_due()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Subscription renewal failed: {exc}")


# ---------- Diagnostics (Graph read-only, matches the Insomnia collection) ----------
# Gated behind the same X-Admin-Key as the rest of the module — these expose
# organiser identity and transcript content, not just status.

@router.get("/users/{user}", dependencies=[Depends(require_admin_key)])
async def resolve_user(user: str):
    """Resolve a user by id or UPN/email. Exercises User.Read.All."""
    try:
        return await graph.get_user(user)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/users/{user}/transcripts", dependencies=[Depends(require_admin_key)])
async def user_transcripts(user: str):
    """List all online-meeting transcripts organised by this user (getAllTranscripts)."""
    try:
        transcripts = await graph.list_transcripts_for_user(user)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))
    return {"count": len(transcripts), "transcripts": transcripts}


@router.post("/transcript/fetch", dependencies=[Depends(require_admin_key)])
async def fetch_transcript(body: TranscriptFetchIn):
    """Fetch a transcript's WebVTT text from its transcriptContentUrl (or resource path)."""
    try:
        vtt_text = await graph.get_transcript_content(body.content_url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))
    return {"length": len(vtt_text), "vtt": vtt_text}


# ---------- Job status ----------

@router.get(
    "/{job_id}",
    name="get_meeting_note_status",
    response_model=NoteJobResult,
    dependencies=[Depends(require_admin_key)],
)
async def get_status(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    return job
