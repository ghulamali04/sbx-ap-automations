"""
Group Structure section — the client entity-relationship diagram (sample pack
p.23): rows of company/trust boxes connecting down to the individual.

Unlike the other sections this one is a diagram, not a table, drawn with
`reportlab.graphics.shapes` primitives onto one `Drawing` flowable. The caller
supplies the layout explicitly as ordered levels (top row first) plus an edge
list — general graph auto-layout is out of scope; group structures are small
and hand-arranged in practice (per the sample: companies -> holding companies ->
family trust -> individual).
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from reportlab.graphics.shapes import Drawing, Ellipse, Line, Rect, String
from reportlab.lib import colors

from api.lib import pdf_builder as pb
from api.automations.client_review_pack.sections import LANDSCAPE_A4, Section

_BOX_W = 160
_HEADER_H = 16
_FIELD_H = 10
_PAD = 5
_LEVEL_GAP = 46
_ROOT_W, _ROOT_H = 100, 40
_TRUST_FILL = colors.HexColor("#b23b3b")


class EntityBox(BaseModel):
    id: str
    heading: str
    fields: list[tuple[str, str]] = Field(default_factory=list)
    kind: str = "company"  # "company" | "trust" — trust renders with a red header bar


class GroupStructureData(BaseModel):
    client_name: str
    as_at: str | None = None
    levels: list[list[EntityBox]]  # top row first
    edges: list[tuple[str, str]]  # (parent id, child id); use "__root__" as the individual
    root_label: str


def _box_height(entity: EntityBox) -> float:
    return _HEADER_H + len(entity.fields) * _FIELD_H + _PAD * 2


def _draw_box(d: Drawing, x: float, y_top: float, entity: EntityBox) -> tuple[tuple[float, float], tuple[float, float]]:
    h = _box_height(entity)
    cx = x + _BOX_W / 2
    y_bottom = y_top - h
    fill = _TRUST_FILL if entity.kind == "trust" else pb.TEAL
    d.add(Rect(x, y_bottom, _BOX_W, h, fillColor=colors.white, strokeColor=pb.GRID, strokeWidth=0.6))
    d.add(Rect(x, y_top - _HEADER_H, _BOX_W, _HEADER_H, fillColor=fill, strokeColor=fill))
    d.add(String(x + 4, y_top - _HEADER_H + 4.5, entity.heading, fontName="Helvetica-Bold", fontSize=7, fillColor=colors.white))
    for i, (label, value) in enumerate(entity.fields):
        fy = y_top - _HEADER_H - _PAD - (i + 1) * _FIELD_H + 2
        d.add(String(x + 4, fy, f"{label}:", fontName="Helvetica-Bold", fontSize=6, fillColor=pb.INK))
        d.add(String(x + 48, fy, value, fontName="Helvetica", fontSize=6, fillColor=pb.INK))
    return (cx, y_top), (cx, y_bottom)


def _chart_height(data: GroupStructureData) -> float:
    total = 10.0
    for level in data.levels:
        total += max(_box_height(e) for e in level) + _LEVEL_GAP
    return total + _ROOT_H + 20


def _org_chart_drawing(data: GroupStructureData, width: float, height: float) -> Drawing:
    d = Drawing(width, height)
    anchors: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {}

    y_top = height - 10
    for level in data.levels:
        n = len(level)
        slot_w = width / n
        row_height = max(_box_height(e) for e in level)
        for i, entity in enumerate(level):
            x = i * slot_w + (slot_w - _BOX_W) / 2
            anchors[entity.id] = _draw_box(d, x, y_top, entity)
        y_top -= row_height + _LEVEL_GAP

    root_cx = width / 2
    root_cy = y_top - _ROOT_H / 2 + 10
    d.add(Ellipse(root_cx, root_cy, _ROOT_W / 2, _ROOT_H / 2, fillColor=colors.HexColor("#d9d9d9"), strokeColor=pb.GRID))
    d.add(String(root_cx, root_cy - 3, data.root_label, fontName="Helvetica-Bold", fontSize=8,
                 fillColor=pb.INK, textAnchor="middle"))
    anchors["__root__"] = ((root_cx, root_cy + _ROOT_H / 2), (root_cx, root_cy - _ROOT_H / 2))

    for parent_id, child_id in data.edges:
        if parent_id not in anchors or child_id not in anchors:
            continue
        _, parent_bottom = anchors[parent_id]
        child_top, _ = anchors[child_id]
        d.add(Line(parent_bottom[0], parent_bottom[1], child_top[0], child_top[1], strokeColor=pb.GRID, strokeWidth=0.8))

    return d


def build_group_structure_section(data: GroupStructureData) -> Section:
    title = f"{data.client_name} — Group Structure"
    section = Section(key="group_structure", title=title, page_size=LANDSCAPE_A4)
    width = section.usable_width
    section.story += pb.masthead_block(title, subtitle=f"As at {data.as_at}" if data.as_at else None)
    section.story.append(_org_chart_drawing(data, width, _chart_height(data)))
    return section
