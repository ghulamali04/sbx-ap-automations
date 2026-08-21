
from __future__ import annotations

import asyncio
import json
import os

from api.automations.completion_overview import jobs, service
from api.automations.completion_overview.models import ReportRequest

QUEUE_NAME = os.getenv("REPORT_QUEUE_NAME", "report-jobs")

_QUEUE_URI = os.getenv("AzureWebJobsStorage__queueServiceUri", "").strip()

_queue_client = None


def _durable() -> bool:
    return bool(_QUEUE_URI)


def _get_queue_client():
    global _queue_client
    if _queue_client is None:
        from azure.core.exceptions import ResourceExistsError
        from azure.identity import DefaultAzureCredential
        from azure.storage.queue import QueueClient, TextBase64EncodePolicy

        client = QueueClient(
            account_url=_QUEUE_URI,
            queue_name=QUEUE_NAME,
            credential=DefaultAzureCredential(),
            # The Functions queue trigger expects base64-encoded message text; the
            # storage SDK sends raw text by default, which the host fails to read.
            message_encode_policy=TextBase64EncodePolicy(),
        )
        try:
            client.create_queue()
        except ResourceExistsError:
            pass
        _queue_client = client
    return _queue_client


def dispatch_report(job_id: str, req: ReportRequest) -> None:
    """Hand the job to the queue (cloud) or an in-process task (local)."""
    if _durable():
        _get_queue_client().send_message(
            json.dumps({"job_id": job_id, "request": req.model_dump(mode="json")})
        )
        return
    asyncio.create_task(run_job(job_id, req))


async def process_message(body: str) -> None:
    """Entry point for the queue trigger — decode one message and run it."""
    data = json.loads(body)
    await run_job(data["job_id"], ReportRequest.model_validate(data["request"]))


async def run_job(job_id: str, req: ReportRequest) -> None:
 
    jobs.set_status(job_id, "running")
    try:
        result = await service.run_report(req)
        result.job_id = job_id
        result.status = "completed"
        jobs.save_job(result)
    except Exception as exc:  # noqa: BLE001 — surface any failure on the job record
        jobs.set_status(job_id, "failed", error=str(exc))