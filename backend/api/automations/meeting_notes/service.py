"""
End-to-end orchestration for one transcript notification.

    notification resource
      -> GET transcript metadata (meetingId, organiser) + .vtt content   [graph]
      -> parse .vtt to speaker-attributed text                            [vtt]
      -> resolve organiser's business area                                [routing]
      -> generate structured notes with the area's prompt                 [azure_openai]
      -> render the firm's HTML template                                  [notes]
      -> store the note, then sendMail it to the adviser                  [graph]

Each external step is defensive: a failure is recorded on the job rather than
thrown away, and the note is stored before delivery so a mail failure still
leaves a readable note (the same ordering task_summary_report uses).
"""
from __future__ import annotations

import logging
import os

from api.automations.meeting_notes import artifacts, azure_openai, graph, notes, vtt
from api.automations.meeting_notes.models import NoteJobRequest, NoteJobResult
from api.automations.meeting_notes.routing import resolve_business_area

_LOG = logging.getLogger(__name__)


def _identity_from_set(identity_set: dict | None) -> tuple[str | None, str | None]:
    """Pull (user_id, display_name) out of a Graph identitySet."""
    if not identity_set:
        return None, None
    user = identity_set.get("user") or {}
    return user.get("id"), user.get("displayName")


def _mail_sender_id(organizer_id: str | None) -> str:
    """Mailbox that Graph sendMail sends as (a service mailbox, or the organiser)."""
    return os.getenv("MEETING_NOTES_MAIL_SENDER", "").strip() or (organizer_id or "")


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

    # 2. Business-area routing from the organiser (Entra group / department).
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
    result.template = area.template

    # 3. Structured notes, then 4. rendered HTML.
    note = await azure_openai.generate_note(transcript_text, area)
    html = notes.render_note_html(
        note,
        area=area,
        subject=meeting_subject,
        organizer_name=organizer_name,
        meeting_date=meeting_date,
    )

    # 5. Store before delivery — a mail failure should still leave a readable note.
    if job_id:
        try:
            artifacts.save_note(job_id, html)
        except Exception as exc:  # noqa: BLE001
            result.error = f"Note rendered but not stored: {exc}"

    # 6. Deliver via Graph sendMail, unless this is a dry run.
    if req.dry_run:
        return result

    recipient = result.organizer_email
    if not recipient:
        result.error = (
            (result.error + " | " if result.error else "")
            + "No organiser email resolved — note stored but not delivered."
        )
        return result

    sender_id = _mail_sender_id(organizer_id)
    if not sender_id:
        result.error = (
            (result.error + " | " if result.error else "")
            + "No mail sender configured (MEETING_NOTES_MAIL_SENDER) — note stored "
            "but not delivered."
        )
        return result

    try:
        await graph.send_mail(
            sender_id=sender_id,
            to_email=recipient,
            subject=f"Meeting notes — {meeting_subject}",
            html_body=html,
        )
        result.delivered = True
    except Exception as exc:  # noqa: BLE001
        result.error = (
            (result.error + " | " if result.error else "") + f"sendMail failed: {exc}"
        )

    return result
