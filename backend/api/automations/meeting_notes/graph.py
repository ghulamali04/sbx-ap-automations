
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from functools import lru_cache

import httpx

_LOG = logging.getLogger(__name__)

_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_TOKEN_EXPIRY_BUFFER = 120  # refresh this many seconds early, like session.py


def graph_base() -> str:
    return os.getenv("GRAPH_API_BASE", "https://graph.microsoft.com/v1.0").rstrip("/")


def _ensure_azure_cli_on_path() -> None:
    """Make `az` findable when the Functions host launched us with a minimal PATH.

    Same reasoning as azure_openai._ensure_azure_cli_on_path: a GUI-launched
    `func start` can drop Homebrew's bin dir from PATH, breaking AzureCliCredential.
    """
    import shutil

    if shutil.which("az"):
        return
    for directory in ("/opt/homebrew/bin", "/usr/local/bin"):
        if os.path.exists(os.path.join(directory, "az")):
            os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
            return


@lru_cache(maxsize=1)
def _credential():
    client_id = os.getenv("GRAPH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GRAPH_CLIENT_SECRET", "").strip()
    tenant_id = os.getenv("GRAPH_TENANT_ID", "").strip()
    if client_id and client_secret and tenant_id:
        from azure.identity import ClientSecretCredential

        return ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )

    from azure.identity import DefaultAzureCredential

    # Not in the cloud -> we may be relying on `az login`; make sure `az` resolves.
    if not (os.getenv("WEBSITE_HOSTNAME") or os.getenv("IDENTITY_ENDPOINT")):
        _ensure_azure_cli_on_path()
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


# Simple in-process token cache. get_token() is synchronous and does its own
# caching, but keeping the AccessToken avoids re-entering the credential on every
# Graph call within a job.
_token_cache: dict[str, float | str] = {"value": "", "expires_on": 0.0}
_token_lock = asyncio.Lock()


def _fetch_token() -> tuple[str, float]:
    token = _credential().get_token(_GRAPH_SCOPE)
    return token.token, float(token.expires_on)


async def _access_token() -> str:
    now = time.time()
    cached = _token_cache["value"]
    if cached and now < float(_token_cache["expires_on"]) - _TOKEN_EXPIRY_BUFFER:
        return str(cached)
    async with _token_lock:
        now = time.time()
        if _token_cache["value"] and now < float(_token_cache["expires_on"]) - _TOKEN_EXPIRY_BUFFER:
            return str(_token_cache["value"])
        # Credential calls are blocking (they may spawn `az` or hit IMDS); keep
        # them off the event loop so concurrent jobs aren't stalled.
        value, expires_on = await asyncio.to_thread(_fetch_token)
        _token_cache["value"] = value
        _token_cache["expires_on"] = expires_on
        return value


async def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {await _access_token()}"}


def is_configured() -> bool:
    """True when app-only Graph credentials are available for real calls."""
    if os.getenv("WEBSITE_HOSTNAME") or os.getenv("IDENTITY_ENDPOINT"):
        return True
    return bool(
        os.getenv("GRAPH_CLIENT_ID")
        and os.getenv("GRAPH_CLIENT_SECRET")
        and os.getenv("GRAPH_TENANT_ID")
    )


# ---------- transcripts ----------

def _normalise_resource(resource: str) -> str:
    """Turn a notification resource path into an absolute Graph URL."""
    resource = resource.strip()
    if resource.startswith("http://") or resource.startswith("https://"):
        return resource
    return f"{graph_base()}/{resource.lstrip('/')}"


