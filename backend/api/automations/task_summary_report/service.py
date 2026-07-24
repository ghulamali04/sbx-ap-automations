"""
Task Summary report orchestration: scan Zoho projects for one head client's
tasks -> aggregate -> render PDF -> deliver to the Power Automate flow.

Field lookup reuses read_task_field from completion_overview.service (a pure,
generic "find a label on this task dict, checking aliases / top-level keys /
custom_fields" helper) rather than duplicating it — see that module for the
matching rules.
"""
from __future__ import annotations

import re
from datetime import date

from api.automations.zoho import client
from api.automations.completion_overview.service import read_task_field
from api.automations.task_summary_report import artifacts, power_automate
from api.automations.task_summary_report.models import JobResult, ReportRequest, field_map
from api.automations.task_summary_report.pdf import ReportData, TaskRow, render_task_summary_pdf


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
    """Scan every (optionally active-only) project for tasks belonging to the head client.

    Brute-force by necessity: Zoho's legacy Projects API has no server-side
    filter for a custom field across all projects, so every project's tasks
    are pulled and filtered client-side — the same approach resolve_projects()
    takes in completion_overview/service.py.
    """
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


# ---------- row building & aggregation ----------

def _build_rows(matched: list[tuple[dict, dict]], fields: dict) -> list[TaskRow]:
    rows = []
    for task, project in matched:
        head_client_name = _display(_first_present(
            read_task_field(task, fields["head_client"]),
            read_task_field(project, fields["head_client"]),
        ))
        rows.append(TaskRow(
            project_name=_display(project.get("name")),
            task_name=_display(task.get("name")),
            project_group=_display(read_task_field(task, fields["project_group"])) or "Ungrouped Project",
            custom_status=_status_name(task, fields),
            owner=_owner_name(task, fields),
            head_client_name=head_client_name,
            preparer=_display(read_task_field(task, fields["preparer"])),
            cash_account=_display(read_task_field(task, fields["cash_account"])),
            td_value=_to_float(read_task_field(task, fields["td_value"])),
            td_term=_display(read_task_field(task, fields["td_term"])),
            provider=_display(read_task_field(task, fields["provider"])),
            maturity_instruction=_display(read_task_field(task, fields["maturity_instruction"])),
            td_roa_reason=_display(read_task_field(task, fields["td_roa_reason"])),
            latest_comment=_strip_html(
                _first_present(read_task_field(task, fields["latest_comment"]), task.get("description"))
            ),
        ))
    return rows


def _count_by(rows: list[TaskRow], key) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in rows:
        label = key(row) or "Not set"
        counts[label] = counts.get(label, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ordered.append(("Total", len(rows)))
    return ordered


def _mode(values: list[str]) -> str:
    values = [v for v in values if v]
    if not values:
        return ""
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _term_deposit_summary(rows: list[TaskRow]) -> dict:
    td_rows = [r for r in rows if r.td_value is not None]
    return {
        "active_count": len(td_rows),
        "total_value": sum(r.td_value for r in td_rows),
        "common_term": _mode([r.td_term for r in td_rows]),
        "maturity_instruction": _mode([r.maturity_instruction for r in td_rows]),
        "cash_account": _mode([r.cash_account for r in td_rows]),
        "provider": _mode([r.provider for r in td_rows]),
    }


def _resolve_identity(matched: list[tuple[dict, dict]], fields: dict, head_client_id: str) -> tuple[str, str]:
    """Return (head_client_display_name, report_title)."""
    name = group = ""
    for task, project in matched:
        if not name:
            name = _display(_first_present(
                read_task_field(task, fields["head_client"]), read_task_field(project, fields["head_client"])
            ))
        if not group:
            group = _display(_first_present(
                read_task_field(task, fields["client_group"]), read_task_field(project, fields["client_group"])
            ))
        if name and group:
            break
    name = name or head_client_id
    title = f"{group or (name + ' Group')} — Task Summary"
    return name, title


def _today_display() -> str:
    today = date.today()
    return f"{today.day} {today.strftime('%B %Y')}"


# ---------- orchestration ----------

async def run_report(req: ReportRequest, job_id: str = "") -> JobResult:
    """Resolve tasks, render the PDF, and deliver it. Result is recorded either way.

    `job_id` is what the rendered PDF is filed under so the status route can link
    to it; pass it whenever the caller wants the PDF viewable afterwards.
    """
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
    head_client_name, title = _resolve_identity(matched, fields, req.head_client_id)
    result.head_client_name = head_client_name

    data = ReportData(
        title=title,
        head_client_name=head_client_name,
        tasks_total=len(rows),
        prepared_by="Advisory Partners",
        as_at=_today_display(),
        by_project_group=_count_by(rows, lambda r: r.project_group),
        by_status=_count_by(rows, lambda r: r.custom_status),
        td_summary=_term_deposit_summary(rows),
        rows=rows,
        selected_notes=[(r.task_name, r.project_name, r.latest_comment) for r in rows if r.latest_comment],
        footer_note=(
            "Grayed cells indicate fields that do not apply to that task (BAS/IAS "
            "applies to activity-statement tasks; term-deposit fields apply to FP "
            f"- Term Deposit tasks). Head client is {head_client_name} for all tasks."
        ),
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
