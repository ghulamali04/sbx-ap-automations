
from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException


def _allowed_hosts() -> list[str]:
    raw = os.getenv("MEETING_NOTES_ALLOWED_HOSTS") or os.getenv(
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
            status_code=400, detail="webhook_url must be an absolute https URL."
        )
    host = (parsed.hostname or "").lower()
    allowed = _allowed_hosts()
    if allowed and host not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"webhook_url host '{host}' is not allowed.",
        )


def resolved_webhook() -> str | None:
    return os.getenv("MEETING_NOTES_WEBHOOK_URL", "").strip() or None


async def deliver_transcript(
    webhook_url: str,
    *,
    transcript_text: str,
    meeting_subject: str,
    meeting_title: str | None,
    meeting_date: str | None,
    organizer_name: str | None,
    organizer_email: str | None,
    attendee_emails: list[str] | None,
    business_area: str | None,
) -> None:
    """POST the transcript and meeting context; the flow does the rest."""
    if not transcript_text.strip():
        raise ValueError("transcript_text is empty — nothing to hand off.")
    payload = {
        "transcript_text": transcript_text,
        "meeting_subject": meeting_subject,
        "meeting_title": meeting_title,
        "meeting_date": meeting_date,
        "organizer_name": organizer_name,
        "organizer_email": organizer_email,
        "attendee_emails": attendee_emails or [],
        "business_area": business_area,
    }
    attempts = max(1, int(os.getenv("POWER_AUTOMATE_DELIVERY_ATTEMPTS", "3")))
    transient_errors = (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadError,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
        httpx.WriteError,
        httpx.WriteTimeout,
    )
    async with httpx.AsyncClient(timeout=60) as client:
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
