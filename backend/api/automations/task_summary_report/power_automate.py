
from __future__ import annotations

import base64
import os
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException


def _allowed_hosts() -> list[str]:
    # A dedicated allowlist for the Task Summary flow, falling back to the shared
    # one so existing single-flow setups keep working without extra config.
    raw = os.getenv("TASK_SUMMARY_ALLOWED_HOSTS") or os.getenv(
        "POWER_AUTOMATE_ALLOWED_HOSTS", ""
    )
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def validate_webhook_url(url: str) -> None:
    """Reject webhook URLs that aren't https or aren't on an allowed host."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(
            status_code=400, detail="webhook_url must be an absolute https URL."
        )
    allowed = _allowed_hosts()
    # Match on hostname only: netloc carries an optional :port (e.g. the default
    # :443 Power Automate sometimes includes), which would never match a
    # host-only allowlist and reject an otherwise-valid URL.
    host = (parsed.hostname or "").lower()
    if allowed and host not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"webhook_url host '{host}' is not in "
                   "TASK_SUMMARY_ALLOWED_HOSTS / POWER_AUTOMATE_ALLOWED_HOSTS.",
        )


async def deliver_pdf(
    webhook_url: str,
    *,
    requestor_email: str,
    filename: str,
    pdf_bytes: bytes,
) -> None:
    """POST the PDF to the flow. Raises on non-2xx.

    The flow requires this exact schema, all four fields::

        {"filename": str, "content_type": str, "pdf_b64": str, "request_email": str}

    ``pdf_b64`` is the base64-encoded PDF and ``request_email`` is who the flow
    emails it to.
    """
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
