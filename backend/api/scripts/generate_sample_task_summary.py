"""Generate a local sample of the Task Summary PDF without Zoho or Azure."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_BACKEND_ROOT))

from api.automations.task_summary_report.pdf import (  # noqa: E402
    ReportData,
    TaskRow,
    render_task_summary_pdf,
)


def _row(
    project: str,
    task: str,
    status: str,
    owner: str,
    value: float | None,
    term: str,
    provider: str,
    notes: str,
) -> TaskRow:
    return TaskRow(
        project_name=project,
        task_name=task,
        project_group="Financial Planning",
        custom_status=status,
        owner=owner,
        preparer="Advisory Partners",
        cash_account="Client cash account",
        td_value=value,
        td_term=term,
        provider=provider,
        maturity_instruction="Review at maturity",
        td_roa_reason="Client review",
        notes=notes,
    )


def main() -> None:
    rows = [
        _row(
            "FP - Annual Review",
            "Review investment portfolio",
            "In progress",
            "Alex Morgan",
            None,
            "",
            "",
            "Portfolio information received and adviser review is underway.",
        ),
        _row(
            "FP - Term Deposits",
            "Review term deposit maturity",
            "Ready for review",
            "Taylor Smith",
            75_000,
            "6 months",
            "Example Bank",
            "Deposit matures next month; renewal options have been requested.",
        ),
        _row(
            "FP - Term Deposits",
            "Confirm maturity instructions",
            "Waiting on client",
            "Taylor Smith",
            50_000,
            "12 months",
            "Sample Credit Union",
            "Client confirmation is required before maturity.",
        ),
        _row(
            "BS - Quarterly Compliance",
            "Prepare BAS information",
            "Not started",
            "Jordan Lee",
            None,
            "",
            "",
            "Quarterly source documents are being collected.",
        ),
    ]
    comment_summaries = [
        (
            rows[0].task_name,
            rows[0].project_name,
            "The portfolio information has been received and is under adviser review.",
        ),
        (
            rows[1].task_name,
            rows[1].project_name,
            "Renewal options are being obtained before the deposit matures next month.",
        ),
        (
            rows[2].task_name,
            rows[2].project_name,
            "Client confirmation is outstanding for the maturity instruction.",
        ),
    ]
    report = ReportData(
        title="Client Snapshot Report - Sample",
        head_client_id="53",
        tasks_total=len(rows),
        prepared_by="Advisory Partners",
        as_at="27 July 2026",
        rows=rows,
        selected_comments=comment_summaries,
    )

    output_dir = _REPOSITORY_ROOT / "output" / "pdf"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "sample-task-summary-report.pdf"
    output_file.write_bytes(render_task_summary_pdf(report))
    print(output_file)


if __name__ == "__main__":
    main()
