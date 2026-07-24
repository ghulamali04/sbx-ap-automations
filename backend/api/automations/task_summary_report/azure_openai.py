
from __future__ import annotations

import os

import httpx

_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

_SYSTEM_PROMPT = (
    "You summarise financial-advisory task notes for a client-facing report. "
    "Reply with exactly one short, plain-English sentence — no preamble, no "
    "quotes, no markdown."
)


def is_configured() -> bool:
    return bool(_ENDPOINT and _API_KEY and _DEPLOYMENT)


async def summarize_note(task_name: str, project_name: str, notes: str) -> str | None:
    """Return a one-line summary of `notes`, or None if unconfigured / the call fails."""
    if not is_configured() or not notes.strip():
        return None

    url = f"{_ENDPOINT}/openai/deployments/{_DEPLOYMENT}/chat/completions?api-version={_API_VERSION}"
    payload = {
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task_name}\nProject: {project_name}\nNotes: {notes}"},
        ],
        "max_tokens": 80,
        "temperature": 0.2,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as http_client:
            resp = await http_client.post(url, headers={"api-key": _API_KEY}, json=payload)
        if resp.status_code != 200:
            return None
        text = resp.json()["choices"][0]["message"]["content"]
        return " ".join(text.split()).strip() or None
    except Exception:  # noqa: BLE001 — any failure here degrades to a blank cell, not a crash
        return None
