
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone

from api.automations.zoho import client
from api.automations.completion_overview.service import read_task_field
from api.automations.task_summary_report import artifacts, azure_openai, power_automate
from api.automations.task_summary_report.models import JobResult, ReportRequest, field_map
from api.automations.task_summary_report.pdf import ReportData, TaskRow, render_task_summary_pdf

REPORT_TITLE = "Client Snapshot Report"

# Project Group is derived from the Project Name's prefix (before the first
# " - "), not read from a custom field. "FP" is kept alongside "FB" because the
# approved sample report's own project names use "FP -" (e.g. "FP - Reviews");
# drop "FB" if it turns out not to be a real prefix in your data.
_PROJECT_GROUP_PREFIXES = {
    "FB": "Financial Planning",
    "FP": "Financial Planning",
    "BS": "Business Services",
    "SMSF": "SMSF",
}


# ---------- value helpers ----------

def _display(value) -> str:
    """Normalise any Zoho field value (str, dict, None) to a display string."""
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("name") or value.get("full_name") or value.get("value") or ""
    return str(value).strip()


def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^0-9.\-]", "", str(value))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def _strip_html(value) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", text).strip()


def _first_present(*values):
    for v in values:
        if v not in (None, ""):
            return v
    return None


def _owner_name(task: dict, fields: dict) -> str:
    value = read_task_field(task, fields["owner"])
    if value:
        return _display(value)
    owners = (task.get("details") or {}).get("owners") or []
    if owners:
        return _display(owners[0])
    return _display(task.get("owner_name"))


def _status_name(task: dict, fields: dict) -> str:
    value = read_task_field(task, fields["custom_status"])
    if value:
        return _display(value)
    return _display(task.get("status")) or "Not started"


def _infer_project_group(project_name: str) -> str:
    """FB/FP -> Financial Planning, BS -> Business Services, SMSF -> SMSF, else Uncategorized."""
    prefix = re.split(r"\s*-\s*", project_name, maxsplit=1)[0].strip().upper()
    return _PROJECT_GROUP_PREFIXES.get(prefix, "Uncategorized")


# ---------- head-client matching ----------

def _field_value(source: dict, key: str):
    value = read_task_field(source, key)
    if isinstance(value, dict):
        value = value.get("id") or value.get("value") or value.get("name")
    return value


def _matches_head_client(task: dict, project: dict, head_client_id: str, fields: dict) -> bool:
    needle = head_client_id.strip().lower()
    for source in (task, project):
        for key in (fields["head_client_id"], fields["head_client"]):
            value = _field_value(source, key)
            if value is not None and str(value).strip().lower() == needle:
                return True
    return False


async def resolve_matching_tasks(
    req: ReportRequest, fields: dict
) -> tuple[list[tuple[dict, dict]], int]:
    
    projects = await client.list_projects()
    if req.active_only:
        projects = [p for p in projects if str(p.get("status", "")).lower() == "active"]

    matched: list[tuple[dict, dict]] = []
    for project in projects:
        tasks = await client.get_all_tasks(str(project.get("id")))
        for task in tasks:
            if _matches_head_client(task, project, req.head_client_id, fields):
                matched.append((task, project))
    return matched, len(projects)


# ---------- row building ----------

def _build_rows(matched: list[tuple[dict, dict]], fields: dict) -> list[TaskRow]:
    rows = []
    for task, project in matched:
        project_name = _display(project.get("name"))
        rows.append(TaskRow(
            project_name=project_name,
            task_name=_display(task.get("name")),
            project_group=_infer_project_group(project_name),
            custom_status=_status_name(task, fields),
            owner=_owner_name(task, fields),
            preparer=_display(read_task_field(task, fields["preparer"])),
            cash_account=_display(read_task_field(task, fields["cash_account"])),
            td_value=_to_float(read_task_field(task, fields["td_value"])),
            td_term=_display(read_task_field(task, fields["td_term"])),
            provider=_display(read_task_field(task, fields["provider"])),
            maturity_instruction=_display(read_task_field(task, fields["maturity_instruction"])),
            td_roa_reason=_display(read_task_field(task, fields["td_roa_reason"])),
            notes=_strip_html(
                _first_present(read_task_field(task, fields["notes"]), task.get("description"))
            ),
        ))
    return rows


