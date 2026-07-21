"""
HTTP endpoints for the completion-overview report.

Async pattern (spec §6.3 / §9.2): POST returns 202 immediately with a Location
header pointing at the status URL; the caller (Power Automate's HTTP action) polls
that until the job reports completed/failed.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from api.automations.completion_overview import power_automate, queue
from api.automations.completion_overview.jobs import create_job, get_job
from api.automations.completion_overview.models import (
    JobResult,
    ReportAccepted,
    ReportRequest,
)

router = APIRouter(prefix="/reports/completion", tags=["completion-overview"])


@router.post("", status_code=202, response_model=ReportAccepted)
async def start_report(req: ReportRequest | None = None, *, request: Request, response: Response):
    """Queue a report run and return 202 + a Location header to poll.

    An empty body is valid: it selects the latest BAS and IAS projects by default.
    """
    req = req or ReportRequest()
    if not req.projects_include and not req.name_filters:
        raise HTTPException(
            status_code=400,
            detail="Provide projects_include, or name_filters to resolve by name.",
        )
    # Validate caller-supplied destinations up front (spec §6.7) so bad input fails
    # fast with 400 rather than mid-way through a background job.
    webhook = req.resolved_webhook()
    if webhook:
        power_automate.validate_webhook_url(webhook)
    elif not req.dry_run:
        raise HTTPException(
            status_code=400,
            detail="No webhook configured. Set POWER_AUTOMATE_WEBHOOK_URL, pass "
                   "webhook_url, or send dry_run=true to render without delivering.",
        )
    job_id = create_job()
    queue.dispatch_report(job_id, req)

    status_url = str(request.url_for("get_report_status", job_id=job_id))
    response.headers["Location"] = status_url
    return ReportAccepted(job_id=job_id, status="queued", status_url=status_url)


@router.get("/{job_id}", name="get_report_status", response_model=JobResult)
async def get_report_status(job_id: str):
    """Poll a queued report; returns queued | running | completed | failed."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    return job
