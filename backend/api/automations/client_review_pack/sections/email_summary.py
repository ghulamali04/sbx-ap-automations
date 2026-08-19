"""Summary of Emails section — correspondence log (sample pack p.2)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from api.lib import pdf_builder as pb
from api.automations.client_review_pack.sections import PORTRAIT_A4, Section


class EmailSummaryEntry(BaseModel):
    date_period: str
    topic: str
    summary: str
    outcome: str


class EmailSummaryData(BaseModel):
    client_name: str
    period_label: str  # e.g. "September 2024 – June 2026"
    entries: list[EmailSummaryEntry] = Field(default_factory=list)


def build_email_summary_section(data: EmailSummaryData) -> Section:
    section = Section(key="email_summary", title="Summary of Emails", page_size=PORTRAIT_A4)
    width = section.usable_width
    section.story += pb.masthead_block(
        "Summary of Emails",
        meta=[f"<b>Client:</b> {data.client_name}"],
        subtitle=f"Correspondence summary · {data.period_label}",
    )

    columns = [
        pb.Column("Date / period", "date_period", weight=1.1),
        pb.Column("Topic", "topic", weight=1.6, bold=True),
        pb.Column("Summary", "summary", weight=3.6),
        pb.Column("Outcome / status", "outcome", weight=1.8, bold=True),
    ]
    rows = [e.model_dump() for e in data.entries]
    section.story.append(pb.data_table(columns, rows, width))
    return section
