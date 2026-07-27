
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


def _is_term_deposit_project(project_name: str) -> bool:
    configured = os.getenv("TERM_DEPOSIT_PROJECT_NAMES", "FP - Term Deposits")
    names = {
        name.strip().casefold()
        for name in configured.split(",")
        if name.strip()
    }
    return project_name.strip().casefold() in names


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
    has_term_deposit_task = any(
        _is_term_deposit_project(_display(project.get("name")))
        for _task, project in matched
    )
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
            td_applicable=has_term_deposit_task,
        ))
    return sorted(
        rows,
        key=lambda row: (
            row.project_group.casefold(),
            row.project_name.casefold(),
            row.task_name.casefold(),
        ),
    )


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
    configured_days = os.getenv("SELECTED_NOTES_DAYS")
    if configured_days is not None:
        days = int(configured_days)
    else:
        # Keep the old setting as a compatibility fallback, but align the
        # default with the approved 60-day inclusion rule.
        configured_months = os.getenv("SELECTED_NOTES_MONTHS")
        days = 30 * int(configured_months) if configured_months else 60
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return int(cutoff.timestamp() * 1000)


def _comment_time_ms(comment: dict) -> int | None:
    for key in ("created_time_long", "last_updated_time_long", "modified_time_long"):
        value = comment.get(key)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _comment_context(comments: list[dict]) -> str:
    history = []
    for comment in comments:
        content = _strip_html(comment.get("content"))
        if not content:
            continue
        date = _display(
            _first_present(
                comment.get("created_time_format"),
                comment.get("created_time"),
            )
        )
        author = _display(comment.get("added_person"))
        prefix = " - ".join(part for part in (date, author) if part)
        history.append(f"{prefix}: {content}" if prefix else content)
    return "\n".join(history)


async def _build_selected_notes(
    matched: list[tuple[dict, dict]], rows: list[TaskRow]
) -> list[tuple[str, str, str]]:
    cutoff_ms = _selected_notes_cutoff_ms()
    concurrency = max(1, int(os.getenv("SELECTED_NOTES_CONCURRENCY", "8")))
    semaphore = asyncio.Semaphore(concurrency)

    async def summarize_one(
        task: dict,
        project: dict,
        row: TaskRow,
    ) -> tuple[str, str, str] | None:
        comments: list[dict] = []
        task_id = _display(_first_present(task.get("id"), task.get("id_string")))
        project_id = _display(project.get("id"))
        if task_id and project_id:
            try:
                async with semaphore:
                    comments = await client.get_task_comments(project_id, task_id)
            except Exception:  # noqa: BLE001 - Notes still provide a safe fallback
                comments = []

        has_recent_comment = any(
            timestamp is not None and timestamp >= cutoff_ms
            for timestamp in (_comment_time_ms(comment) for comment in comments)
        )
        task_activity = _last_activity_ms(task)
        has_recent_notes_field = bool(
            row.notes
            and (task_activity is None or task_activity >= cutoff_ms)
        )
        if not has_recent_comment and not has_recent_notes_field:
            return None

        context_parts = []
        if row.notes:
            context_parts.append(f"Task Notes:\n{row.notes}")
        comment_history = _comment_context(comments)
        if comment_history:
            context_parts.append(f"Comment History:\n{comment_history}")
        context = "\n\n".join(context_parts)
        summary = await azure_openai.summarize_note(
            row.task_name,
            row.project_name,
            context,
        )
        return row.task_name, row.project_name, summary or ""

    selected = await asyncio.gather(
        *[
            summarize_one(task, project, row)
            for (task, project), row in zip(matched, rows)
        ]
    )
    return [note for note in selected if note is not None]


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
        await power_automate.deliver_pdf(
            webhook,
            requestor_email=req.requestor_email or "",
            filename=req.resolved_filename(),
            pdf_bytes=pdf_bytes,
        )
        result.delivered = True
    except Exception as exc:  # noqa: BLE001 — surface delivery failure on the job
        result.error = str(exc)

    return result
