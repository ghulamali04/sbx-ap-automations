from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from api.automations.completion_overview.models import ChartResult
from api.scripts import generate_completion_overview_email_test as script


class CompletionOverviewEmailTestScriptTests(IsolatedAsyncioTestCase):
    @staticmethod
    def _args(output_root: Path, **overrides) -> Namespace:
        values = {
            "include_id": [],
            "exclude_id": [],
            "include_name": ["bs"],
            "exclude_name": ["compliance"],
            "email": [
                "first@example.com",
                "FIRST@example.com",
                "second@example.com",
            ],
            "include_inactive": False,
            "dry_run": False,
            "webhook_url": "https://flow.example.test/report",
            "output_root": output_root,
            "batch_name": "completion-overview-email-test-fixed",
        }
        values.update(overrides)
        return Namespace(**values)

    async def test_creates_fresh_png_batch_manifest_and_delivers_emails(
        self,
    ) -> None:
        temp_parent = Path(__file__).resolve().parents[2] / "tmp"
        temp_parent.mkdir(parents=True, exist_ok=True)
        projects = [
            {"id": "1", "name": "BS - Jul 26 BAS (AP)"},
            {"id": "2", "name": "BS - Aug 26 BAS (AP)"},
        ]
        first_png = b"\x89PNG\r\n\x1a\nfirst"
        second_png = b"\x89PNG\r\n\x1a\nsecond"
        charts = [
            ChartResult(
                project_id="1",
                project_name=projects[0]["name"],
                filename="01-first.png",
                tasks_total=3,
                bytes_png=len(first_png),
            ),
            ChartResult(
                project_id="2",
                project_name=projects[1]["name"],
                filename="02-second.png",
                tasks_total=4,
                bytes_png=len(second_png),
            ),
        ]

        with TemporaryDirectory(dir=temp_parent) as temp_dir:
            args = self._args(Path(temp_dir))
            with (
                patch.object(
                    script,
                    "resolve_projects",
                    new=AsyncMock(return_value=projects),
                ) as resolve,
                patch.object(
                    script.client,
                    "get_all_tasks",
                    new=AsyncMock(return_value=[]),
                ),
                patch.object(
                    script,
                    "_render_project_chart",
                    side_effect=[
                        (charts[0], first_png),
                        (charts[1], second_png),
                    ],
                ),
                patch.object(script.power_automate, "validate_webhook_url"),
                patch.object(
                    script.power_automate,
                    "deliver_charts",
                    new=AsyncMock(),
                ) as deliver,
            ):
                batch_dir = await script.generate_email_test(args)

            request = resolve.await_args.args[0]
            self.assertEqual(request.projects_include_Names, ["bs"])
            self.assertEqual(request.projects_exclude_Names, ["compliance"])
            self.assertEqual(
                request.projects_include_Emails,
                ["first@example.com", "second@example.com"],
            )
            self.assertEqual(
                (batch_dir / "01-first.png").read_bytes(),
                first_png,
            )
            self.assertEqual(
                (batch_dir / "02-second.png").read_bytes(),
                second_png,
            )
            manifest = json.loads(
                (batch_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["projects_matched"], 2)
            self.assertEqual(manifest["images_created"], 2)
            self.assertEqual(
                manifest["request"]["projects_include_Emails"],
                ["first@example.com", "second@example.com"],
            )
            self.assertTrue(manifest["delivery"]["attempted"])
            self.assertTrue(manifest["delivery"]["sent"])
            self.assertEqual(
                deliver.await_args.kwargs["images"],
                [first_png, second_png],
            )
            self.assertEqual(
                deliver.await_args.kwargs["request_emails"],
                ["first@example.com", "second@example.com"],
            )

    async def test_no_email_creates_dry_run_batch_without_delivery(self) -> None:
        temp_parent = Path(__file__).resolve().parents[2] / "tmp"
        temp_parent.mkdir(parents=True, exist_ok=True)
        png = b"\x89PNG\r\n\x1a\ndry"
        chart = ChartResult(
            project_id="1",
            project_name="BS - BAS",
            filename="01-dry.png",
            bytes_png=len(png),
        )

        with TemporaryDirectory(dir=temp_parent) as temp_dir:
            args = self._args(Path(temp_dir), email=[], dry_run=False)
            with (
                patch.object(
                    script,
                    "resolve_projects",
                    new=AsyncMock(
                        return_value=[{"id": "1", "name": "BS - BAS"}]
                    ),
                ),
                patch.object(
                    script.client,
                    "get_all_tasks",
                    new=AsyncMock(return_value=[]),
                ),
                patch.object(
                    script,
                    "_render_project_chart",
                    return_value=(chart, png),
                ),
                patch.object(
                    script.power_automate,
                    "deliver_charts",
                    new=AsyncMock(),
                ) as deliver,
            ):
                batch_dir = await script.generate_email_test(args)

            manifest = json.loads(
                (batch_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["request"]["dry_run"])
            self.assertFalse(manifest["delivery"]["attempted"])
            self.assertFalse(manifest["delivery"]["sent"])
            deliver.assert_not_awaited()

    async def test_existing_batch_name_is_never_overwritten(self) -> None:
        temp_parent = Path(__file__).resolve().parents[2] / "tmp"
        temp_parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=temp_parent) as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "completion-overview-email-test-fixed").mkdir()
            args = self._args(output_root)

            with self.assertRaises(FileExistsError):
                await script.generate_email_test(args)

