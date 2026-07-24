
from __future__ import annotations

import os
import threading

_BLOB_URI = os.getenv("AzureWebJobsStorage__blobServiceUri", "").strip()
_CONTAINER = os.getenv("REPORT_ARTIFACTS_CONTAINER", "report-artifacts")

# Local fallback store.
_local: dict[str, bytes] = {}
_local_lock = threading.Lock()

# Created lazily so an unreachable storage account never breaks module import,
# which would fail the whole Functions host at startup rather than just this call.
_container_client = None


def _durable() -> bool:
    return bool(_BLOB_URI)


def _blob_name(job_id: str) -> str:
    return f"task-summary/{job_id}.pdf"


def _get_container_client():
    global _container_client
    if _container_client is None:
        from azure.core.exceptions import ResourceExistsError
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient(
            account_url=_BLOB_URI, credential=DefaultAzureCredential()
        )
        client = service.get_container_client(_CONTAINER)
        try:
            client.create_container()
        except ResourceExistsError:
            pass
        _container_client = client
    return _container_client


def save_pdf(job_id: str, pdf_bytes: bytes) -> None:
    """Persist a rendered PDF against its job id."""
    if _durable():
        from azure.storage.blob import ContentSettings

        _get_container_client().upload_blob(
            name=_blob_name(job_id),
            data=pdf_bytes,
            overwrite=True,
            # Set on the blob so a direct blob URL also renders rather than
            # downloading, not just the API route below.
            content_settings=ContentSettings(
                content_type="application/pdf", content_disposition="inline"
            ),
        )
        return
    with _local_lock:
        _local[job_id] = pdf_bytes


def load_pdf(job_id: str) -> bytes | None:
    """Return the stored PDF for a job, or None when there is nothing stored."""
    if _durable():
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return _get_container_client().download_blob(_blob_name(job_id)).readall()
        except ResourceNotFoundError:
            return None
    with _local_lock:
        return _local.get(job_id)
