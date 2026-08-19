"""
Shared PDF branding and layout primitives (ARCHITECTURE.md §4 — doc builders).

Every Advisory Partners PDF report is built from the same handful of pieces: a
teal masthead, a title block, section headings, and banded data tables. This
module owns that look-and-feel once so automation report modules only supply
data and layout sequencing — they should not redefine colours, fonts, or table
chrome locally (see `automations/client_review_pack/sections/*` for callers).

Two render entry points:
  - `render_section_pdf(section)`   — one section, standalone, its own page size.
  - `combine_sections(sections)`    — several *same-page-size* sections into one
    PDF. Advisory Partners' portrait sections share A4; the wide register-style
    sections (Task Summary, Group Structure) use landscape A3/A4 and can't be
    combined with the portrait sections until a general BaseDocTemplate with
    per-size PageTemplates is built — deliberately left for that follow-up.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------- palette ----------

TEAL = colors.HexColor("#1f6f6e")
TEAL_TEXT = colors.HexColor("#0f5352")
TEAL_LIGHT = colors.HexColor("#eaf2f2")
INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#666666")
GRID = colors.HexColor("#bfbfbf")
BAND = colors.HexColor("#eaf2f2")
NA_FILL = colors.HexColor("#e2e2e2")

GOOD_BG, GOOD_TEXT = colors.HexColor("#e3f3e6"), colors.HexColor("#1f7a3d")
WARN_BG, WARN_TEXT = colors.HexColor("#fbead2"), colors.HexColor("#a15c00")
BAD_BG, BAD_TEXT = colors.HexColor("#f7dcdc"), colors.HexColor("#a3261f")
NEUTRAL_BG, NEUTRAL_TEXT = colors.HexColor("#ececec"), MUTED

_TONE_BG = {"good": GOOD_BG, "warn": WARN_BG, "bad": BAD_BG, "neutral": NEUTRAL_BG}
_TONE_TEXT = {"good": GOOD_TEXT, "warn": WARN_TEXT, "bad": BAD_TEXT, "neutral": NEUTRAL_TEXT}

DEFAULT_MARGIN = 36  # points (0.5")
WIDE_MARGIN = 20  # points — for register-style tables with many columns

# ---------- typography ----------

_FONT = "Helvetica"
_BOLD = "Helvetica-Bold"
_ITALIC = "Helvetica-Oblique"

MASTHEAD = ParagraphStyle("masthead", fontName=_BOLD, fontSize=9, leading=13, textColor=TEAL_TEXT, spaceAfter=2)
TITLE = ParagraphStyle("title", fontName=_BOLD, fontSize=17, leading=21, textColor=INK, spaceAfter=4)
SUBTITLE = ParagraphStyle("subtitle", fontName=_ITALIC, fontSize=9, leading=13, textColor=MUTED, spaceAfter=10)
META = ParagraphStyle("meta", fontName=_FONT, fontSize=9.5, leading=13, textColor=INK, spaceAfter=3)
SECTION_HEAD = ParagraphStyle("sectionHead", fontName=_BOLD, fontSize=12.5, leading=15, textColor=TEAL_TEXT,
                               spaceBefore=10, spaceAfter=6)
SUBSECTION_HEAD = ParagraphStyle("subsectionHead", fontName=_BOLD, fontSize=10, leading=13, textColor=TEAL_TEXT,
                                  spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("body", fontName=_FONT, fontSize=9, leading=12.5, textColor=INK)
NOTE = ParagraphStyle("note", fontName=_ITALIC, fontSize=7.5, leading=10, textColor=MUTED, spaceBefore=6)

CELL = ParagraphStyle("cell", fontName=_FONT, fontSize=7.5, leading=9, textColor=INK)
CELL_BOLD = ParagraphStyle("cellBold", parent=CELL, fontName=_BOLD)
CELL_MUTED = ParagraphStyle("cellMuted", parent=CELL, textColor=MUTED)
CELL_RIGHT = ParagraphStyle("cellRight", parent=CELL, alignment=2)
CELL_BOLD_RIGHT = ParagraphStyle("cellBoldRight", parent=CELL_BOLD, alignment=2)
CELL_CENTER = ParagraphStyle("cellCenter", parent=CELL, alignment=1)
HEAD = ParagraphStyle("head", fontName=_BOLD, fontSize=7.5, leading=9, textColor=colors.white)
HEAD_RIGHT = ParagraphStyle("headRight", parent=HEAD, alignment=2)
HEAD_CENTER = ParagraphStyle("headCenter", parent=HEAD, alignment=1)

_STYLE_MATRIX = {
    ("left", False): CELL, ("left", True): CELL_BOLD,
    ("right", False): CELL_RIGHT, ("right", True): CELL_BOLD_RIGHT,
    ("center", False): CELL_CENTER, ("center", True): CELL_CENTER,
}
_HEAD_MATRIX = {"left": HEAD, "right": HEAD_RIGHT, "center": HEAD_CENTER}

_tone_style_cache: dict[tuple[str, str], ParagraphStyle] = {}


def _tone_variant(base: ParagraphStyle, tone: str) -> ParagraphStyle:
    key = (base.name, tone)
    if key not in _tone_style_cache:
        _tone_style_cache[key] = ParagraphStyle(
            f"{base.name}_{tone}", parent=base, textColor=_TONE_TEXT.get(tone, base.textColor)
        )
    return _tone_style_cache[key]


def p(text: str | None, style: ParagraphStyle = CELL) -> Paragraph:
    """Escape + wrap plain text as a Paragraph (tables need flowables, not strings, to wrap)."""
    return Paragraph(escape(text) if text else "", style)


# ---------- formatting ----------

def fmt_money(value: float | None, *, decimals: int = 2, na: str = "") -> str:
    if value is None:
        return na
    return f"${value:,.{decimals}f}"


def fmt_money_signed(value: float | None, *, decimals: int = 2, na: str = "") -> str:
    """Negative amounts in parentheses, matching the accounting-statement convention used throughout."""
    if value is None:
        return na
    return f"(${abs(value):,.{decimals}f})" if value < 0 else f"${value:,.{decimals}f}"


def fmt_pct(value: float | None, *, decimals: int = 1, na: str = "") -> str:
    if value is None:
        return na
    return f"{value:.{decimals}f}%"


def fmt_number(value: float | int | None, *, decimals: int = 0, na: str = "") -> str:
    if value is None:
        return na
    return f"{value:,.{decimals}f}"


# ---------- header block ----------

def masthead_block(title: str, *, subtitle: str | None = None, meta: list[str] | None = None) -> list:
    """'ADVISORY PARTNERS' + report title + optional meta lines (e.g. 'Head Client: Dan') + subtitle."""
    story: list = [Paragraph("ADVISORY PARTNERS", MASTHEAD), Paragraph(escape(title), TITLE)]
    for line in meta or []:
        story.append(Paragraph(line, META))
    if subtitle:
        story.append(Paragraph(escape(subtitle), SUBTITLE))
    story.append(Spacer(1, 4))
    return story


def section_heading(text: str) -> Paragraph:
    return Paragraph(escape(text), SECTION_HEAD)


def subsection_heading(text: str) -> Paragraph:
    return Paragraph(escape(text), SUBSECTION_HEAD)


def note(text: str) -> Paragraph:
    return Paragraph(text, NOTE)  # caller-supplied markup (e.g. numbered notes) — not escaped


# ---------- tables ----------

@dataclass
class Column:
    header: str
    key: str
    weight: float
    align: str = "left"  # left | right | center
    bold: bool = False


def data_table(
    columns: list[Column],
    rows: list[dict],
    page_width: float,
    *,
    band_key: str | None = None,
    tones: dict[tuple[int, str], str] | None = None,
    row_bold: set[int] | None = None,
    header_bg: colors.Color = TEAL,
    blank_as: str = "—",
) -> Table:
    """The workhorse register/table used by most sections: header row + banded body.

    `band_key` re-toggles row shading whenever that row's value for `key` changes
    (e.g. shade by project so multi-row projects read as one block).
    `tones` maps (0-based row index, column key) -> "good"/"warn"/"bad"/"neutral"
    for status-style cells (risk ratings, lodgement status, watch-list flags).
    `row_bold` marks 0-based row indices as totals: bold text + a rule above.
    """
    total_weight = sum(c.weight for c in columns) or 1
    widths = [c.weight / total_weight * page_width for c in columns]
    tones = tones or {}
    row_bold = row_bold or set()

    header_row = [p(c.header, _HEAD_MATRIX[c.align]) for c in columns]
    body = [header_row]
    band_rows: list[int] = []
    band_on = False
    prev_band_value: object = object()
    bg_cells: list[tuple[int, int, str]] = []

    for r_idx, row in enumerate(rows):
        if band_key is not None:
            current = row.get(band_key)
            if current != prev_band_value:
                band_on = not band_on
                prev_band_value = current
            if band_on:
                band_rows.append(r_idx + 1)

        bold_row = r_idx in row_bold
        cells = []
        for c_idx, c in enumerate(columns):
            value = row.get(c.key)
            text = str(value) if value not in (None, "") else blank_as
            style = _STYLE_MATRIX[(c.align, bold_row or c.bold)]
            tone = tones.get((r_idx, c.key))
            if tone:
                style = _tone_variant(style, tone)
                bg_cells.append((c_idx, r_idx + 1, tone))
            cells.append(p(text, style))
        body.append(cells)

    table = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for r in band_rows:
        style_cmds.append(("BACKGROUND", (0, r), (-1, r), BAND))
    for c_idx, r_idx, tone in bg_cells:
        style_cmds.append(("BACKGROUND", (c_idx, r_idx), (c_idx, r_idx), _TONE_BG[tone]))
    for r in row_bold:
        style_cmds.append(("LINEABOVE", (0, r + 1), (-1, r + 1), 0.6, INK))
    table.setStyle(TableStyle(style_cmds))
    return table


def key_value_table(
    rows: list[tuple[str, str]],
    page_width: float,
    *,
    bold_rows: set[int] | None = None,
    rule_above: set[int] | None = None,
    label_weight: float = 2.2,
    value_weight: float = 1.0,
    value_align: str = "right",
) -> Table:
    """Label/value pairs, one per row — 'Meeting details', waterfall-style summaries, fund overviews.

    `value_align="right"` suits $ amounts (the default — waterfalls, fee tables);
    pass `"left"` for free-text values (attendees, objectives, addresses).
    """
    bold_rows = bold_rows or set()
    rule_above = rule_above or set()
    total = label_weight + value_weight
    widths = [page_width * label_weight / total, page_width * value_weight / total]

    body = []
    for i, (label, value) in enumerate(rows):
        lstyle = CELL_BOLD if i in bold_rows else CELL
        vstyle = _STYLE_MATRIX[(value_align, i in bold_rows)]
        body.append([p(label, lstyle), p(value, vstyle)])

    table = Table(body, colWidths=widths, hAlign="LEFT")
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, max(len(body) - 2, 0)), 0.3, GRID),
    ]
    for r in rule_above:
        cmds.append(("LINEABOVE", (0, r), (-1, r), 0.6, INK))
    table.setStyle(TableStyle(cmds))
    return table


def two_column_layout(left: list, right: list, page_width: float, *, gap: float = 14) -> Table:
    """Side-by-side flowable blocks (e.g. Fund overview / Financial position panels)."""
    col_w = (page_width - gap) / 2
    table = Table([[left, right]], colWidths=[col_w, col_w], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), gap),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


# ---------- document assembly ----------

@dataclass
class Section:
    """One report section: a title, its flowables, and the page geometry it was designed for."""
    key: str
    title: str
    story: list = field(default_factory=list)
    page_size: tuple[float, float] = A4
    margin: float = DEFAULT_MARGIN

    @property
    def usable_width(self) -> float:
        return self.page_size[0] - 2 * self.margin


def _footer(page_size, margin: float, label: str):
    def draw(canvas: Canvas, doc) -> None:
        canvas.saveState()
        y = margin * 0.5
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.5)
        canvas.line(margin, y + 10, page_size[0] - margin, y + 10)
        canvas.setFont(_FONT, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, y, label)
        canvas.drawRightString(page_size[0] - margin, y, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def render_document(
    story: list,
    *,
    page_size: tuple[float, float] = A4,
    margin: float = DEFAULT_MARGIN,
    title: str = "",
    footer_label: str = "Advisory Partners",
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=page_size,
        leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin,
        title=title,
    )
    draw_footer = _footer(page_size, margin, footer_label)
    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buf.getvalue()


def render_section_pdf(section: Section) -> bytes:
    """Render one section standalone — useful for previewing/testing a section on its own."""
    return render_document(
        section.story,
        page_size=section.page_size,
        margin=section.margin,
        title=section.title,
        footer_label=f"Advisory Partners · {section.title}",
    )


def combine_sections(sections: list[Section], *, title: str = "Client Review Pack") -> bytes:
    """Concatenate same-page-size sections into one PDF, with a page break between each.

    Narrow first cut, not the general combiner described in the module docstring:
    every section passed in must share `page_size`. Combining portrait A4 sections
    with the landscape register-style ones is the deferred follow-up.
    """
    if not sections:
        raise ValueError("combine_sections requires at least one section")
    page_size = sections[0].page_size
    mismatched = [s.key for s in sections if s.page_size != page_size]
    if mismatched:
        raise ValueError(
            f"combine_sections only supports one shared page size for now; "
            f"{mismatched} differ from '{sections[0].key}' ({page_size}). "
            "Mixed-size combination is the deferred follow-up — see module docstring."
        )
    story: list = []
    for i, section in enumerate(sections):
        if i:
            story.append(PageBreak())
        story.extend(section.story)
    return render_document(story, page_size=page_size, margin=sections[0].margin, title=title, footer_label=title)
