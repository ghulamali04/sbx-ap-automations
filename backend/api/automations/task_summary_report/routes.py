
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from api.automations.task_summary_report import artifacts, power_automate, queue
from api.automations.task_summary_report.jobs import create_job, get_job
from api.automations.task_summary_report.models import JobResult, ReportAccepted, ReportRequest

router = APIRouter(prefix="/reports/task-summary", tags=["task-summary-report"])


@router.post("", status_code=202, response_model=ReportAccepted)
async def start_report(req: ReportRequest, *, request: Request, response: Response):
    """Queue a Task Summary PDF run for one head client and return 202 + a Location to poll."""
    webhook = req.resolved_webhook()
    if webhook:
        power_automate.validate_webhook_url(webhook)
    elif not req.dry_run:
        raise HTTPException(
            status_code=400,
            detail="No webhook configured. Set TASK_SUMMARY_WEBHOOK_URL (or "
                   "POWER_AUTOMATE_WEBHOOK_URL), pass webhook_url, or send "
                   "dry_run=true to render without delivering.",
        )
    if not req.dry_run and not (req.requestor_email or "").strip():
        raise HTTPException(
            status_code=400,
            detail="requestor_email is required when the PDF will be delivered.",
        )
    job_id = create_job()
    queue.dispatch_report(job_id, req)

    status_url = str(request.url_for("get_task_summary_status", job_id=job_id))
    response.headers["Location"] = status_url
    return ReportAccepted(job_id=job_id, status="queued", status_url=status_url)


@router.get("/{job_id}", name="get_task_summary_status", response_model=JobResult)
async def get_task_summary_status(job_id: str, *, request: Request):
   
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    if job.bytes_pdf:
        job.pdf_url = str(request.url_for("view_task_summary_pdf", job_id=job_id))
    return job


@router.get("/{job_id}/pdf", name="view_task_summary_pdf", response_class=Response)
async def view_task_summary_pdf(job_id: str, download: bool = False):
  
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
