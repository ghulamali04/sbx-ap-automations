
from __future__ import annotations

import asyncio
import json
import os

from api.automations.meeting_notes import jobs, service
from api.automations.meeting_notes.models import NoteJobRequest

QUEUE_NAME = os.getenv("MEETING_NOTES_QUEUE_NAME", "meeting-notes-jobs")

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
            message_encode_policy=TextBase64EncodePolicy(),
        )
        try:
            client.create_queue()
        except ResourceExistsError:
            pass
        _queue_client = client
    return _queue_client


def dispatch_note(job_id: str, req: NoteJobRequest) -> None:
    """Hand the job to the queue (cloud) or an in-process task (local).

    The webhook must return within Graph's short response window, so the actual
    fetch/summarise/mail work always happens off the request thread.
    """
    if _durable():
        _get_queue_client().send_message(
            json.dumps({"job_id": job_id, "request": req.model_dump(mode="json")})
        )
        return
    asyncio.create_task(run_job(job_id, req))


async def process_message(body: str) -> None:
    """Entry point for the queue trigger — decode one message and run it."""
    data = json.loads(body)
    await run_job(data["job_id"], NoteJobRequest.model_validate(data["request"]))


async def run_job(job_id: str, req: NoteJobRequest) -> None:
    jobs.set_status(job_id, "running")
    try:
        result = await service.run_note_job(req, job_id=job_id)
        result.job_id = job_id
        result.status = "failed" if result.error and not result.delivered else "completed"
        jobs.save_job(result)
    except Exception as exc:  # noqa: BLE001 — surface any failure on the job record
        jobs.set_status(job_id, "failed", error=str(exc))
