"""
Thin async client for the Zoho Projects data API.

Wraps the auto-refreshing token from session.py so callers just get projects and
tasks back as plain dicts. Uses the legacy /restapi/ endpoints, which accept the
portal *name* (e.g. 'aiautomation') — the shape the rest of this codebase already
uses successfully.
"""
from __future__ import annotations

import os

import httpx

from api.automations.zoho.session import get_access_token

PROJECTS_API_BASE = (
    os.getenv("ZOHO_PROJECTS_API_BASE") or "https://projectsapi.zoho.com"
).rstrip("/")

_PAGE = 200  # Zoho's max page size for the legacy tasks endpoint


def _portal() -> str:
    return os.getenv("ZOHO_PORTAL_ID", "aiautomation")


async def _headers() -> dict:
    token = await get_access_token()
    return {"Authorization": f"Zoho-oauthtoken {token}"}


async def list_projects() -> list[dict]:
    """Return every project in the configured portal."""
    url = f"{PROJECTS_API_BASE}/restapi/portal/{_portal()}/projects/"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=await _headers(), params={"range": _PAGE})
    if resp.status_code != 200:
        raise RuntimeError(f"Zoho projects list failed (HTTP {resp.status_code}): {resp.text[:300]}")
    return resp.json().get("projects", [])


async def get_all_tasks(project_id: str) -> list[dict]:
    """Return every task in a project, following the legacy index/range pagination."""
    url = f"{PROJECTS_API_BASE}/restapi/portal/{_portal()}/projects/{project_id}/tasks/"
    headers = await _headers()
    tasks: list[dict] = []
    index = 1
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            resp = await client.get(
                url, headers=headers,
                params={"index": index, "range": _PAGE, "status": "all"},
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Zoho tasks fetch failed for {project_id} (HTTP {resp.status_code}): {resp.text[:300]}"
                )
            page = resp.json().get("tasks", [])
            tasks.extend(page)
            if len(page) < _PAGE:
                break
            index += _PAGE
    return tasks
