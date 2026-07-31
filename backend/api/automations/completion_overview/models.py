"""
Request/response models for the completion-overview report endpoint.

The contract stays generic (spec §6.7) — metric field, groupings and destinations
can all be overridden per call — but every one of those has a sensible default, so
the common case is a body as small as:

    {"projects_include_IDs": ["123"]}

or a keyword-driven selection:

    {"projects_include_Names": ["BAS"], "projects_exclude_Names": ["Overdue"]}
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from pydantic import BaseModel, Field, field_validator

from api.automations.email_recipients import normalize_email_recipients


def default_group_by() -> list[str]:
    """Zoho task fields to chart, one stacked panel each, in this order."""
    raw = os.getenv("COMPLETION_GROUP_BY", "Partner,Accountant")
    return [f.strip() for f in raw.split(",") if f.strip()]


class ReportRequest(BaseModel):
    """Payload from the calling flow.

    Project selection runs as include-then-exclude:
      - `projects_include_IDs` non-empty -> use exactly those ids, and
        `projects_include_Names` is ignored entirely.
      - otherwise `projects_include_Names` -> every project whose name contains any
        of the keywords (case-insensitive substring match).
      - neither -> every project.
    Then:
      - drop every id in `projects_exclude_IDs`.
      - drop every project whose name contains a keyword in
        `projects_exclude_Names`.

    At least one include or exclude filter must be non-empty; see
    `validate_selection`.
    """
    projects_include_IDs: list[str] = Field(
        default_factory=list, description="Explicit Zoho project ids to report on."
    )
    projects_exclude_IDs: list[str] = Field(
        default_factory=list, description="Zoho project ids to drop from the selection."
    )
    projects_include_Names: list[str] = Field(
        default_factory=list,
        description="Project-name keywords (e.g. 'BAS', 'July'). Every project whose "
                    "name contains one of these is included. Ignored when "
                    "projects_include_IDs is non-empty.",
    )
    projects_exclude_Names: list[str] = Field(
        default_factory=list,
        description="Project-name keywords (e.g. 'Overdue'). Every project whose name "
                    "contains one of these is dropped, in addition to exclusions by id.",
    )
    projects_include_Emails: list[str] = Field(
        default_factory=list,
        description="One or more recipients received from Power Automate and "
                    "returned with the generated report artifacts.",
    )
    email_subject: str | None = Field(
        default=None,
        max_length=255,
        description="Email subject returned to Power Automate. Defaults to a "
                    "dated Completion Overview Report subject.",
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
                    "Falls back to COMPLETION_OVERVIEW_WEBHOOK_URL, then "
                    "POWER_AUTOMATE_WEBHOOK_URL.",
    )
    filename: str | None = Field(
        default=None,
        description="Label for the batch sent to the flow. Defaults to 'report-<today>'.",
    )
    dry_run: bool = Field(
        default=False, description="Render charts but skip delivery."
    )

    @field_validator("projects_include_Emails", mode="before")
    @classmethod
    def normalize_project_emails(cls, value) -> list[str]:
        return normalize_email_recipients(value)

    @field_validator("email_subject", mode="before")
    @classmethod
    def normalize_email_subject(cls, value) -> str | None:
        """Clean the caller-supplied subject before it reaches the email/webhook.

        Blank (or whitespace-only) collapses to None so `resolved_email_subject`
        can fall back to the dated default. Control characters — CR/LF above all —
        are stripped to prevent header injection, and internal runs of whitespace
        are collapsed to single spaces.
        """
        if value is None:
            return None
        text = str(value)
        # Drop C0/C1 control characters (includes CR, LF, tabs) then collapse
        # any remaining whitespace runs to a single space.
        text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text or None

    @field_validator(
        "projects_include_IDs",
        "projects_exclude_IDs",
        "projects_include_Names",
        "projects_exclude_Names",
        mode="before",
    )
    @classmethod
    def normalize_project_filters(cls, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    decoded = json.loads(stripped)
                except json.JSONDecodeError:
                    decoded = value
                if isinstance(decoded, list):
                    value = decoded
        values = [value] if isinstance(value, str) else value
        normalized: list[str] = []
        seen: set[str] = set()
        for item in values:
            text = str(item).strip()
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                normalized.append(text)
        return normalized

    def validate_selection(self) -> str | None:
        """Return an error message when the body cannot select anything to report on.

        A run needs at least one include or exclude filter so an accidental empty
        body cannot report every project in the portal.
        """
        if (
            self.projects_include_IDs
            or self.projects_exclude_IDs
            or self.projects_include_Names
            or self.projects_exclude_Names
        ):
            return None
        return (
            "Provide projects_include_IDs (explicit project ids), "
            "projects_include_Names (name keywords to include), or "
            "projects_exclude_IDs/projects_exclude_Names (projects to exclude) "
            "to generate a report."
        )

    def resolved_webhook(self) -> str | None:
        return (
            self.webhook_url
            or os.getenv("COMPLETION_OVERVIEW_WEBHOOK_URL")
            or os.getenv("POWER_AUTOMATE_WEBHOOK_URL")
            or None
        )

    def resolved_filename(self) -> str:
        return self.filename or f"report-{date.today().isoformat()}"

    def resolved_email_subject(self) -> str:
        if self.email_subject and self.email_subject.strip():
            return self.email_subject.strip()
        return f"Completion Overview Report - {date.today().isoformat()}"


class ReportAccepted(BaseModel):
    """202 body — the job was queued; poll `status_url`."""
    job_id: str
    status: str
    status_url: str


class MetricSummary(BaseModel):
    """One displayed bar and the current tasks contributing to its percentage."""
    label: str
    value: float
    count: int


class PanelSummary(BaseModel):
    """Per-grouping detail behind one panel of a combined chart."""
    grouping: str
    people: int
    tasks_included: int
    tasks_excluded: int
    statistics: list[MetricSummary] = Field(default_factory=list)


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
