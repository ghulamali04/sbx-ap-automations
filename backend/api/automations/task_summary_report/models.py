
from __future__ import annotations

import os
from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from api.automations.email_recipients import normalize_email_recipients


def field_map() -> dict[str, str]:
   
    return {
        "head_client": os.getenv("TASK_FIELD_HEAD_CLIENT", "Head Client"),
        "head_client_id": os.getenv("TASK_FIELD_HEAD_CLIENT_ID", "Head Client ID"),
        "custom_status": os.getenv("TASK_FIELD_CUSTOM_STATUS", "Custom Status"),
        "owner": os.getenv("TASK_FIELD_OWNER", "Owner"),
        "preparer": os.getenv("TASK_FIELD_PREPARER", "Who Prepares (BAS/IAS)"),
        "cash_account": os.getenv("TASK_FIELD_CASH_ACCOUNT", "Cash Account"),
        "td_value": os.getenv("TASK_FIELD_TD_VALUE", "Term Deposit Value"),
        "td_term": os.getenv("TASK_FIELD_TD_TERM", "Current Term"),
        "provider": os.getenv("TASK_FIELD_PROVIDER", "Provider"),
        "maturity_instruction": os.getenv("TASK_FIELD_MATURITY_INSTRUCTION", "Maturity Instruction"),
        "td_roa_reason": os.getenv("TASK_FIELD_TD_ROA_REASON", "TD - ROA Reason"),
        "notes": os.getenv("TASK_FIELD_NOTES", "Notes"),
    }


class ReportRequest(BaseModel):
    """Payload for the POST /reports/task-summary endpoint."""

    head_client_id: str = Field(
        ...,
        description="Zoho value identifying the head client to report on — matched "
                    "against the configured head-client field on each task/project.",
    )
    active_only: bool = Field(
        default=False,
        description="Only search Zoho projects Zoho marks active. Defaults to false "
                    "so the snapshot includes active and historical tasks.",
    )
    requestor_email: str | None = Field(
        default=None,
        description="Legacy single-recipient field. Prefer request_emails.",
    )
    request_email: str | None = Field(
        default=None,
        description="Power Automate single-recipient field. Prefer request_emails.",
    )
    request_emails: list[str] = Field(
        default_factory=list,
        description="One or more recipients returned with the completed PDF to "
                    "Power Automate. Required unless dry_run is true.",
    )
    webhook_url: str | None = Field(
        default=None,
        description="Power Automate flow to POST the PDF to. Falls back to "
                    "TASK_SUMMARY_WEBHOOK_URL, then POWER_AUTOMATE_WEBHOOK_URL.",
    )
    filename: str | None = Field(
        default=None,
        description="PDF filename sent to the flow. Defaults to "
                    "'task-summary-<head_client_id>-<date>.pdf'.",
    )
    dry_run: bool = Field(
        default=False, description="Render the PDF but skip delivery to Power Automate."
    )

    @field_validator("request_emails", mode="before")
    @classmethod
    def normalize_request_emails(cls, value) -> list[str]:
        return normalize_email_recipients(value)

    @model_validator(mode="after")
    def merge_legacy_requestor_email(self) -> "ReportRequest":
        self.request_emails = normalize_email_recipients(
            [
                *self.request_emails,
                self.request_email,
                self.requestor_email,
            ]
        )
        return self

    def resolved_request_emails(self) -> list[str]:
        return list(self.request_emails)

    def resolved_webhook(self) -> str | None:
        return (
            self.webhook_url
            or os.getenv("TASK_SUMMARY_WEBHOOK_URL")
            or os.getenv("POWER_AUTOMATE_WEBHOOK_URL")
            or None
        )

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
    filename: str = ""
    # Absolute link to the rendered PDF, filled in by the status route (not stored)
    # so it always reflects the host the caller actually reached. None until the
    # PDF exists — a failed or still-running job has nothing to show.
    pdf_url: str | None = None
