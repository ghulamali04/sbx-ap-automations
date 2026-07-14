"""
In-process job store for the async (202 + Location) pattern.

The report can take longer than Power Automate's 120s sync cap and Azure's 230s
HTTP-response cap (spec §6.3 / §9.2), so the endpoint returns 202 immediately and
runs the work in the background; the caller polls the status URL until it finishes.

This in-memory store is fine for a single-instance local/dev run. On Azure Flex
Consumption (multiple instances, work must survive the response), move the queue to
a durable/queue trigger — the HTTP contract here stays the same.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable

from api.automations.completion_overview.models import JobResult

_jobs: dict[str, JobResult] = {}


def create_job() -> str:
    job_id = uuid.uuid4().hex
    _jobs[job_id] = JobResult(job_id=job_id, status="queued")
    return job_id


def get_job(job_id: str) -> JobResult | None:
    return _jobs.get(job_id)


def _set(job_id: str, **fields) -> None:
    job = _jobs.get(job_id)
    if job:
        _jobs[job_id] = job.model_copy(update=fields)


def start_job(job_id: str, work: Callable[[], Awaitable[JobResult]]) -> None:
    """Run `work` in the background, recording its result/failure on the job."""

    async def runner() -> None:
        _set(job_id, status="running")
        try:
            result = await work()
            result.job_id = job_id
            result.status = "completed"
            _jobs[job_id] = result
        except Exception as exc:  # noqa: BLE001 — surface any failure on the job
            _set(job_id, status="failed", error=str(exc))

    asyncio.create_task(runner())
