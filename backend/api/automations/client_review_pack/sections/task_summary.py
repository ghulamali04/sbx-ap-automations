"""
Task Summary section — the Zoho task register (sample pack p.21-22, "Dan Core
Group — Task Summary"). Ported from the now-removed `task_summary_report`
automation's `pdf.py` (reportlab, teal Advisory Partners branding — see git
history at e1bd815) onto the shared `pdf_builder` foundation; this module owns
layout only; that automation's Zoho data-fetch/service layer is not ported.

Landscape A3 with narrow margins, matching the original: the register runs to
twelve columns including two long free-text ones (Notes, TD - ROA Reason).
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from reportlab.platypus import Spacer

from api.lib import pdf_builder as pb
from api.automations.client_review_pack.sections import LANDSCAPE_A3, Section

_NOT_APPLICABLE = "Not applicable"

# The task register intentionally excludes Project Group, Latest Comment, and
# Head Client Name — Project Group remains an internal classification.
_COLUMNS = [
    pb.Column("Project Name", "project_name", 95),
    pb.Column("Task Name", "task_name", 118),
    pb.Column("Custom Status", "custom_status", 62),
    pb.Column("Owner", "owner", 62),
    pb.Column("Who prepares BAS/IAS", "preparer", 58),
    pb.Column("Cash account", "cash_account", 62),
    pb.Column("Term Deposit Value", "td_value", 58, align="right"),
    pb.Column("Current Term", "td_term", 48),
    pb.Column("Provider", "provider", 58),
    pb.Column("Maturity instruction", "maturity_instruction", 66),
    pb.Column("TD - ROA Reason", "td_roa_reason", 78),
    pb.Column("Notes", "notes", 150),
]

_COMMENT_COLUMNS = [
    pb.Column("Task", "task", weight=22),
    pb.Column("Project", "project", weight=16),
    pb.Column("Summary", "summary", weight=62),
]


class TaskRow(BaseModel):
    project_name: str
    task_name: str
    custom_status: str = ""
    owner: str = ""
    preparer: str = ""
    cash_account: str = ""
    td_value: float | None = None
    td_term: str = ""
    provider: str = ""
    maturity_instruction: str = ""
    td_roa_reason: str = ""
    notes: str = ""
    td_applicable: bool = True  # False for tasks with no term-deposit fields (e.g. non-FP tasks)


class SelectedComment(BaseModel):
    task: str
    project: str
    summary: str


class TaskSummaryData(BaseModel):
    head_client_id: str
    tasks_total: int
    prepared_by: str
    as_at: str
    rows: list[TaskRow] = Field(default_factory=list)
    selected_comments: list[SelectedComment] = Field(default_factory=list)


def _row_dict(r: TaskRow) -> dict:
    if not r.td_applicable:
        return {
            "project_name": r.project_name, "task_name": r.task_name, "custom_status": r.custom_status,
            "owner": r.owner, "preparer": r.preparer, "cash_account": _NOT_APPLICABLE,
            "td_value": _NOT_APPLICABLE, "td_term": _NOT_APPLICABLE, "provider": _NOT_APPLICABLE,
            "maturity_instruction": _NOT_APPLICABLE, "td_roa_reason": _NOT_APPLICABLE, "notes": r.notes,
        }
    return {
        "project_name": r.project_name, "task_name": r.task_name, "custom_status": r.custom_status,
        "owner": r.owner, "preparer": r.preparer, "cash_account": r.cash_account,
        "td_value": pb.fmt_money(r.td_value, decimals=0) if r.td_value is not None else "",
        "td_term": r.td_term, "provider": r.provider, "maturity_instruction": r.maturity_instruction,
        "td_roa_reason": r.td_roa_reason, "notes": r.notes,
    }


def build_task_summary_section(data: TaskSummaryData) -> Section:
    section = Section(key="task_summary", title="Client Report", page_size=LANDSCAPE_A3, margin=pb.WIDE_MARGIN)
    width = section.usable_width

    section.story += pb.masthead_block(
        "Client Report",
        subtitle=f"{data.tasks_total} tasks · Prepared by {data.prepared_by} · As at {data.as_at}",
    )

    section.story.append(pb.section_heading("Task register"))
    rows = [_row_dict(r) for r in data.rows]
    section.story.append(pb.data_table(_COLUMNS, rows, width, band_key="project_name", blank_as=""))

    if data.selected_comments:
        section.story.append(Spacer(1, 16))
        section.story.append(pb.section_heading("Selected Task Comments"))
        comment_rows = [{"task": c.task, "project": c.project, "summary": c.summary} for c in data.selected_comments]
        section.story.append(pb.data_table(_COMMENT_COLUMNS, comment_rows, width))

    return section
