"""
Deliver rendered charts by calling a Power Automate flow.

Python's responsibility ends at "POST the PNG as base64 to the flow". What the flow
then does with it — filing it, emailing it — is the flow's business, and
deliberately not encoded here.

The request body matches the flow's declared schema exactly:

    {"filename": str, "content_type": str, "image_b64": [str]}

`image_b64` is an array per that schema, so the base64 payload is sent as a
single-element list.

Security (spec §6.7): the webhook URL can be supplied by the caller, so it is
validated against an allowlist before use rather than trusted outright.
"""
from __future__ import annotations

import base64
import os
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException


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
    content_type: str = "image/png",
) -> None:
    """POST every chart to the flow in ONE call. Raises on non-2xx.

    All images go in a single request so the flow triggers once and can build one
    email containing them all — one call per project would send one email each.

    `images` order is meaningful: it is the order the charts should appear in
    (BAS before IAS, chronological within each), so the flow can rely on it.
    """
    payload = {
        "filename": filename,
        "content_type": content_type,
        "image_b64": [base64.b64encode(png).decode("ascii") for png in images],
    }
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(webhook_url, json=payload)
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Power Automate webhook returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
