
from __future__ import annotations

import os
import threading
import uuid

from api.automations.meeting_notes.models import NoteJobResult

_PARTITION = "meeting-notes"

_TABLE_URI = os.getenv("AzureWebJobsStorage__tableServiceUri", "").strip()
_TABLE_NAME = os.getenv("MEETING_NOTES_JOBS_TABLE", "meetingnotesjobs")

_local: dict[str, NoteJobResult] = {}
_local_lock = threading.Lock()

_table_client = None


def _durable() -> bool:
    return bool(_TABLE_URI)


def _get_table_client():
    global _table_client
    if _table_client is None:
        from azure.core.exceptions import ResourceExistsError
        from azure.data.tables import TableServiceClient
        from azure.identity import DefaultAzureCredential

        service = TableServiceClient(
            endpoint=_TABLE_URI, credential=DefaultAzureCredential()
        )
        try:
            service.create_table(_TABLE_NAME)
        except ResourceExistsError:
            pass
        _table_client = service.get_table_client(_TABLE_NAME)
    return _table_client


def create_job(transcript_resource: str = "") -> str:
    job_id = uuid.uuid4().hex
    save_job(
        NoteJobResult(
            job_id=job_id, status="queued", transcript_resource=transcript_resource
        )
    )
    return job_id


def save_job(result: NoteJobResult) -> None:
    if _durable():
        _get_table_client().upsert_entity(
            {
                "PartitionKey": _PARTITION,
                "RowKey": result.job_id,
                "status": result.status,
                "payload": result.model_dump_json(),
            }
        )
        return
    with _local_lock:
        _local[result.job_id] = result


def get_job(job_id: str) -> NoteJobResult | None:
    if _durable():
        from azure.core.exceptions import ResourceNotFoundError

        try:
            entity = _get_table_client().get_entity(_PARTITION, job_id)
        except ResourceNotFoundError:
            return None
        return NoteJobResult.model_validate_json(entity["payload"])
    with _local_lock:
        return _local.get(job_id)


def set_status(job_id: str, status: str, error: str | None = None) -> None:
    job = get_job(job_id)
    if job is None:
        return
    job.status = status
    if error is not None:
        job.error = error
    save_job(job)
