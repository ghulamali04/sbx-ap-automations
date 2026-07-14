"""
Request/response models for the completion-overview report endpoint.

The contract is deliberately generic (spec §6.7): the caller (a Power Automate
flow) supplies the metric field, the groupings, and where each grouping's charts
should land. Nothing here is BAS/IAS-specific — a different report reuses the same
endpoint with a different payload.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Grouping(BaseModel):
    """One grouping to chart: a Zoho task field, and where its charts go."""
    field: str = Field(..., description="Zoho task field to group by, e.g. 'Partner'.")
    output_folder: str = Field(
        ..., description="SharePoint folder these charts belong in (passed to the webhook)."
    )


class ReportRequest(BaseModel):
    """Payload from the calling flow.

    Project selection: pass explicit `project_ids`, OR omit them and let the job
    resolve the latest active project per entry in `name_filters`.
    """
    project_ids: list[str] = Field(
        default_factory=list,
        description="Explicit Zoho project ids. If empty, resolve by name_filters.",
    )
    name_filters: list[str] = Field(
        default_factory=list,
        description="Project-name substrings, e.g. ['BAS', 'IAS']. Used when project_ids is empty.",
    )
    active_only: bool = Field(
        default=True, description="Only include projects Zoho marks active."
    )
    metric_field: str = Field(
        ..., description="Zoho task field to average, e.g. 'Completion Percentage'."
    )
    groupings: list[Grouping] = Field(
        ..., min_length=1, description="One or more groupings to chart per project."
    )
    sharepoint_webhook_url: str = Field(
        ..., description="Power Automate HTTP trigger that stores a posted chart in SharePoint."
    )


class ReportAccepted(BaseModel):
    """202 body — the job was queued; poll `status_url`."""
    job_id: str
    status: str
    status_url: str


class ChartResult(BaseModel):
    project_id: str
    project_name: str
    grouping: str
    filename: str
    output_folder: str
    people: int
    tasks_included: int
    tasks_excluded: int
    delivered: bool
    error: str | None = None


class JobResult(BaseModel):
    job_id: str
    status: str  # queued | running | completed | failed
    charts: list[ChartResult] = Field(default_factory=list)
    projects_matched: int = 0
    error: str | None = None
