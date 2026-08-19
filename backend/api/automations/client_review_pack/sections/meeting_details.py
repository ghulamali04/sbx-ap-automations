"""
Meeting Notes section — the pack's compact meeting-details/agenda/action-items
page (sample pack p.1), distinct from the full `automations/meeting_notes`
transcript-summary automation. Input is whatever meeting record the caller
resolves (a scheduled review meeting, a file note) — this module only lays it out.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from reportlab.platypus import Spacer

from api.lib import pdf_builder as pb
from api.automations.client_review_pack.sections import PORTRAIT_A4, Section


class AgendaItem(BaseModel):
    item: str
    presenter: str | None = None


class ActionItem(BaseModel):
    action: str
    who: str | None = None
    when: str | None = None
    status: str | None = None


class MeetingDetailsData(BaseModel):
    client_name: str
    date: str | None = None
    time: str | None = None
    location: str | None = None
    attendees: str | None = None
    objectives: str | None = None
    agenda: list[AgendaItem] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)


def build_meeting_details_section(data: MeetingDetailsData) -> Section:
    section = Section(key="meeting_details", title="Meeting Notes", page_size=PORTRAIT_A4)
    width = section.usable_width
    section.story += pb.masthead_block("Meeting Notes", meta=[f"<b>Client:</b> {data.client_name}"])

    section.story.append(pb.section_heading("Meeting details"))
    detail_rows = [
        ("Date", data.date or "—"),
        ("Time", data.time or "—"),
        ("Location", data.location or "—"),
        ("Attendees", data.attendees or "—"),
        ("Objectives", data.objectives or "—"),
    ]
    section.story.append(pb.key_value_table(
        detail_rows, width, label_weight=1.0, value_weight=2.8, value_align="left",
    ))
    section.story.append(Spacer(1, 14))

    if data.agenda:
        section.story.append(pb.section_heading("Agenda"))
        columns = [
            pb.Column("Agenda item", "item", weight=3),
            pb.Column("Presenter", "presenter", weight=1),
        ]
        rows = [{"item": a.item, "presenter": a.presenter} for a in data.agenda]
        section.story.append(pb.data_table(columns, rows, width))
        section.story.append(Spacer(1, 14))

    if data.action_items:
        section.story.append(pb.section_heading("Action items"))
        columns = [
            pb.Column("Action", "action", weight=3),
            pb.Column("Who?", "who", weight=1),
            pb.Column("When?", "when", weight=1),
            pb.Column("Status", "status", weight=1),
        ]
        rows = [
            {"action": a.action, "who": a.who, "when": a.when, "status": a.status}
            for a in data.action_items
        ]
        section.story.append(pb.data_table(columns, rows, width))

    return section
