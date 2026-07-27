"""Generate a PDF from the first real active Zoho project containing tasks."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_BACKEND_ROOT))

from api.settings import load_local_settings  # noqa: E402

load_local_settings()

from api.automations.task_summary_report.models import field_map  # noqa: E402
from api.automations.task_summary_report.pdf import (  # noqa: E402
    ReportData,
    render_task_summary_pdf,
)
from api.automations.task_summary_report.service import (  # noqa: E402
    REPORT_TITLE,
    _build_rows,
    _today_display,
)
from api.automations.zoho.client import get_all_tasks, list_projects  # noqa: E402


async def main() -> None:
    projects = await list_projects()
    active_projects = [
        project
        for project in projects
        if str(project.get("status", "")).lower() == "active"
    ]

    selected_project = None
    selected_tasks: list[dict] = []
    for project in active_projects:
        tasks = await get_all_tasks(str(project["id"]))
        if tasks:
            selected_project = project
            selected_tasks = tasks
            break

    if selected_project is None:
        raise RuntimeError("No active Zoho project containing tasks was found.")

    matched = [(task, selected_project) for task in selected_tasks]
    rows = _build_rows(matched, field_map())
    report = ReportData(
        title=REPORT_TITLE,
        tasks_total=len(rows),
        prepared_by="Advisory Partners",
        as_at=_today_display(),
        rows=rows,
        selected_notes=[],
    )

    output_dir = _REPOSITORY_ROOT / "output" / "pdf"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "actual-task-summary-report.pdf"
    output_file.write_bytes(render_task_summary_pdf(report))
    print(
        f"Generated {output_file} from project "
        f"{selected_project.get('name')!r} with {len(rows)} real tasks."
    )


if __name__ == "__main__":
    asyncio.run(main())
