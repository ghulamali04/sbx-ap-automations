
from __future__ import annotations

import os
import threading

_BLOB_URI = os.getenv("AzureWebJobsStorage__blobServiceUri", "").strip()
_CONTAINER = os.getenv("REPORT_ARTIFACTS_CONTAINER", "report-artifacts")

# Local fallback store.
_local: dict[str, str] = {}
_local_lock = threading.Lock()

# Same pattern, separate store, for the PDF rendering of the same note.
_local_pdf: dict[str, bytes] = {}
_local_pdf_lock = threading.Lock()

# Created lazily so an unreachable storage account never breaks module import.
_container_client = None


def _durable() -> bool:
    return bool(_BLOB_URI)


def _blob_name(job_id: str) -> str:
    return f"meeting-notes/{job_id}.html"


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


def save_note(job_id: str, html: str) -> None:
    """Persist a rendered HTML note against its job id."""
    if _durable():
        from azure.storage.blob import ContentSettings

        _get_container_client().upload_blob(
            name=_blob_name(job_id),
            data=html.encode("utf-8"),
            overwrite=True,
            content_settings=ContentSettings(
                content_type="text/html; charset=utf-8", content_disposition="inline"
            ),
        )
        return
    with _local_lock:
        _local[job_id] = html


def load_note(job_id: str) -> str | None:
    """Return the stored HTML note for a job, or None when nothing is stored."""
    if _durable():
        from azure.core.exceptions import ResourceNotFoundError

        try:
            data = _get_container_client().download_blob(_blob_name(job_id)).readall()
            return data.decode("utf-8")
        except ResourceNotFoundError:
            return None
    with _local_lock:
        return _local.get(job_id)


def _blob_name_pdf(job_id: str) -> str:
    return f"meeting-notes/{job_id}.pdf"


def save_note_pdf(job_id: str, pdf_bytes: bytes) -> None:
    """Persist the PDF rendering of a note against its job id."""
    if _durable():
        from azure.storage.blob import ContentSettings

        _get_container_client().upload_blob(
            name=_blob_name_pdf(job_id),
            data=pdf_bytes,
            overwrite=True,
            content_settings=ContentSettings(
                content_type="application/pdf", content_disposition="inline"
            ),
        )
        return
    with _local_pdf_lock:
        _local_pdf[job_id] = pdf_bytes


def load_note_pdf(job_id: str) -> bytes | None:
    """Return the stored PDF note for a job, or None when nothing is stored."""
    if _durable():
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return _get_container_client().download_blob(_blob_name_pdf(job_id)).readall()
        except ResourceNotFoundError:
            return None
    with _local_pdf_lock:
        return _local_pdf.get(job_id)