def _raise_for_transcript_error(resp: httpx.Response, *, what: str) -> None:
    if resp.status_code == 403 and "GraphAccessToTranscriptsDisabled" in resp.text:
        # The tenant switch from section 3.2 has been turned off. Say so plainly
        # rather than surfacing an opaque 403 — this is the well-meaning-security-
        # review failure mode the paper warns about.
        raise RuntimeError(
            "Graph API access to transcripts is disabled for the tenant "
            "(GraphAccessToTranscriptsDisabled). An admin must re-enable it."
        )
    if resp.status_code == 403 and "RSC permission evaluation" in resp.text:
        # Distinct from the app-registration permissions: per-resource GETs
        # (as opposed to the bulk getAllTranscripts function) additionally need
        # a Teams application access policy granted to the organiser. See the
        # README's "One-time admin setup" step 6.
        raise RuntimeError(
            f"{what} failed: no application access policy grants this app "
            "access to this user's online meetings. Run New-CsApplicationAccessPolicy "
            "/ Grant-CsApplicationAccessPolicy for this app id (see README)."
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"{what} failed (HTTP {resp.status_code}): {resp.text[:300]}"
        )


async def get_transcript_metadata(resource: str) -> dict:
    """Fetch the callTranscript object (meetingId, meetingOrganizer, timestamps)."""
    url = _normalise_resource(resource)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=await _auth_headers())
    _raise_for_transcript_error(resp, what="Transcript metadata fetch")
    return resp.json()


async def get_transcript_content(resource: str) -> str:
    """Return the transcript body as WebVTT text (speaker-attributed).

    Accepts either a bare transcript resource path (the notifications/
    getAllTranscripts form, e.g. communications/onlineMeetings(...)/transcripts(...))
    or a full transcriptContentUrl that already ends in /content — appending
    /content unconditionally would double it up and Graph 400s on .../content/content.
    """
    base = _normalise_resource(resource).rstrip("/")
    url = base if base.endswith("/content") else f"{base}/content"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            url,
            headers=await _auth_headers(),
            params={"$format": "text/vtt"},
        )
    _raise_for_transcript_error(resp, what="Transcript content fetch")
    return resp.text


async def list_transcripts_for_user(
    user_id: str,
    *,
    start_date_time: str | None = None,
    end_date_time: str | None = None,
) -> list[dict]:
    """List callTranscript objects for every meeting the given user organised.

    Uses GET /users/{id}/onlineMeetings/getAllTranscripts(meetingOrganizerUserId=...),
    which is distinct from the tenant-wide subscription resource in subscriptions.py:
    that one pushes a notification per new transcript across the whole tenant, this
    one is a direct pull for one organiser, handy for local/manual testing and for
    backfilling meetings that happened before the subscription existed.

    meetingOrganizerUserId must be the Entra object id (a GUID) — unlike most
    /users/{id} routes, this function rejects a userPrincipalName/email with a
    plain 400. Resolve it first so callers can still pass either.
    """
    if "@" in user_id:
        resolved = await get_user(user_id, select="id")
        user_id = resolved["id"]

    url = (
        f"{graph_base()}/users/{user_id}/onlineMeetings/getAllTranscripts"
        f"(meetingOrganizerUserId='{user_id}'"
    )
    if start_date_time:
        url += f",startDateTime={start_date_time}"
    if end_date_time:
        url += f",endDateTime={end_date_time}"
    url += ")"

    transcripts: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        headers = await _auth_headers()
        while url:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 403 and "GraphAccessToTranscriptsDisabled" in resp.text:
                raise RuntimeError(
                    "Graph API access to transcripts is disabled for the tenant "
                    "(GraphAccessToTranscriptsDisabled). An admin must re-enable it."
                )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Transcript list fetch failed for {user_id} "
                    f"(HTTP {resp.status_code}): {resp.text[:300]}"
                )
            body = resp.json()
            transcripts.extend(body.get("value", []))
            url = body.get("@odata.nextLink")
    return transcripts


async def get_online_meeting(
    organizer_id: str, meeting_id: str, *, select: str = "subject,participants"
) -> dict:
    """Fetch the onlineMeeting itself (application permission OnlineMeetings.Read.All) —
    the callTranscript object has no subject/attendee list, only this does.
    """
    url = f"{graph_base()}/users/{organizer_id}/onlineMeetings/{meeting_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            url, headers=await _auth_headers(), params={"$select": select}
        )
    _raise_for_transcript_error(resp, what=f"Online meeting fetch for {meeting_id}")
    return resp.json()