def _resolve_head_client_name(matched: list[tuple[dict, dict]], fields: dict, head_client_id: str) -> str:
    for task, project in matched:
        name = _display(_first_present(
            read_task_field(task, fields["head_client"]), read_task_field(project, fields["head_client"])
        ))
        if name:
            return name
    return head_client_id


def _today_display() -> str:
    today = datetime.now(timezone.utc).date()
    return f"{today.day} {today.strftime('%B %Y')}"


# ---------- Selected Task Notes (Azure OpenAI) ----------

def _last_activity_ms(task: dict) -> int | None:
    for key in ("last_updated_time_long", "updated_date_long", "created_date_long", "created_time_long"):
        value = task.get(key)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _selected_notes_cutoff_ms() -> int:
    months = int(os.getenv("SELECTED_NOTES_MONTHS", "6"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * months)
    return int(cutoff.timestamp() * 1000)


async def _build_selected_notes(
    matched: list[tuple[dict, dict]], rows: list[TaskRow]
) -> list[tuple[str, str, str]]:

    cutoff_ms = _selected_notes_cutoff_ms()
    candidates = [
        row for (task, _project), row in zip(matched, rows)
        if row.notes and (_last_activity_ms(task) is None or _last_activity_ms(task) >= cutoff_ms)
    ]
    summaries = await asyncio.gather(
        *[azure_openai.summarize_note(r.task_name, r.project_name, r.notes) for r in candidates]
    )
    return [(r.task_name, r.project_name, summary or "") for r, summary in zip(candidates, summaries)]


# ---------- orchestration ----------

async def run_report(req: ReportRequest, job_id: str = "") -> JobResult:
  
    fields = field_map()
    result = JobResult(
        job_id=job_id,
        status="running",
        head_client_id=req.head_client_id,
        filename=req.resolved_filename(),
    )

    matched, projects_scanned = await resolve_matching_tasks(req, fields)
    result.projects_scanned = projects_scanned
    result.tasks_matched = len(matched)

    if not matched:
        result.error = f"No tasks found for head_client_id={req.head_client_id!r}."
        return result

    rows = _build_rows(matched, fields)
    result.head_client_name = _resolve_head_client_name(matched, fields, req.head_client_id)
    selected_notes = await _build_selected_notes(matched, rows)

    data = ReportData(
        title=REPORT_TITLE,
        tasks_total=len(rows),
        prepared_by="Advisory Partners",
        as_at=_today_display(),
        rows=rows,
        selected_notes=selected_notes,
    )

    try:
        pdf_bytes = render_task_summary_pdf(data)
    except Exception as exc:  # noqa: BLE001 — record render failure on the job
        result.error = f"PDF render failed: {exc}"
        return result
    result.bytes_pdf = len(pdf_bytes)

    # Store before delivering: a delivery failure should still leave the report
    # readable, and a dry run is precisely the case where viewing it is the point.
    if job_id:
        try:
            artifacts.save_pdf(job_id, pdf_bytes)
        except Exception as exc:  # noqa: BLE001 — a report we can't file is still a report
            result.error = f"PDF rendered but not stored for viewing: {exc}"

    if req.dry_run:
        return result

    webhook = req.resolved_webhook()
    if not webhook:
        result.error = "No webhook configured — PDF rendered but not delivered."
        return result

    try:
        await power_automate.deliver_pdf(webhook, filename=req.resolved_filename(), pdf_bytes=pdf_bytes)
        result.delivered = True
    except Exception as exc:  # noqa: BLE001 — surface delivery failure on the job
        result.error = str(exc)

    return result
