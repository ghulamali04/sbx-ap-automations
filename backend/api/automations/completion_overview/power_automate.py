 
from __future__ import annotations

import asyncio
import base64
import os
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from api.automations.email_recipients import normalize_email_recipients


def _allowed_hosts() -> list[str]:
    raw = os.getenv("POWER_AUTOMATE_ALLOWED_HOSTS", "")
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def validate_webhook_url(url: str) -> None:
    """Reject webhook URLs that aren't https or aren't on an allowed host."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(
            status_code=400, detail="webhook_url must be an absolute https URL."
        )
    allowed = _allowed_hosts()
    if allowed and parsed.netloc.lower() not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"webhook_url host '{parsed.netloc}' is not in POWER_AUTOMATE_ALLOWED_HOSTS.",
        )  


async def deliver_charts(
    webhook_url: str,
    *,
    filename: str,
    images: list[bytes],
    request_emails: list[str],
    email_subject: str | None = None,
) -> None:
    """POST every PNG chart, recipient, and subject in one flow call.

    All images go in a single request so the flow triggers once and can build one
    email containing them all — one call per project would send one email each.

    `images` order is meaningful: it is the order Power Automate should embed the
    images in its HTML email body (BAS before IAS, chronological within each).
    The payload deliberately matches the Power Automate trigger schema exactly.
    """
    recipients = normalize_email_recipients(request_emails)
    if not recipients:
        raise ValueError("At least one report recipient email is required.")
    if not images:
        raise ValueError("At least one completion chart image is required.")
    subject = (email_subject or "Completion Overview Report").strip()
    encoded_images = [
        base64.b64encode(image).decode("ascii") for image in images
    ]
    payload = {
        "filename": filename,
        "content_type": "image/png",
        "image_b64": encoded_images,
        "email_subject": subject,
        "projects_include_Emails": recipients,
    }
    attempts = max(
        1,
        int(os.getenv("POWER_AUTOMATE_DELIVERY_ATTEMPTS", "3")),
    )
    transient_errors = (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadError,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
        httpx.WriteError,
        httpx.WriteTimeout,
    )
    async with httpx.AsyncClient(timeout=180) as client:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.post(webhook_url, json=payload)
                break
            except transient_errors:
                if attempt >= attempts:
                    raise
                await asyncio.sleep(attempt)
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Power Automate webhook returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
