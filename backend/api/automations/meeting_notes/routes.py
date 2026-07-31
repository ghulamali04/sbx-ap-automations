
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from api.automations.meeting_notes import jobs, queue, subscriptions, artifacts
from api.automations.meeting_notes.models import (
    ChangeNotificationCollection,
    NoteJobRequest,
    NoteJobResult,
    SubscriptionInfo,
)

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/meeting-notes", tags=["meeting-notes"])


def _dry_run_default() -> bool:
    return os.getenv("MEETING_NOTES_DRY_RUN", "false").strip().lower() in ("1", "true", "yes")


def _client_state_ok(received: str | None) -> bool:
    """Constant-ish check that the notification carries our secret clientState."""
    expected = subscriptions.client_state()
    if not expected:
        return True  # no secret configured -> nothing to verify
    return received == expected


# ---------- Graph webhook ----------

@router.post("/notifications")
async def notifications(request: Request, validationToken: str | None = None):
    """Receive transcript-created notifications from the tenant-wide subscription.

    Two shapes arrive here:
      * Subscription validation — Graph calls with ?validationToken=... and no
        body, and expects the raw token echoed as text/plain within 10 seconds.
      * Real notifications — a JSON batch. We validate clientState, enqueue one
        job per transcript, and return fast; all fetching/summarising happens on
        the queue so we never miss Graph's short response window.
    """
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
    """Handle subscription lifecycle events (reauthorization, removal, missed).

    reauthorizationRequired and subscriptionRemoved both mean the pipeline is
    about to stop receiving notifications, which silently loses meetings — so we
    renew/recreate immediately, in the background to keep the response prompt.
    """
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

@router.post("/subscriptions", response_model=SubscriptionInfo, status_code=201)
async def create_subscription():
    """Create the tenant-wide transcript subscription (run once by an admin)."""
    try:
        return await subscriptions.create()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Subscription create failed: {exc}")


@router.get("/subscriptions", response_model=list[SubscriptionInfo])
async def get_subscriptions():
    """List the transcript subscriptions this app owns."""
    try:
        return await subscriptions.list_ours()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Subscription list failed: {exc}")


@router.post("/subscriptions/renew", response_model=list[SubscriptionInfo])
async def renew_subscriptions():
    """Renew any transcript subscription near expiry (or create one if missing)."""
    try:
        return await subscriptions.renew_due()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Subscription renewal failed: {exc}")


# ---------- Job status / note viewing ----------

@router.get("/{job_id}", name="get_meeting_note_status", response_model=NoteJobResult)
async def get_status(job_id: str, *, request: Request):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    if artifacts.load_note(job_id) is not None:
        job.note_url = str(request.url_for("view_meeting_note", job_id=job_id))
    return job


@router.get("/{job_id}/note", name="view_meeting_note", response_class=Response)
async def view_note(job_id: str):
    html = artifacts.load_note(job_id)
    if html is None:
        job = jobs.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job_id.")
        raise HTTPException(
            status_code=404,
            detail=f"No note stored for this job (status={job.status!r}).",
        )
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get("/{job_id}/note.pdf", name="view_meeting_note_pdf", response_class=Response)
async def view_note_pdf(job_id: str):
    pdf_bytes = artifacts.load_note_pdf(job_id)
    if pdf_bytes is None:
        job = jobs.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job_id.")
        raise HTTPException(
            status_code=404,
            detail=f"No PDF stored for this job (status={job.status!r}).",
        )
    return Response(content=pdf_bytes, media_type="application/pdf")
