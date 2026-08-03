
from __future__ import annotations

import logging
import os

from api.automations.meeting_notes import graph, power_automate, vtt
from api.automations.meeting_notes.models import NoteJobRequest, NoteJobResult
from api.automations.meeting_notes.routing import resolve_business_area

_LOG = logging.getLogger(__name__)


def _identity_from_set(identity_set: dict | None) -> tuple[str | None, str | None]:
    """Pull (user_id, display_name) out of a Graph identitySet."""
    if not identity_set:
        return None, None
    user = identity_set.get("user") or {}
    return user.get("id"), user.get("displayName")


async def run_note_job(req: NoteJobRequest, job_id: str = "") -> NoteJobResult:
    result = NoteJobResult(
        job_id=job_id,
        status="running",
        transcript_resource=req.transcript_resource,
    )

    # 1. Transcript content — either the injected test VTT or a real Graph fetch.
    meeting_id, _transcript_id = graph.extract_meeting_and_transcript_ids(
        req.transcript_resource
    )
    result.meeting_id = meeting_id

    organizer_id: str | None = None
    organizer_name: str | None = None
    meeting_subject = os.getenv("MEETING_NOTES_DEFAULT_SUBJECT", "Client Meeting Notes")
    meeting_date: str | None = None

    if req.transcript_vtt is not None:
        vtt_text = req.transcript_vtt
        organizer_id = req.organizer_id_override
        meeting_date = req.meeting_date_override
    else:
        try:
            metadata = await graph.get_transcript_metadata(req.transcript_resource)
        except Exception as exc:  # noqa: BLE001
            result.error = f"Transcript metadata fetch failed: {exc}"
            return result
        organizer_id, organizer_name = _identity_from_set(
            metadata.get("meetingOrganizer")
        )
        meeting_id = meeting_id or metadata.get("meetingId")
        result.meeting_id = meeting_id
        meeting_date = metadata.get("createdDateTime")
        try:
            vtt_text = await graph.get_transcript_content(req.transcript_resource)
        except Exception as exc:  # noqa: BLE001
            result.error = f"Transcript content fetch failed: {exc}"
            return result

    transcript_text = vtt.parse_vtt(vtt_text)
    if not transcript_text.strip():
        result.error = "Transcript contained no readable content."
        return result

    result.organizer_id = organizer_id
    result.organizer_name = organizer_name

    # 2. Business-area routing from the organiser (Entra group / department) —
    # sent along as context; the Power Automate flow decides what to do with it.
    user: dict | None = None
    group_names: set[str] = set()
    if organizer_id:
        try:
            user = await graph.get_user(organizer_id)
            organizer_name = organizer_name or user.get("displayName")
            result.organizer_email = user.get("mail") or user.get("userPrincipalName")
        except Exception as exc:  # noqa: BLE001 - routing degrades to general area
            _LOG.warning("Organiser lookup failed for %s: %s", organizer_id, exc)
        try:
            group_names = await graph.user_group_names(organizer_id)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("Group lookup failed for %s: %s", organizer_id, exc)

    area = resolve_business_area(user, group_names)
    result.organizer_name = organizer_name
    result.business_area = area.display_name

    # 2b. Meeting title + attendee emails — the callTranscript object carries
    # neither, only the onlineMeeting itself does. Best-effort: a meeting whose
    # title/roster can't be fetched still gets its transcript handed off.
    meeting_title: str | None = None
    attendee_emails: list[str] = []
    if req.transcript_vtt is not None:
        # No real Graph meeting behind a local test transcript — use the test
        # hooks instead of calling Graph (which would just 400 on a synthetic
        # meeting id).
        meeting_title = req.meeting_title_override
        attendee_emails = list(req.attendee_emails_override or [])
    elif organizer_id and meeting_id:
        try:
            online_meeting = await graph.get_online_meeting(organizer_id, meeting_id)
            meeting_title = online_meeting.get("subject") or None
            participants = online_meeting.get("participants") or {}
            emails: list[str] = []
            seen: set[str] = set()
            for participant in [participants.get("organizer"), *participants.get("attendees", [])]:
                if not participant:
                    continue
                upn = (participant.get("upn") or "").strip()
                if upn and upn.casefold() not in seen:
                    seen.add(upn.casefold())
                    emails.append(upn)
            attendee_emails = emails
        except Exception as exc:  # noqa: BLE001 - handoff still proceeds without this context
            _LOG.warning("Online meeting fetch failed for %s: %s", meeting_id, exc)

    result.meeting_date = meeting_date
    result.meeting_title = meeting_title
    result.attendee_emails = attendee_emails

    # 3. Hand the transcript off to Power Automate — it generates the summary
    # and sends the email. Nothing is rendered or delivered locally.
    if req.dry_run:
        return result

    webhook = power_automate.resolved_webhook()
    if not webhook:
        result.error = "No Power Automate webhook configured (MEETING_NOTES_WEBHOOK_URL)."
        return result
    power_automate.validate_webhook_url(webhook)

    try:
        await power_automate.deliver_transcript(
            webhook,
            transcript_text=transcript_text,
            meeting_subject=meeting_subject,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            organizer_name=organizer_name,
            organizer_email=result.organizer_email,
            attendee_emails=attendee_emails,
            business_area=result.business_area,
        )
        result.delivered = True
    except Exception as exc:  # noqa: BLE001
        result.error = f"Power Automate handoff failed: {exc}"

    return result
