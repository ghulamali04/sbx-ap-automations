"""
Request/response models for the head-client Task Summary PDF report.

Zoho Projects custom-field *labels* (Project Group, Head Client, Term Deposit
Value, ...) were not confirmed against live Zoho data when this was built, so
every label this report reads is resolved through field_map() at call time
(env-driven, sensible defaults) rather than hardcoded — point TASK_FIELD_* at
the real labels once known, no code change needed. See read_task_field() in
api.automations.completion_overview.service for how a label is matched against
a task/project's custom_fields.
"""
from __future__ import annotations

import os
from datetime import date

from pydantic import BaseModel, Field


def field_map() -> dict[str, str]:
    """Zoho task/project custom-field labels this report reads, overridable via env."""
    return {
        "head_client": os.getenv("TASK_FIELD_HEAD_CLIENT", "Head Client"),
        "head_client_id": os.getenv("TASK_FIELD_HEAD_CLIENT_ID", "Head Client ID"),
        "client_group": os.getenv("TASK_FIELD_CLIENT_GROUP", "Client Group"),
        "project_group": os.getenv("TASK_FIELD_PROJECT_GROUP", "Project Group"),
        "custom_status": os.getenv("TASK_FIELD_CUSTOM_STATUS", "Custom Status"),
        "owner": os.getenv("TASK_FIELD_OWNER", "Owner"),
        "preparer": os.getenv("TASK_FIELD_PREPARER", "Who Prepares (BAS/IAS)"),
        "cash_account": os.getenv("TASK_FIELD_CASH_ACCOUNT", "Cash Account"),
        "td_value": os.getenv("TASK_FIELD_TD_VALUE", "Term Deposit Value"),
        "td_term": os.getenv("TASK_FIELD_TD_TERM", "Current Term"),
        "provider": os.getenv("TASK_FIELD_PROVIDER", "Provider"),
        "maturity_instruction": os.getenv("TASK_FIELD_MATURITY_INSTRUCTION", "Maturity Instruction"),
        "td_roa_reason": os.getenv("TASK_FIELD_TD_ROA_REASON", "TD - ROA Reason"),
        "latest_comment": os.getenv("TASK_FIELD_LATEST_COMMENT", "Latest Comment"),
    }


class ReportRequest(BaseModel):
    """Payload for the POST /reports/task-summary endpoint."""

    head_client_id: str = Field(
        ...,
        description="Zoho value identifying the head client to report on — matched "
                    "against the configured head-client field on each task/project.",
    )
    active_only: bool = Field(
        default=True, description="Only search Zoho projects Zoho marks active."
    )
    webhook_url: str | None = Field(
        default=None,
        description="Power Automate flow to POST the PDF to. "
                    "Falls back to POWER_AUTOMATE_WEBHOOK_URL.",
    )
    filename: str | None = Field(
        default=None,
        description="PDF filename sent to the flow. Defaults to "
                    "'task-summary-<head_client_id>-<date>.pdf'.",
    )
    dry_run: bool = Field(
        default=False, description="Render the PDF but skip delivery to Power Automate."
    )

    def resolved_webhook(self) -> str | None:
        return self.webhook_url or os.getenv("POWER_AUTOMATE_WEBHOOK_URL") or None

    def resolved_filename(self) -> str:
        return self.filename or f"task-summary-{self.head_client_id}-{date.today().isoformat()}.pdf"


class ReportAccepted(BaseModel):
    """202 body — the job was queued; poll status_url."""
    job_id: str
    status: str
    status_url: str


class JobResult(BaseModel):
    job_id: str
    status: str  # queued | running | completed | failed
    head_client_id: str = ""
    head_client_name: str | None = None
    projects_scanned: int = 0
    tasks_matched: int = 0
    bytes_pdf: int = 0
    delivered: bool = False
    error: str | None = None
