
from __future__ import annotations

import base64

import httpx


async def deliver_pdf(
    webhook_url: str,
    *,
    requestor_email: str,
    filename: str,
    pdf_bytes: bytes,
) -> None:
    """POST one email-ready PDF attachment to the flow. Raises on non-2xx."""
    encoded_pdf = base64.b64encode(pdf_bytes).decode("ascii")
    payload = {
        "requestor_email": requestor_email,
        "filename": filename,
        "content_type": "application/pdf",
        "content_b64": encoded_pdf,
        "attachments": [
            {
                "name": filename,
                "contentType": "application/pdf",
                "contentBytes": encoded_pdf,
            }
        ],
    }
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(webhook_url, json=payload)
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Power Automate webhook returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
