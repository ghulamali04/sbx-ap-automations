"""
Reportlab PDF renderer for the head-client Task Summary report.

Visual target: the approved Advisory Partners sample export — a teal masthead,
three summary tables across the top (by project group / by status / term
deposit summary), one wide task-register table banded per project, then a
"Selected task notes" table and a footnote about greyed cells.

Built with reportlab (pure Python, no system font/graphics dependencies) so it
runs unmodified on Azure Functions, same reasoning as matplotlib's "Agg"
backend in completion_overview/charts.py.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_TEAL = colors.HexColor("#1f6f6e")
_TEAL_TEXT = colors.HexColor("#0f5352")
_INK = colors.HexColor("#1a1a1a")
_MUTED = colors.HexColor("#666666")
_BAND_B = colors.HexColor("#eaf2f2")
_NA_FILL = colors.HexColor("#e2e2e2")
_GRID = colors.HexColor("#bfbfbf")

_CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=7, leading=8.5, textColor=_INK)
_CELL_BOLD = ParagraphStyle("cellBold", parent=_CELL, fontName="Helvetica-Bold")
_HEAD = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.white)
_SECTION_HEAD = ParagraphStyle(
    "sectionHead", fontName="Helvetica-Bold", fontSize=10.5, textColor=_TEAL_TEXT, spaceAfter=4,
)


@dataclass
class TaskRow:
    project_name: str
    task_name: str
    project_group: str
    custom_status: str
    owner: str
    head_client_name: str
    preparer: str
    cash_account: str
    td_value: float | None
    td_term: str
    provider: str
    maturity_instruction: str
    td_roa_reason: str
    latest_comment: str


@dataclass
class ReportData:
    title: str
    head_client_name: str
    tasks_total: int
    prepared_by: str
    as_at: str
    by_project_group: list[tuple[str, int]]
    by_status: list[tuple[str, int]]
    td_summary: dict
    rows: list[TaskRow]
    selected_notes: list[tuple[str, str, str]]  # (task, project, note)
    footer_note: str


def _fmt_money(value: float | None) -> str:
    return f"${value:,.0f}" if value is not None else ""


def _p(text: str | None, style: ParagraphStyle = _CELL) -> Paragraph:
    return Paragraph(escape(text) if text else "", style)


def _header_block(data: ReportData) -> list:
    subtitle = (
        f"Head client: {escape(data.head_client_name)} &nbsp;·&nbsp; "
        f"{data.tasks_total} active tasks &nbsp;·&nbsp; "
        f"Prepared by {escape(data.prepared_by)} &nbsp;·&nbsp; As at {escape(data.as_at)}"
    )
    return [
        Paragraph("ADVISORY PARTNERS", ParagraphStyle(
            "masthead", fontName="Helvetica-Bold", fontSize=9, leading=13, textColor=_TEAL_TEXT, spaceAfter=2,
        )),
        Paragraph(escape(data.title), ParagraphStyle(
            "title", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=_INK, spaceAfter=6,
        )),
        Paragraph(subtitle, ParagraphStyle(
            "subtitle", fontName="Helvetica-Oblique", fontSize=9, leading=13, textColor=_MUTED, spaceAfter=12,
        )),
    ]


def _titled(heading: str, table: Table) -> Table:
    wrapper = Table([[Paragraph(escape(heading), _SECTION_HEAD)], [table]])
    wrapper.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
    ]))
    return wrapper


def _count_table(heading: str, label_head: str, rows: list[tuple[str, int]], width: int) -> Table:
    body = [[_p(label_head, _HEAD), _p("Count", _HEAD)]]
    for label, count in rows:
        style = _CELL_BOLD if label == "Total" else _CELL
        body.append([_p(label, style), _p(str(count), style)])
    t = Table(body, colWidths=[width - 45, 45], hAlign="LEFT")
    n = len(body)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _TEAL),
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, n - 1), (-1, n - 1), 1, _INK),
    ]))
    return _titled(heading, t)


def _kv_table(heading: str, rows: list[tuple[str, str]], width: int) -> Table:
    body = [[_p(k), _p(v)] for k, v in rows]
    t = Table(body, colWidths=[width - 110, 110], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("FONTNAME", (1, len(body) - 1), (1, len(body) - 1), "Helvetica-Bold"),
    ]))
    return _titled(heading, t)


def _summary_row(data: ReportData, page_width: float) -> Table:
    col = page_width / 3
    left = _count_table("Tasks by project group", "Project group", data.by_project_group, int(col) - 14)
    mid = _count_table("Tasks by status", "Status", data.by_status, int(col) - 14)
    td = data.td_summary
    right = _kv_table("Term deposit summary", [
        ("Active term-deposit tasks", str(td["active_count"])),
        ("Total term-deposit value", _fmt_money(td["total_value"])),
        ("Common term", td["common_term"] or "—"),
        ("Maturity instruction", td["maturity_instruction"] or "—"),
        ("Cash account", td["cash_account"] or "—"),
        ("Provider", td["provider"] or "—"),
    ], int(col) - 14)

    outer = Table([[left, mid, right]], colWidths=[col, col, col], hAlign="LEFT")
    outer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))
    return outer


# Third value is a relative weight, not a point width: the table is scaled to fill
# the page, so dropping or adding a column reflows the rest instead of leaving a
# gap at the right margin.
_TASK_COLUMNS = [
    ("Project Name", "project_name", 95),
    ("Task Name", "task_name", 118),
    ("Project Group", "project_group", 78),
    ("Custom Status", "custom_status", 62),
    ("Owner", "owner", 62),
    ("Head Client name", "head_client_name", 62),
    ("Who prepares BAS/IAS", "preparer", 58),
    ("Cash account", "cash_account", 62),
    ("Term Deposit Value", "td_value", 58),
    ("Current Term", "td_term", 48),
    ("Provider", "provider", 58),
    ("Maturity instruction", "maturity_instruction", 66),
    ("TD - ROA Reason", "td_roa_reason", 78),
]


def _task_register_table(rows: list[TaskRow], page_width: float) -> Table:
    total_weight = sum(w for _, _, w in _TASK_COLUMNS)
    scale = page_width / total_weight
    widths = [w * scale for _, _, w in _TASK_COLUMNS]

    header = [_p(label, _HEAD) for label, _, _ in _TASK_COLUMNS]
    body = [header]
    blank_cells: list[tuple[int, int]] = []  # (col, row) to grey out
    band_cells: list[tuple[int, int]] = []   # rows to shade band B
    band_on = False
    prev_project = None

    for r_index, row in enumerate(rows, start=1):
        if row.project_name != prev_project:
            band_on = not band_on
            prev_project = row.project_name
        if band_on:
            band_cells.append(r_index)

        values = [
            row.project_name, row.task_name, row.project_group, row.custom_status,
            row.owner, row.head_client_name, row.preparer, row.cash_account,
            _fmt_money(row.td_value), row.td_term, row.provider,
            row.maturity_instruction, row.td_roa_reason,
        ]
        cells = []
        for c_index, value in enumerate(values):
            text = value if isinstance(value, str) else value
            if not text:
                blank_cells.append((c_index, r_index))
            cells.append(_p(text, _CELL))
        body.append(cells)

    t = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _TEAL),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for r in band_cells:
        style.append(("BACKGROUND", (0, r), (-1, r), _BAND_B))
    for c, r in blank_cells:
        style.append(("BACKGROUND", (c, r), (c, r), _NA_FILL))
    t.setStyle(TableStyle(style))
    return t


def _selected_notes_table(notes: list[tuple[str, str, str]], page_width: float) -> Table:
    task_w = int(page_width * 0.22)
    project_w = int(page_width * 0.16)
    note_w = int(page_width - task_w - project_w)
    body = [[_p("Task", _HEAD), _p("Project", _HEAD), _p("Latest note / action", _HEAD)]]
    for i, (task, project, note) in enumerate(notes):
        body.append([_p(task), _p(project), _p(note)])
    t = Table(body, colWidths=[task_w, project_w, note_w], repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _TEAL),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in range(1, len(body)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), _BAND_B))
    t.setStyle(TableStyle(style))
    return t


def render_task_summary_pdf(data: ReportData) -> bytes:
    """Render the full report to PDF bytes."""
    buf = io.BytesIO()
    page_size = landscape(A3)
    margin = 24
    doc = SimpleDocTemplate(
        buf, pagesize=page_size,
        leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin,
        title=data.title,
    )
    usable_width = page_size[0] - 2 * margin

    story: list = []
    story.extend(_header_block(data))
    story.append(Paragraph("Summary", _SECTION_HEAD))
    story.append(_summary_row(data, usable_width))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Task register", _SECTION_HEAD))
    story.append(_task_register_table(data.rows, usable_width))
    story.append(Spacer(1, 16))

    if data.selected_notes:
        story.append(Paragraph("Selected task notes", _SECTION_HEAD))
        story.append(_selected_notes_table(data.selected_notes, usable_width))
        story.append(Spacer(1, 10))

    story.append(Paragraph(escape(data.footer_note), ParagraphStyle(
        "footer", fontName="Helvetica-Oblique", fontSize=7.5, textColor=_MUTED,
    )))

    doc.build(story)
    return buf.getvalue()
