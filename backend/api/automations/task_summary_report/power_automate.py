
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
