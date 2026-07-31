"""
Render a MeetingNote into the firm's HTML note template (email body + stored copy).

Formatting depends on the note's named fields, not on the model's prose, so every
note for a given business area looks the same. Kept as inline-styled HTML because
it is delivered as the body of a Graph sendMail message.
"""
from __future__ import annotations

from html import escape

from api.automations.meeting_notes.models import MeetingNote
from api.automations.meeting_notes.routing import BusinessArea


def _li_list(items: list[str]) -> str:
    if not items:
        return '<p style="color:#666;margin:4px 0;">None recorded.</p>'
    rows = "".join(f"<li style='margin:4px 0;'>{escape(i)}</li>" for i in items if i)
    return f"<ul style='margin:6px 0 12px;padding-left:20px;'>{rows}</ul>"


def _actions_table(note: MeetingNote) -> str:
    if not note.actions:
        return '<p style="color:#666;margin:4px 0;">None recorded.</p>'
    header = (
        "<tr style='background:#f2f4f7;text-align:left;'>"
        "<th style='padding:6px 10px;border:1px solid #dfe3e8;'>Action</th>"
        "<th style='padding:6px 10px;border:1px solid #dfe3e8;'>Owner</th>"
        "<th style='padding:6px 10px;border:1px solid #dfe3e8;'>Due</th></tr>"
    )
    body = []
    for action in note.actions:
        # An unfilled owner/date is shown as "Not specified", never invented.
        owner = escape(action.owner) if action.owner else "<em style='color:#a00;'>Not specified</em>"
        due = escape(action.due_date) if action.due_date else "<em style='color:#a00;'>Not specified</em>"
        body.append(
            "<tr>"
            f"<td style='padding:6px 10px;border:1px solid #dfe3e8;'>{escape(action.description)}</td>"
            f"<td style='padding:6px 10px;border:1px solid #dfe3e8;'>{owner}</td>"
            f"<td style='padding:6px 10px;border:1px solid #dfe3e8;'>{due}</td>"
            "</tr>"
        )
    return (
        "<table style='border-collapse:collapse;width:100%;margin:6px 0 12px;font-size:14px;'>"
        f"{header}{''.join(body)}</table>"
    )


def _events_list(note: MeetingNote) -> str:
    if not note.follow_up_events:
        return '<p style="color:#666;margin:4px 0;">None recorded.</p>'
    rows = []
    for event in note.follow_up_events:
        when = f" — {escape(event.date)}" if event.date else ""
        extra = f"<br><span style='color:#555;'>{escape(event.notes)}</span>" if event.notes else ""
        rows.append(f"<li style='margin:4px 0;'><strong>{escape(event.title)}</strong>{when}{extra}</li>")
    return f"<ul style='margin:6px 0 12px;padding-left:20px;'>{''.join(rows)}</ul>"


def _heading(text: str) -> str:
    return (
        f"<h3 style='font-size:15px;margin:18px 0 4px;color:#1a1a1a;"
        f"border-bottom:2px solid #e5e8ec;padding-bottom:3px;'>{escape(text)}</h3>"
    )


def render_note_html(
    note: MeetingNote,
    *,
    area: BusinessArea,
    subject: str,
    organizer_name: str | None,
    meeting_date: str | None,
) -> str:
    """Return the complete HTML note for one meeting."""
    flag_banner = ""
    if area.flagged:
        # Section 4: an organiser matching no area gets a generic template that
        # is *obviously* generic, so the reader knows to double-check routing.
        flag_banner = (
            "<div style='background:#fff4e5;border:1px solid #ffb84d;"
            "padding:8px 12px;border-radius:4px;margin:0 0 12px;font-size:13px;'>"
            "⚠ Business area could not be determined for the organiser — this note "
            "uses the general template. Check the adviser's Entra group or department."
            "</div>"
        )

    meta_bits = [f"Business area: <strong>{escape(area.display_name)}</strong>"]
    if organizer_name:
        meta_bits.append(f"Organiser: {escape(organizer_name)}")
    if meeting_date:
        meta_bits.append(f"Date: {escape(meeting_date)}")
    meta = " &nbsp;·&nbsp; ".join(meta_bits)

    return (
        "<div style='font-family:Segoe UI,Arial,sans-serif;color:#1a1a1a;"
        "max-width:720px;font-size:14px;line-height:1.5;'>"
        f"<h2 style='font-size:18px;margin:0 0 2px;'>{escape(subject or 'Meeting Notes')}</h2>"
        f"<p style='color:#555;margin:0 0 12px;font-size:13px;'>{meta}</p>"
        f"{flag_banner}"
        f"{_heading('Summary')}<p style='margin:4px 0 12px;'>{escape(note.summary) or 'No summary produced.'}</p>"
        f"{_heading('Decisions')}{_li_list(note.decisions)}"
        f"{_heading('Action items')}{_actions_table(note)}"
        f"{_heading('Follow-up events')}{_events_list(note)}"
        f"{_heading('Risks / flags')}{_li_list(note.risks_or_flags)}"
        "<p style='color:#999;font-size:12px;margin-top:20px;'>"
        "Generated automatically from the Teams meeting transcript. Please review "
        "before relying on any action or commitment recorded above.</p>"
        "</div>"
    )
