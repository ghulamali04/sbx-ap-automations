"""
Completion-overview orchestration: resolve projects → pull tasks → aggregate →
render → deliver to SharePoint via the webhook.

Generic per spec §6.7: the metric field and grouping fields come from the request,
not hardcoded. `read_task_field` is the single place that knows how to pull a named
field out of Zoho's task JSON — verify its behaviour against real data if the shape
of custom fields differs from the assumptions noted inline.
"""
from __future__ import annotations

import re

from api.automations.zoho import client
from api.automations.completion_overview.charts import Row, render_bar_chart
from api.automations.completion_overview.models import (
    ChartResult,
    Grouping,
    JobResult,
    ReportRequest,
)
from api.automations.completion_overview import sharepoint

# Built-in Zoho completion field. Spec §4.2: chart the built-in "Completion
# Percentage" (legacy JSON key `percent_complete`), NOT the custom "Percent
# Complete" field — so only the built-in name is aliased to the top-level key.
_TOP_LEVEL_ALIASES = {
    "completion percentage": "percent_complete",
}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
)}


# ---------- field access ----------

def read_task_field(task: dict, field_name: str):
    """Pull a named field from a Zoho task: aliases, then top-level, then custom_fields."""
    key = field_name.strip().lower()
    if key in _TOP_LEVEL_ALIASES:
        return task.get(_TOP_LEVEL_ALIASES[key])
    for k, v in task.items():
        if k.lower() == key:
            return v
    for cf in task.get("custom_fields", []) or []:
        if not isinstance(cf, dict):
            continue
        if cf.get("label_name", "").lower() == key or cf.get("column_name", "").lower() == key:
            return cf.get("value")
        for k, v in cf.items():  # legacy {label: value} form
            if k.lower() == key:
                return v
    return None


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


def _grouping_value(value) -> str | None:
    """Normalise a grouping cell to a non-empty display string, else None (excluded)."""
    if value is None:
        return None
    if isinstance(value, dict):  # e.g. an owner/user object
        value = value.get("name") or value.get("full_name") or value.get("value")
    s = str(value).strip() if value is not None else ""
    return s or None


# ---------- project selection & ordering ----------

def _is_active(project: dict, active_only: bool) -> bool:
    if not active_only:
        return True
    return str(project.get("status", "")).lower() == "active"


def _report_type(name: str) -> tuple[int, str]:
    upper = name.upper()
    if "BAS" in upper:
        return 0, "BAS"
    if "IAS" in upper:
        return 1, "IAS"
    return 2, "OTHER"


def _month_year(name: str, project: dict) -> tuple[int, int]:
    """Best-effort (year, month) for ordering + filenames, e.g. 'Jun 26' -> (2026, 6)."""
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\s+(\d{2})\b", name)
    if m and m.group(1).lower() in _MONTHS:
        return 2000 + int(m.group(2)), _MONTHS[m.group(1).lower()]
    created = project.get("created_date_long") or project.get("created_time_long")
    if created:
        import datetime as _dt
        dt = _dt.datetime.utcfromtimestamp(int(created) / 1000)
        return dt.year, dt.month
    return 9999, 12


def _order_key(project: dict) -> tuple:
    name = project.get("name", "")
    type_rank, _ = _report_type(name)
    year, month = _month_year(name, project)
    return (type_rank, year, month, name)


async def resolve_projects(req: ReportRequest) -> list[dict]:
    """Explicit ids win; otherwise pick the latest active project per name filter."""
    all_projects = await client.list_projects()
    by_id = {str(p.get("id")): p for p in all_projects}

    if req.project_ids:
        selected = [by_id[pid] for pid in (str(x) for x in req.project_ids) if pid in by_id]
    else:
        selected = []
        seen: set[str] = set()
        for term in req.name_filters:
            matches = [
                p for p in all_projects
                if term.lower() in (p.get("name", "").lower()) and _is_active(p, req.active_only)
            ]
            if not matches:
                continue
            latest = max(matches, key=lambda p: _month_year(p.get("name", ""), p))
            pid = str(latest.get("id"))
            if pid not in seen:
                seen.add(pid)
                selected.append(latest)

    selected = [p for p in selected if _is_active(p, req.active_only)]
    selected.sort(key=_order_key)
    return selected


# ---------- aggregation ----------

def aggregate(tasks: list[dict], metric_field: str, grouping_field: str) -> tuple[list[Row], int, int]:
    """Group tasks by grouping_field, averaging metric_field. Returns (rows, included, excluded)."""
    buckets: dict[str, list[float]] = {}
    included = excluded = 0
    for task in tasks:
        person = _grouping_value(read_task_field(task, grouping_field))
        metric = _to_float(read_task_field(task, metric_field))
        if person is None or metric is None:
            excluded += 1
            continue
        buckets.setdefault(person, []).append(metric)
        included += 1
    rows = [Row(label=p, value=sum(v) / len(v), count=len(v)) for p, v in buckets.items()]
    return rows, included, excluded


# ---------- orchestration ----------

def _filename(index: int, project: dict) -> str:
    name = project.get("name", "")
    _, type_code = _report_type(name)
    year, month = _month_year(name, project)
    return f"{index:02d}-{type_code}-{year:04d}-{month:02d}.png"


async def run_report(req: ReportRequest) -> JobResult:
    projects = await resolve_projects(req)
    result = JobResult(job_id="", status="running", projects_matched=len(projects))

    for index, project in enumerate(projects, start=1):
        pid = str(project.get("id"))
        pname = project.get("name", pid)
        tasks = await client.get_all_tasks(pid)
        base_name = _filename(index, project)

        for grouping in req.groupings:
            chart = await _one_chart(req, project, pid, pname, tasks, grouping, base_name)
            result.charts.append(chart)

    return result


async def _one_chart(
    req: ReportRequest,
    project: dict,
    pid: str,
    pname: str,
    tasks: list[dict],
    grouping: Grouping,
    base_name: str,
) -> ChartResult:
    rows, included, excluded = aggregate(tasks, req.metric_field, grouping.field)
    # One file per grouping — suffix the shared base name with the grouping field.
    filename = base_name.replace(".png", f"-{grouping.field.lower()}.png")
    chart = ChartResult(
        project_id=pid, project_name=pname, grouping=grouping.field,
        filename=filename, output_folder=grouping.output_folder,
        people=len(rows), tasks_included=included, tasks_excluded=excluded,
        delivered=False,
    )
    try:
        png = render_bar_chart(
            rows,
            title=pname,
            subtitle=f"By {grouping.field.lower()} — average {req.metric_field.lower()}",
        )
        await sharepoint.deliver_chart(
            req.sharepoint_webhook_url,
            folder=grouping.output_folder, filename=filename,
            png_bytes=png, project_name=pname, grouping=grouping.field,
        )
        chart.delivered = True
    except Exception as exc:  # noqa: BLE001 — record per-chart failure, keep going
        chart.error = str(exc)
    return chart
