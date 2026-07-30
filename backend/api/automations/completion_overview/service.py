"""
Completion-overview orchestration: resolve projects → pull tasks → aggregate →
render → deliver to the Power Automate flow.

Generic per spec §6.7: the metric field and grouping fields come from the request,
not hardcoded. `read_task_field` is the single place that knows how to pull a named
field out of Zoho's task JSON — verify its behaviour against real data if the shape
of custom fields differs from the assumptions noted inline.
"""
from __future__ import annotations

import re

from api.automations.zoho import client
from api.automations.completion_overview.charts import Panel, Row, render_combined_chart
from api.automations.completion_overview.models import (
    ChartResult,
    JobResult,
    MetricSummary,
    PanelSummary,
    ReportRequest,
)
from api.automations.completion_overview import power_automate

# Built-in Zoho completion field. Spec §4.2: chart the built-in "Completion
# Percentage" (legacy JSON key `percent_complete`), NOT the custom "Percent
# Complete" field — so only the built-in name is aliased to the top-level key.
_TOP_LEVEL_ALIASES = {
    "completion percentage": "percent_complete",
}


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


def _report_type(name: str | None) -> tuple[int, str]:
    upper = str(name or "").upper()
    if "BAS" in upper:
        return 0, "BAS"
    if "IAS" in upper:
        return 1, "IAS"
    return 2, "OTHER"


def _order_key(project: dict) -> tuple:
    """BAS first, then IAS, then everything else — alphabetical within each group."""
    name = str(project.get("name") or "")
    type_rank, _ = _report_type(name)
    return (type_rank, name.lower())


def _name_matches(project: dict, keywords: list[str]) -> bool:
    """True when the project name contains any keyword (case-insensitive substring)."""
    name = str(project.get("name") or "").casefold()
    return any(
        keyword in name
        for keyword in (value.strip().casefold() for value in keywords)
        if keyword
    )


def _project_identifiers(project: dict) -> set[str]:
    """Return every Zoho identifier accepted by the Power Automate filters.

    Zoho's visible project number is `key` (for example ``AI-7``), while API
    calls use the longer `id`/`id_string`. Callers may provide either form.
    """
    return {
        str(value).strip().casefold()
        for value in (
            project.get("id"),
            project.get("id_string"),
            project.get("key"),
        )
        if value is not None and str(value).strip()
    }


async def resolve_projects(req: ReportRequest) -> list[dict]:
    """Choose one include strategy, then apply every exclusion.

    Include ids win over include names. Exclusions always win over inclusions:
    excluded ids and excluded name keywords are both applied to the selected set.
    When neither include list is given, exclusions narrow the full project list.
    """
    all_projects = await client.list_projects()
    by_identifier = {
        identifier: project
        for project in all_projects
        for identifier in _project_identifiers(project)
    }

    if req.projects_include_IDs:
        selected = []
        selected_internal_ids: set[str] = set()
        for requested_id in req.projects_include_IDs:
            project = by_identifier.get(str(requested_id).strip().casefold())
            if project is None:
                continue
            internal_id = str(project.get("id"))
            if internal_id not in selected_internal_ids:
                selected_internal_ids.add(internal_id)
                selected.append(project)
    elif req.projects_include_Names:
        selected = [p for p in all_projects if _name_matches(p, req.projects_include_Names)]
    else:
        selected = list(all_projects)

    if req.projects_exclude_IDs:
        excluded_ids = {
            str(value).strip().casefold()
            for value in req.projects_exclude_IDs
        }
        selected = [
            project
            for project in selected
            if _project_identifiers(project).isdisjoint(excluded_ids)
        ]
    if req.projects_exclude_Names:
        selected = [p for p in selected if not _name_matches(p, req.projects_exclude_Names)]

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
    """`01-bas-july-26.png` — the index keeps names unique and in report order."""
    name = project.get("name", "")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or str(project.get("id"))
    return f"{index:02d}-{slug}.png"


async def run_report(req: ReportRequest) -> JobResult:
    """Render every project's chart, then deliver them all once rendering is done.

    Delivery is deliberately a completion step rather than interleaved: a project
    that fails to render should not leave a half-delivered set of charts behind.
    """
    projects = await resolve_projects(req)
    if not projects and not req.dry_run:
        raise RuntimeError(
            "No Zoho projects matched the Completion Overview filters. "
            "Verify that include IDs are real Zoho project IDs, that selected "
            "projects are active, and that Power Automate sends arrays rather "
            "than quoted display text."
        )
    result = JobResult(
        job_id="", status="running",
        projects_matched=len(projects),
        projects_selected=[f"{p.get('id')}: {p.get('name')}" for p in projects],
    )

    # 1. Render.
    rendered: list[tuple[ChartResult, bytes | None]] = []
    for index, project in enumerate(projects, start=1):
        tasks = await client.get_all_tasks(str(project.get("id")))
        chart, png = _render_project_chart(req, project, tasks, _filename(index, project))
        rendered.append((chart, png))
        result.charts.append(chart)

    # 2. Deliver every chart in ONE call, so the flow triggers once and can send a
    #    single email covering all projects — one call per project sends one each.
    ready = [(chart, png) for chart, png in rendered if png is not None]
    if req.dry_run:
        return result
    if not ready:
        raise RuntimeError(
            "Projects matched, but no Completion Overview PNG images were rendered."
        )

    webhook = req.resolved_webhook()
    if not webhook:
        raise RuntimeError(
            "No Completion Overview webhook is configured for delivery."
        )

    try:
        await power_automate.deliver_charts(
            webhook,
            filename=req.resolved_filename(),
            images=[png for _, png in ready],
            request_emails=req.projects_include_Emails,
            email_subject=req.resolved_email_subject(),
        )
        for chart, _ in ready:
            chart.delivered = True
    except Exception as exc:  # noqa: BLE001 — single call, so the batch fails together
        for chart, _ in ready:
            chart.error = str(exc)
        raise RuntimeError(
            f"Completion Overview delivery failed: {exc}"
        ) from exc

    return result


def _render_project_chart(
    req: ReportRequest, project: dict, tasks: list[dict], filename: str
) -> tuple[ChartResult, bytes | None]:
    """One combined PNG per project: a stacked panel for each grouping."""
    pid = str(project.get("id"))
    pname = project.get("name", pid)
    chart = ChartResult(
        project_id=pid, project_name=pname, filename=filename, tasks_total=len(tasks)
    )

    panels: list[Panel] = []
    for field in req.group_by:
        rows, included, excluded = aggregate(tasks, req.metric_field, field)
        panels.append(Panel(heading=f"By {field.lower()} — average {req.metric_field.lower()}", rows=rows))
        chart.panels.append(PanelSummary(
            grouping=field, people=len(rows),
            tasks_included=included, tasks_excluded=excluded,
            statistics=[
                MetricSummary(
                    label=row.label,
                    value=row.value,
                    count=row.count,
                )
                for row in rows
            ],
        ))

    try:
        png = render_combined_chart(
            panels,
            title=pname,
            subtitle=f"Average {req.metric_field.lower()} per person · {_today()}",
        )
        chart.bytes_png = len(png)
        return chart, png
    except Exception as exc:  # noqa: BLE001 — record render failure, keep going
        chart.error = str(exc)
        return chart, None


def _today() -> str:
    import datetime as _dt
    return _dt.date.today().strftime("%d %b %Y")
