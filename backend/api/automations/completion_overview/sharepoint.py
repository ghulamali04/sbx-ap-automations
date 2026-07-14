"""
Deliver a rendered chart to SharePoint by calling a Power Automate HTTP trigger.

Python never touches SharePoint directly — it POSTs the PNG (base64) plus placement
metadata to a Power Automate flow, which owns the SharePoint connection. This keeps
SharePoint auth out of Python entirely (the reason we chose the webhook approach).

Security (spec §6.7): the webhook URL and output folder are caller-supplied, so both
are validated against allowlists before use rather than trusted outright.
"""
from __future__ import annotations

import base64
import os
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException


def _allowed_webhook_hosts() -> list[str]:
    raw = os.getenv("SHAREPOINT_WEBHOOK_ALLOWED_HOSTS", "")
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def _allowed_folder_prefixes() -> list[str]:
    raw = os.getenv("SHAREPOINT_ALLOWED_FOLDER_PREFIXES", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def validate_webhook_url(url: str) -> None:
    """Reject webhook URLs that aren't https or aren't on an allowed host."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(status_code=400, detail="sharepoint_webhook_url must be an absolute https URL.")
    allowed = _allowed_webhook_hosts()
    if allowed and parsed.netloc.lower() not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"sharepoint_webhook_url host '{parsed.netloc}' is not in SHAREPOINT_WEBHOOK_ALLOWED_HOSTS.",
        )


def validate_output_folder(folder: str) -> None:
    """Reject folders outside the configured allowlist and obvious traversal."""
    if ".." in folder:
        raise HTTPException(status_code=400, detail="output_folder must not contain '..'.")
    prefixes = _allowed_folder_prefixes()
    if prefixes and not any(folder.startswith(p) for p in prefixes):
        raise HTTPException(
            status_code=400,
            detail=f"output_folder '{folder}' is not under an allowed prefix.",
        )


async def deliver_chart(
    webhook_url: str,
    *,
    folder: str,
    filename: str,
    png_bytes: bytes,
    project_name: str,
    grouping: str,
) -> None:
    """POST one chart to the Power Automate webhook. Raises on non-2xx."""
    payload = {
        "folder": folder,
        "filename": filename,
        "project_name": project_name,
        "grouping": grouping,
        "content_type": "image/png",
        "content_base64": base64.b64encode(png_bytes).decode("ascii"),
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(webhook_url, json=payload)
    if resp.status_code >= 300:
        raise RuntimeError(
            f"SharePoint webhook returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
