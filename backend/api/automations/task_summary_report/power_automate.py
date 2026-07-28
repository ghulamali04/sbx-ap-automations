
from __future__ import annotations

import base64
import os
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException


def _allowed_hosts() -> list[str]:
    raw = os.getenv("TASK_SUMMARY_ALLOWED_HOSTS") or os.getenv(
        "POWER_AUTOMATE_ALLOWED_HOSTS", ""
    )
    return [host.strip().lower() for host in raw.split(",") if host.strip()]


def validate_webhook_url(url: str) -> None:
    """Reject webhook URLs outside the configured HTTPS allowlist."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="webhook_url must be an absolute https URL.",
        )
    host = (parsed.hostname or "").lower()
    allowed = _allowed_hosts()
    if allowed and host not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"webhook_url host '{host}' is not allowed.",
        )


async def deliver_pdf(
    webhook_url: str,
    *,
    requestor_email: str,
    filename: str,
    pdf_bytes: bytes,
) -> None:
    """POST the exact PDF/email payload required by the task-summary flow."""
    encoded_pdf = base64.b64encode(pdf_bytes).decode("ascii")
    payload = {
        "filename": filename,
        "content_type": "application/pdf",
        "pdf_b64": encoded_pdf,
        "request_email": requestor_email,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(webhook_url, json=payload)
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Power Automate webhook returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
