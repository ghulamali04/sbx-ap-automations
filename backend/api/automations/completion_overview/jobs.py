"""
Durable job store for the completion-overview report.

Replaces the in-process dict this module used to hold, which could not work on Flex
Consumption: instances are ephemeral and scale out, so a job created while serving
the POST was invisible to whichever instance served the status poll (404), and it
vanished entirely when the instance scaled in.

Backend is chosen at runtime:

  * AzureWebJobsStorage__tableServiceUri set (sandbox / prod) -> Azure Table Storage,
    reached with the Function App's managed identity. Job records survive restarts,
    scale-out and scale-to-zero.

  * unset (local dev / tests) -> an in-process dict, as before, so `func start` and
    uvicorn keep working with no storage account.

Records are small — JobResult holds chart *metadata* only (the PNG bytes go to Power
Automate and are not retained), so a job comfortably fits one table entity.
"""
from __future__ import annotations

import os
import threading
import uuid

from api.automations.completion_overview.models import JobResult

# Every report job shares one partition: the set is small and always fetched by id.
_PARTITION = "report"

_TABLE_URI = os.getenv("AzureWebJobsStorage__tableServiceUri", "").strip()
_TABLE_NAME = os.getenv("REPORT_JOBS_TABLE", "reportjobs")

# Local fallback store.
_local: dict[str, JobResult] = {}
_local_lock = threading.Lock()

# Created lazily so a missing/unreachable storage account never breaks module import,
# which would fail the whole Functions host at startup rather than just this call.
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


def create_job() -> str:
    """Create a queued job record and return its id."""
    job_id = uuid.uuid4().hex
    save_job(JobResult(job_id=job_id, status="queued"))
    return job_id


def save_job(result: JobResult) -> None:
    """Persist (insert or replace) the whole job record."""
    if _durable():
        _get_table_client().upsert_entity(
            {
                "PartitionKey": _PARTITION,
                "RowKey": result.job_id,
                "status": result.status,   # duplicated as a column for easy querying
                "payload": result.model_dump_json(),
            }
        )
        return
    with _local_lock:
        _local[result.job_id] = result


def get_job(job_id: str) -> JobResult | None:
    if _durable():
        from azure.core.exceptions import ResourceNotFoundError

        try:
            entity = _get_table_client().get_entity(_PARTITION, job_id)
        except ResourceNotFoundError:
            return None
        return JobResult.model_validate_json(entity["payload"])
    with _local_lock:
        return _local.get(job_id)


def set_status(job_id: str, status: str, error: str | None = None) -> None:
    """Update just the status (and optionally the error) of an existing job."""
    job = get_job(job_id)
    if job is None:
        return
    job.status = status
    if error is not None:
        job.error = error
    save_job(job)
