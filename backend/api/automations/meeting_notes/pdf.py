"""
Render a MeetingNote to PDF.

Same sections, same order, same content rules as notes.py's HTML (which stays
the email body — Graph sendMail needs HTML, so that path is untouched). This is
the downloadable document version of the same note, built with reportlab like
the sibling task_summary_report/pdf.py so both automations produce documents in
the firm's look.
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from api.automations.meeting_notes.models import MeetingNote
from api.automations.meeting_notes.routing import BusinessArea

_TEAL = colors.HexColor("#1f6f6e")
_TEAL_TEXT = colors.HexColor("#0f5352")
_INK = colors.HexColor("#1a1a1a")
_MUTED = colors.HexColor("#666666")
_WARN_BG = colors.HexColor("#fff4e5")
_WARN_BORDER = colors.HexColor("#ffb84d")
_NOT_SPECIFIED = colors.HexColor("#aa0000")
_GRID = colors.HexColor("#dfe3e8")
_BAND = colors.HexColor("#f2f4f7")

_MASTHEAD = ParagraphStyle("masthead", fontName="Helvetica-Bold", fontSize=10, leading=14, textColor=_TEAL_TEXT, spaceAfter=2)
_TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=_INK, spaceAfter=4)
_META = ParagraphStyle("meta", fontName="Helvetica", fontSize=9.5, leading=13, textColor=_MUTED, spaceAfter=10)
_SECTION = ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=_TEAL_TEXT, spaceBefore=12, spaceAfter=4)
_BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14, textColor=_INK)
_MUTED_BODY = ParagraphStyle("mutedBody", parent=_BODY, textColor=_MUTED)
_NA = ParagraphStyle("na", parent=_BODY, fontName="Helvetica-Oblique", fontSize=9, textColor=_NOT_SPECIFIED)
_CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=9, leading=12, textColor=_INK)
_CELL_HEAD = ParagraphStyle("cellHead", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white)
_WARN_TEXT = ParagraphStyle("warn", fontName="Helvetica", fontSize=9, leading=12, textColor=_INK)
_FOOTER = ParagraphStyle("footer", fontName="Helvetica-Oblique", fontSize=8, leading=11, textColor=_MUTED, spaceBefore=16)


def _p(text: str | None, style: ParagraphStyle = _BODY) -> Paragraph:
    return Paragraph(escape(text) if text else "", style)


def _bullets(items: list[str]):
    if not items:
        return _p("None recorded.", _MUTED_BODY)
    return ListFlowable(
        [ListItem(_p(item, _BODY), leftIndent=6) for item in items if item],
        bulletType="bullet",
        start="circle",
        leftIndent=12,
    )


def _actions_table(note: MeetingNote, width: float):
    if not note.actions:
        return _p("None recorded.", _MUTED_BODY)
    header = [_p("Action", _CELL_HEAD), _p("Owner", _CELL_HEAD), _p("Due", _CELL_HEAD)]
    body = [header]
    for action in note.actions:
        owner = _p(action.owner, _CELL) if action.owner else _p("Not specified", _NA)
        due = _p(action.due_date, _CELL) if action.due_date else _p("Not specified", _NA)
        body.append([_p(action.description, _CELL), owner, due])
    t = Table(body, colWidths=[width * 0.55, width * 0.22, width * 0.23], hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _TEAL),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(body)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), _BAND))
    t.setStyle(TableStyle(style))
    return t


def _events_block(note: MeetingNote):
    if not note.follow_up_events:
        return _p("None recorded.", _MUTED_BODY)
    items = []
    for event in note.follow_up_events:
        when = f" — {escape(event.date)}" if event.date else ""
        text = f"<b>{escape(event.title)}</b>{when}"
        if event.notes:
            text += f"<br/><font color='#555555'>{escape(event.notes)}</font>"
        items.append(ListItem(Paragraph(text, _BODY), leftIndent=6))
    return ListFlowable(items, bulletType="bullet", start="circle", leftIndent=12)


def render_note_pdf(
    note: MeetingNote,
    *,
    area: BusinessArea,
    subject: str,
    organizer_name: str | None,
    meeting_date: str | None,
) -> bytes:
    """Render the complete meeting note to PDF bytes — same content as render_note_html."""
    buf = io.BytesIO()
    page_size = A4
    margin = 40
    doc = SimpleDocTemplate(
        buf,
        pagesize=page_size,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=subject or "Meeting Notes",
    )
    width = page_size[0] - 2 * margin

    story: list = [
        Paragraph("ADVISORY PARTNERS", _MASTHEAD),
        Paragraph(escape(subject or "Meeting Notes"), _TITLE),
    ]

    meta_bits = [f"Business area: <b>{escape(area.display_name)}</b>"]
    if organizer_name:
        meta_bits.append(f"Organiser: {escape(organizer_name)}")
    if meeting_date:
        meta_bits.append(f"Date: {escape(meeting_date)}")
    story.append(Paragraph(" &#183; ".join(meta_bits), _META))

    if area.flagged:
        warn = Table(
            [[Paragraph(
                "&#9888; Business area could not be determined for the organiser "
                "— this note uses the general template. Check the adviser's "
                "Entra group or department.",
                _WARN_TEXT,
            )]],
            colWidths=[width],
        )
        warn.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _WARN_BG),
            ("BOX", (0, 0), (-1, -1), 0.75, _WARN_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(warn)
        story.append(Spacer(1, 8))

    story.append(Paragraph("Summary", _SECTION))
    story.append(_p(note.summary or "No summary produced.", _BODY))

    story.append(Paragraph("Decisions", _SECTION))
    story.append(_bullets(note.decisions))

    story.append(Paragraph("Action items", _SECTION))
    story.append(_actions_table(note, width))

    story.append(Paragraph("Follow-up events", _SECTION))
    story.append(_events_block(note))

    story.append(Paragraph("Risks / flags", _SECTION))
    story.append(_bullets(note.risks_or_flags))

    story.append(Paragraph(
        "Generated automatically from the Teams meeting transcript. Please review "
        "before relying on any action or commitment recorded above.",
        _FOOTER,
    ))

    doc.build(story)
    return buf.getvalue()
