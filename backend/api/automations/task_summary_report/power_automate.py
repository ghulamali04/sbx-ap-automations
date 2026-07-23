"""
Deliver the rendered Task Summary PDF by calling a Power Automate flow.

Body matches the flow's declared schema exactly:

    {"filename": str, "content_type": str, "image_b64": [str]}

`image_b64` is a single-element list holding the base64 PDF — the key name is
inherited from the flow's existing image-delivery schema (see
completion_overview/power_automate.py), which also accepts a PDF for this flow.
Webhook URL validation (https + allowlisted host) is shared with that module —
see validate_webhook_url() there, reused as-is rather than duplicated.
"""
from __future__ import annotations

import base64

import httpx


async def deliver_pdf(webhook_url: str, *, filename: str, pdf_bytes: bytes) -> None:
    """POST the PDF to the flow. Raises on non-2xx."""
    payload = {
        "filename": filename,
        "content_type": "application/pdf",
        "image_b64": [base64.b64encode(pdf_bytes).decode("ascii")],
    }
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(webhook_url, json=payload)
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Power Automate webhook returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
