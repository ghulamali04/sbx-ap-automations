"""Generate a fresh live Completion Overview PNG batch and optionally deliver it."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_BACKEND_ROOT))

from api.settings import load_local_settings  # noqa: E402

load_local_settings()

from api.automations.completion_overview import power_automate  # noqa: E402
from api.automations.completion_overview.models import ReportRequest  # noqa: E402
from api.automations.completion_overview.service import (  # noqa: E402
    _filename,
    _render_project_chart,
    resolve_projects,
)
from api.automations.email_recipients import normalize_email_recipients  # noqa: E402
from api.automations.zoho import client  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch live Zoho data, apply Completion Overview project filters, "
            "write a new timestamped PNG batch, and optionally send that exact "
            "batch plus recipient emails to the cu/25 Power Automate flow."
        )
    )
    parser.add_argument("--include-id", action="append", default=[])
    parser.add_argument("--exclude-id", action="append", default=[])
    parser.add_argument("--include-name", action="append", default=[])
    parser.add_argument("--exclude-name", action="append", default=[])
    parser.add_argument(
        "--email",
        action="append",
        default=[],
        help="Recipient email. Repeat to include multiple recipients.",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive Zoho projects. Active projects are used by default.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Create and validate the PNG batch without sending it.",
    )
    parser.add_argument("--webhook-url", help="Optional cu/25 webhook override.")
    parser.add_argument(
        "--output-root",
        type=Path,
        help=(
            "Parent directory for new batches. Defaults to "
            "output/completion-overview-email-test."
        ),
    )
    parser.add_argument(
        "--batch-name",
        help="Optional unique batch directory/name; mainly useful for automated tests.",
    )
    return parser.parse_args()


def _new_batch_name() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return f"completion-overview-email-test-{timestamp}"


def _write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


async def generate_email_test(args: argparse.Namespace) -> Path:
    recipients = normalize_email_recipients(args.email)
    request = ReportRequest(
        projects_include_IDs=args.include_id,
        projects_exclude_IDs=args.exclude_id,
        projects_include_Names=args.include_name,
        projects_exclude_Names=args.exclude_name,
        projects_include_Emails=recipients,
        active_only=not args.include_inactive,
        webhook_url=args.webhook_url,
        dry_run=args.dry_run or not recipients,
    )
    selection_error = request.validate_selection()
    if selection_error:
        raise ValueError(selection_error)

    batch_name = args.batch_name or _new_batch_name()
    output_root = args.output_root or (
        _REPOSITORY_ROOT / "output" / "completion-overview-email-test"
    )
    if not output_root.is_absolute():
        output_root = _REPOSITORY_ROOT / output_root
    batch_dir = output_root / batch_name
    batch_dir.mkdir(parents=True, exist_ok=False)

    projects = await resolve_projects(request)
    rendered_images: list[bytes] = []
    project_results: list[dict] = []
    for index, project in enumerate(projects, start=1):
        tasks = await client.get_all_tasks(str(project.get("id")))
        chart, png = _render_project_chart(
            request,
            project,
            tasks,
            _filename(index, project),
        )
        if png is not None:
            (batch_dir / chart.filename).write_bytes(png)
            rendered_images.append(png)
        project_results.append(
            {
                "project_id": chart.project_id,
                "project_name": chart.project_name,
                "filename": chart.filename,
                "tasks_total": chart.tasks_total,
                "bytes_png": chart.bytes_png,
                "error": chart.error,
            }
        )

    manifest = {
        "batch_name": batch_name,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "request": {
            "projects_include_IDs": request.projects_include_IDs,
            "projects_exclude_IDs": request.projects_exclude_IDs,
            "projects_include_Names": request.projects_include_Names,
            "projects_exclude_Names": request.projects_exclude_Names,
            "projects_include_Emails": request.projects_include_Emails,
            "active_only": request.active_only,
            "dry_run": request.dry_run,
        },
        "projects_matched": len(projects),
        "images_created": len(rendered_images),
        "projects": project_results,
        "delivery": {
            "workflow": "completion-overview-cu25",
            "attempted": False,
            "sent": False,
            "error": None,
        },
    }
    manifest_path = batch_dir / "manifest.json"
    _write_manifest(manifest_path, manifest)

    if not rendered_images:
        raise RuntimeError(
            f"No Completion Overview PNGs were created. Review {manifest_path}."
        )

    if recipients and not args.dry_run:
        webhook = request.resolved_webhook()
        if not webhook:
            raise RuntimeError(
                "No Completion Overview cu/25 webhook is configured."
            )
        power_automate.validate_webhook_url(webhook)
        manifest["delivery"]["attempted"] = True
        try:
            await power_automate.deliver_charts(
                webhook,
                filename=batch_name,
                images=rendered_images,
                request_emails=recipients,
            )
            manifest["delivery"]["sent"] = True
        except Exception as exc:
            manifest["delivery"]["error"] = str(exc)
            raise
        finally:
            _write_manifest(manifest_path, manifest)

    print(
        f"Created {batch_dir}: {len(projects)} projects, "
        f"{len(rendered_images)} PNG images."
    )
    if manifest["delivery"]["sent"]:
        print(
            "Sent PNG batch through cu/25 for "
            f"{', '.join(request.projects_include_Emails)}."
        )
    elif request.dry_run:
        print("Dry run: Power Automate delivery skipped.")
    return batch_dir


if __name__ == "__main__":
    asyncio.run(generate_email_test(_parse_args()))
