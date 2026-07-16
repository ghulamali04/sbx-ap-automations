"""
Request/response models for the completion-overview report endpoint.

The contract stays generic (spec §6.7) — metric field, groupings and destinations
can all be overridden per call — but every one of those has a sensible default, so
the common case is a body as small as:

    {"projects_include": ["123"], "projects_excluded": []}

or even `{}`, which selects the latest BAS and IAS projects automatically.
"""
from __future__ import annotations

import os
from datetime import date

from pydantic import BaseModel, Field


def default_group_by() -> list[str]:
    """Zoho task fields to chart, one stacked panel each, in this order."""
    raw = os.getenv("COMPLETION_GROUP_BY", "Partner,Accountant")
    return [f.strip() for f in raw.split(",") if f.strip()]


class ReportRequest(BaseModel):
    """Payload from the calling flow.

    Project selection:
      - `projects_include` given -> use exactly those ids.
      - otherwise              -> match `name_filters` and take the latest month
                                  available for each (e.g. the newest BAS and the
                                  newest IAS).
    `projects_excluded` is always applied last, so it can drop an id that either
    path selected.
    """
    projects_include: list[str] = Field(
        default_factory=list, description="Explicit Zoho project ids to report on."
    )
    projects_excluded: list[str] = Field(
        default_factory=list, description="Zoho project ids to drop from the selection."
    )
    name_filters: list[str] = Field(
        default_factory=lambda: ["BAS", "IAS"],
        description="Project-name substrings used when projects_include is empty.",
    )
    active_only: bool = Field(
        default=True, description="Only include projects Zoho marks active."
    )
    metric_field: str = Field(
        default="Completion Percentage", description="Zoho task field to average."
    )
    group_by: list[str] = Field(
        default_factory=default_group_by,
        description="Zoho task fields to group by — one stacked panel each, in one combined PNG.",
    )
    webhook_url: str | None = Field(
        default=None,
        description="Power Automate flow to POST the charts to. "
                    "Falls back to POWER_AUTOMATE_WEBHOOK_URL.",
    )
    filename: str | None = Field(
        default=None,
        description="Label for the batch sent to the flow. Defaults to 'report-<today>'.",
    )
    dry_run: bool = Field(
        default=False, description="Render charts but skip delivery."
    )

    def resolved_webhook(self) -> str | None:
        return self.webhook_url or os.getenv("POWER_AUTOMATE_WEBHOOK_URL") or None

    def resolved_filename(self) -> str:
        return self.filename or f"report-{date.today().isoformat()}"


class ReportAccepted(BaseModel):
    """202 body — the job was queued; poll `status_url`."""
    job_id: str
    status: str
    status_url: str


class PanelSummary(BaseModel):
    """Per-grouping detail behind one panel of a combined chart."""
    grouping: str
    people: int
    tasks_included: int
    tasks_excluded: int


class ChartResult(BaseModel):
    project_id: str
    project_name: str
    filename: str
    panels: list[PanelSummary] = Field(default_factory=list)
    tasks_total: int = 0
    bytes_png: int = 0
    delivered: bool = False
    error: str | None = None


class JobResult(BaseModel):
    job_id: str
    status: str  # queued | running | completed | failed
    charts: list[ChartResult] = Field(default_factory=list)
    projects_matched: int = 0
    projects_selected: list[str] = Field(default_factory=list)
    error: str | None = None
