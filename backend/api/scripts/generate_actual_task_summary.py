"""Generate and optionally email one live Client Snapshot report."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_BACKEND_ROOT))

from api.settings import load_local_settings  # noqa: E402

load_local_settings()

from api.automations.task_summary_report import power_automate  # noqa: E402
from api.automations.task_summary_report.models import ReportRequest, field_map  # noqa: E402
from api.automations.task_summary_report.pdf import (  # noqa: E402
    ReportData,
    render_task_summary_pdf,
)
from api.automations.task_summary_report.service import (  # noqa: E402
    REPORT_TITLE,
    _build_rows,
    _build_selected_comments,
    _today_display,
    resolve_matching_tasks,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch one Head Client from live Zoho data, generate Azure summaries "
            "from its last 180 days of task comments, and build the standard PDF."
        )
    )
    parser.add_argument("head_client_id", help="Head Client ID to report on.")
    parser.add_argument(
        "--requestor-email",
        help="If supplied, send the generated PDF through the configured flow.",
    )
    parser.add_argument(
        "--webhook-url",
        help="Optional Power Automate webhook override.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "PDF output path. Defaults to "
            "output/pdf/actual-task-summary-report.pdf."
        ),
    )
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Search only Zoho projects marked active.",
    )
    return parser.parse_args()


async def generate_live_report(args: argparse.Namespace) -> Path:
    request = ReportRequest(
        head_client_id=args.head_client_id,
        active_only=args.active_only,
        requestor_email=args.requestor_email,
        webhook_url=args.webhook_url,
        dry_run=not bool(args.requestor_email),
    )
    fields = field_map()
    matched, projects_scanned = await resolve_matching_tasks(request, fields)
    if not matched:
        raise RuntimeError(
            f"No Zoho tasks found for Head Client ID {args.head_client_id!r} "
            f"after scanning {projects_scanned} projects."
        )

    rows = _build_rows(matched, fields)
    selected_comments = await _build_selected_comments(matched, rows)
    report = ReportData(
        title=REPORT_TITLE,
        head_client_id=args.head_client_id,
        tasks_total=len(rows),
        prepared_by="Advisory Partners",
        as_at=_today_display(),
        rows=rows,
        selected_comments=selected_comments,
    )
    pdf_bytes = render_task_summary_pdf(report)

    output_file = args.output or (
        _REPOSITORY_ROOT / "output" / "pdf" / "actual-task-summary-report.pdf"
    )
    if not output_file.is_absolute():
        output_file = _REPOSITORY_ROOT / output_file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(pdf_bytes)

    if args.requestor_email:
        webhook = request.resolved_webhook()
        if not webhook:
            raise RuntimeError(
                "No task-summary Power Automate webhook is configured."
            )
        power_automate.validate_webhook_url(webhook)
        await power_automate.deliver_pdf(
            webhook,
            requestor_email=args.requestor_email,
            filename=output_file.name,
            pdf_bytes=pdf_bytes,
        )

    summaries_generated = sum(bool(summary) for _task, _project, summary in selected_comments)
    print(
        f"Generated {output_file} for Head Client ID {args.head_client_id!r}: "
        f"{len(rows)} tasks, {summaries_generated} Azure comment summaries."
    )
    if args.requestor_email:
        print(f"Sent PDF to {args.requestor_email} through Power Automate.")
    return output_file


if __name__ == "__main__":
    asyncio.run(generate_live_report(_parse_args()))
