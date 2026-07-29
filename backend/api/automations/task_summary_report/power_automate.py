
from __future__ import annotations

import base64
import os
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from api.automations.email_recipients import normalize_email_recipients


def _allowed_hosts() -> list[str]:
    raw = os.getenv("TASK_SUMMARY_ALLOWED_HOSTS") or os.getenv(
        "POWER_AUTOMATE_ALLOWED_HOSTS", ""
    )
    hosts = []
    for value in raw.split(","):
        value = value.strip().lower()
        if value:
            hosts.append(urlparse(f"//{value}").hostname or value)
    return hosts


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
    request_emails: list[str] | None = None,
    requestor_email: str | None = None,
    filename: str,
    pdf_bytes: bytes,
) -> None:
    """POST the exact PDF/email payload required by the task-summary flow."""
    recipients = normalize_email_recipients(
        [*(request_emails or []), requestor_email]
    )
    if not recipients:
        raise ValueError("At least one PDF recipient email is required.")
    encoded_pdf = base64.b64encode(pdf_bytes).decode("ascii")
    payload = {
        "filename": filename,
        "content_type": "application/pdf",
        "pdf_b64": encoded_pdf,
        # Keep the original single-email property for existing flows.
        "request_email": recipients[0],
        # New flows should join this array with ';' in the M365 To field.
        "request_emails": recipients,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(webhook_url, json=payload)
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Power Automate webhook returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