async def list_meeting_recordings(organizer_id: str, meeting_id: str) -> list[dict]:
    """List callRecording objects for one online meeting (application permission
    OnlineMeetingRecording.Read.All), same RSC/application-access-policy
    requirement as get_online_meeting. A meeting with no recording returns an
    empty list, not an error — recording is opt-in per meeting like transcription.
    """
    url = f"{graph_base()}/users/{organizer_id}/onlineMeetings/{meeting_id}/recordings"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=await _auth_headers())
    if resp.status_code == 404:
        return []
    _raise_for_transcript_error(resp, what=f"Recording list fetch for {meeting_id}")
    return resp.json().get("value", [])


# ---------- users / routing lookups ----------

async def get_user(user_id: str, *, select: str = "id,displayName,mail,userPrincipalName,department,jobTitle") -> dict:
    url = f"{graph_base()}/users/{user_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            url, headers=await _auth_headers(), params={"$select": select}
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"User lookup failed for {user_id} (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    return resp.json()


async def user_group_names(user_id: str) -> set[str]:
    """Return the display names of the groups the user is a member of.

    Used to route by Entra group (e.g. FP-Advisers / BS-Advisers) as an
    alternative to the department attribute (options paper, section 4).
    """
    url = f"{graph_base()}/users/{user_id}/memberOf"
    names: set[str] = set()
    async with httpx.AsyncClient(timeout=30) as client:
        headers = await _auth_headers()
        params: dict | None = {"$select": "displayName", "$top": 100}
        while url:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Group membership lookup failed for {user_id} "
                    f"(HTTP {resp.status_code}): {resp.text[:300]}"
                )
            body = resp.json()
            for group in body.get("value", []):
                name = (group.get("displayName") or "").strip()
                if name:
                    names.add(name)
            url = body.get("@odata.nextLink")
            params = None  # nextLink already carries the query
    return names


# ---------- subscriptions ----------

async def create_subscription(body: dict) -> dict:
    url = f"{graph_base()}/subscriptions"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=await _auth_headers(), json=body)
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Subscription create failed (HTTP {resp.status_code}): {resp.text[:400]}"
        )
    return resp.json()


async def renew_subscription(subscription_id: str, expiration_iso: str) -> dict:
    url = f"{graph_base()}/subscriptions/{subscription_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.patch(
            url,
            headers=await _auth_headers(),
            json={"expirationDateTime": expiration_iso},
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Subscription renew failed for {subscription_id} "
            f"(HTTP {resp.status_code}): {resp.text[:400]}"
        )
    return resp.json()


async def list_subscriptions() -> list[dict]:
    url = f"{graph_base()}/subscriptions"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=await _auth_headers())
    if resp.status_code != 200:
        raise RuntimeError(
            f"Subscription list failed (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    return resp.json().get("value", [])


async def delete_subscription(subscription_id: str) -> None:
    url = f"{graph_base()}/subscriptions/{subscription_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(url, headers=await _auth_headers())
    if resp.status_code not in (200, 204):
        raise RuntimeError(
            f"Subscription delete failed for {subscription_id} "
            f"(HTTP {resp.status_code}): {resp.text[:300]}"
        )


# ---------- helpers ----------

def extract_meeting_and_transcript_ids(resource: str) -> tuple[str | None, str | None]:
    """Pull ('<meetingId>', '<transcriptId>') out of a getAllTranscripts resource path.

    Resource looks like:
      communications/onlineMeetings('MSo...')/transcripts('MSMj...')
    """
    ids = re.findall(r"\(['\"]?([^'\")]+)['\"]?\)", resource or "")
    meeting_id = ids[0] if len(ids) >= 1 else None
    transcript_id = ids[1] if len(ids) >= 2 else None
    return meeting_id, transcript_id
