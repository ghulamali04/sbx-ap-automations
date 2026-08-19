"""
Live Task Summary data — fetches from Zoho via the still-intact
`task_summary_report` automation's fetch/mapping logic (`service.py`) rather
than re-implementing custom-field parsing here. That automation's own PDF
rendering and Power Automate delivery are untouched; this module only reuses
its data layer and hands the result to the shared `pdf_builder`-based
`build_task_summary_section`.

No other `client_review_pack` section has an equivalent live source in this
codebase yet — see `client_review_pack/live/__init__.py`.
"""
from __future__ import annotations

from api.automations.task_summary_report import service as ts_service
from api.automations.task_summary_report.models import ReportRequest as _TSReportRequest

from api.automations.client_review_pack.sections.task_summary import (
    SelectedComment,
    TaskRow,
    TaskSummaryData,
)


def _to_new_row(old) -> TaskRow:
    """Map `task_summary_report.pdf.TaskRow` onto the new Pydantic `TaskRow`.

    Field-for-field identical except `project_group`, which the new layout
    doesn't use (it bands rows by `project_name` directly).
    """
    return TaskRow(
        project_name=old.project_name,
        task_name=old.task_name,
        custom_status=old.custom_status,
        owner=old.owner,
        preparer=old.preparer,
        cash_account=old.cash_account,
        td_value=old.td_value,
        td_term=old.td_term,
        provider=old.provider,
        maturity_instruction=old.maturity_instruction,
        td_roa_reason=old.td_roa_reason,
        notes=old.notes,
        td_applicable=old.td_applicable,
    )


async def fetch_live_task_summary(head_client_id: str, *, active_only: bool = False) -> TaskSummaryData:
    """Fetch and shape one head client's live Zoho task register.

    Raises `RuntimeError` (naming `head_client_id` and `projects_scanned`) when
    nothing matched, so a caller can tell "integration works, wrong id" apart
    from "integration broken."
    """
    fields = ts_service.field_map()
    req = _TSReportRequest(head_client_id=head_client_id, active_only=active_only)

    matched, projects_scanned = await ts_service.resolve_matching_tasks(req, fields)
    if not matched:
        raise RuntimeError(
            f"No Zoho tasks matched head_client_id={head_client_id!r} "
            f"across {projects_scanned} project(s) scanned."
        )

    old_rows = ts_service._build_rows(matched, fields)
    head_client_name = ts_service._resolve_head_client_name(matched, fields, head_client_id)
    selected = await ts_service._build_selected_comments(matched, old_rows)

    return TaskSummaryData(
        head_client_id=head_client_name or head_client_id,
        tasks_total=len(old_rows),
        prepared_by="Advisory Partners",
        as_at=ts_service._today_display(),
        rows=[_to_new_row(r) for r in old_rows],
        selected_comments=[
            SelectedComment(task=task, project=project, summary=summary)
            for task, project, summary in selected
        ],
    )
