"""
HTTP endpoints for the head-client Task Summary PDF report.

Same async pattern as completion_overview/routes.py: POST returns 202
immediately with a Location header pointing at the status URL; the caller
polls that until the job reports completed/failed. Kept async because a
Zoho scan across many projects, PDF render, and Power Automate delivery can
comfortably outrun Power Automate's 120s synchronous-call cap.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from api.automations.completion_overview.power_automate import validate_webhook_url
from api.automations.task_summary_report import artifacts, queue
from api.automations.task_summary_report.jobs import create_job, get_job
from api.automations.task_summary_report.models import JobResult, ReportAccepted, ReportRequest

router = APIRouter(prefix="/reports/task-summary", tags=["task-summary-report"])


@router.post("", status_code=202, response_model=ReportAccepted)
async def start_report(req: ReportRequest, *, request: Request, response: Response):
    """Queue a Task Summary PDF run for one head client and return 202 + a Location to poll."""
    webhook = req.resolved_webhook()
    if webhook:
        validate_webhook_url(webhook)
    elif not req.dry_run:
        raise HTTPException(
            status_code=400,
            detail="No webhook configured. Set POWER_AUTOMATE_WEBHOOK_URL, pass "
                   "webhook_url, or send dry_run=true to render without delivering.",
        )
    job_id = create_job()
    queue.dispatch_report(job_id, req)

    status_url = str(request.url_for("get_task_summary_status", job_id=job_id))
    response.headers["Location"] = status_url
    return ReportAccepted(job_id=job_id, status="queued", status_url=status_url)


@router.get("/{job_id}", name="get_task_summary_status", response_model=JobResult)
async def get_task_summary_status(job_id: str, *, request: Request):
    """Poll a queued report; returns queued | running | completed | failed.

    Once the PDF has been rendered, `pdf_url` points at a link that opens it in
    the browser. It is filled in here rather than stored so it always names the
    host the caller actually reached (localhost, sandbox, or prod).
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    if job.bytes_pdf:
        job.pdf_url = str(request.url_for("view_task_summary_pdf", job_id=job_id))
    return job


@router.get("/{job_id}/pdf", name="view_task_summary_pdf", response_class=Response)
async def view_task_summary_pdf(job_id: str, download: bool = False):
    """Return the rendered PDF itself.

    Served `inline` so a browser renders it in place; `?download=true` forces a
    save-as instead, under the same filename the Power Automate flow receives.
    """
    pdf_bytes = artifacts.load_pdf(job_id)
    if pdf_bytes is None:
        job = get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job_id.")
        raise HTTPException(
            status_code=404,
            detail=f"No PDF stored for this job (status={job.status!r}). "
                   "It is still running, it failed, or storage was unavailable.",
        )
    job = get_job(job_id)
    filename = (job.filename if job else "") or f"task-summary-{job_id}.pdf"
    disposition = "attachment" if download else "inline"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )
