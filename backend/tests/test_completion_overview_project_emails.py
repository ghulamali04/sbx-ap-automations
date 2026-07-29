from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from api.automations.completion_overview import power_automate
from api.automations.completion_overview.charts import (
    Panel,
    Row,
    render_combined_chart,
)
from api.automations.completion_overview.models import ChartResult, ReportRequest
from api.automations.completion_overview.service import resolve_projects, run_report
from api.main import app


class CompletionOverviewRecipientTests(IsolatedAsyncioTestCase):
    @staticmethod
    def _png_bytes(label: str) -> bytes:
        return render_combined_chart(
            [
                Panel(
                    heading=label,
                    rows=[Row(label="Example", value=75, count=3)],
                )
            ],
            title=label,
            subtitle="Layout test",
        )

    def test_power_automate_body_preserves_one_or_more_emails(self) -> None:
        payload = {
            "projects_include_IDs": [],
            "projects_exclude_IDs": [],
            "projects_include_Names": ["bs"],
            "projects_exclude_Names": ["compliance"],
            "projects_include_Emails": [
                "first@example.com",
                "second@example.com",
            ],
            "dry_run": False,
        }

        request = ReportRequest.model_validate(payload)
        queued_request = ReportRequest.model_validate(
            request.model_dump(mode="json")
        )

        self.assertEqual(
            queued_request.projects_include_Emails,
            ["first@example.com", "second@example.com"],
        )
        self.assertIn(
            "projects_include_Emails",
            ReportRequest.model_json_schema()["properties"],
        )

    def test_published_openapi_contract_exposes_project_emails(self) -> None:
        contract_path = (
            Path(__file__).resolve().parents[2] / "contracts" / "openapi.json"
        )
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        request_schema = contract["components"]["schemas"][
            "api__automations__completion_overview__models__ReportRequest"
        ]

        self.assertIn("projects_include_Emails", request_schema["properties"])
        self.assertEqual(
            request_schema["properties"]["projects_include_Emails"]["items"][
                "type"
            ],
            "string",
        )

    def test_api_receives_and_queues_the_complete_power_request(self) -> None:
        payload = {
            "projects_include_IDs": [],
            "projects_exclude_IDs": [],
            "projects_include_Names": ["bs"],
            "projects_exclude_Names": ["compliance"],
            "projects_include_Emails": [
                "first@example.com",
                "second@example.com",
            ],
            "dry_run": False,
        }

        with (
            patch(
                "api.automations.completion_overview.routes.create_job",
                return_value="completion-job",
            ),
            patch(
                "api.automations.completion_overview.routes.queue.dispatch_report",
            ) as dispatch,
        ):
            response = TestClient(app).post("/reports/completion", json=payload)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["job_id"], "completion-job")
        queued_request = dispatch.call_args.args[1]
        self.assertEqual(queued_request.projects_include_IDs, [])
        self.assertEqual(queued_request.projects_exclude_IDs, [])
        self.assertEqual(
            queued_request.projects_include_Emails,
            ["first@example.com", "second@example.com"],
        )
        self.assertEqual(queued_request.projects_include_Names, ["bs"])
        self.assertEqual(queued_request.projects_exclude_Names, ["compliance"])
        self.assertFalse(queued_request.dry_run)

    def test_completion_overview_uses_its_dedicated_webhook(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "COMPLETION_OVERVIEW_WEBHOOK_URL": "https://completion.example.test",
                "POWER_AUTOMATE_WEBHOOK_URL": "https://fallback.example.test",
            },
            clear=False,
        ):
            self.assertEqual(
                ReportRequest(projects_include_Names=["bs"]).resolved_webhook(),
                "https://completion.example.test",
            )

    async def test_recipient_emails_do_not_change_project_selection(self) -> None:
        projects = [
            {
                "id": "1",
                "name": "BS - Jul 26 BAS (AP)",
                "status": "active",
            },
            {
                "id": "2",
                "name": "BS - Jul 26 Compliance",
                "status": "active",
            },
            {
                "id": "3",
                "name": "BS - Aug 26 BAS (AP)",
                "status": "active",
            },
        ]
        request = ReportRequest.model_validate(
            {
                "projects_include_Names": ["bs"],
                "projects_exclude_Names": ["compliance"],
                "projects_include_Emails": [
                    "first@example.com",
                    "second@example.com",
                ],
                "dry_run": True,
            }
        )

        with patch(
            "api.automations.completion_overview.service.client.list_projects",
            new=AsyncMock(return_value=projects),
        ):
            selected = await resolve_projects(request)

        self.assertEqual(
            [project["id"] for project in selected],
            ["3", "1"],
        )

    async def test_original_pngs_and_all_emails_are_sent_to_power_automate(self) -> None:
        response = MagicMock(status_code=200)
        http_client = AsyncMock()
        http_client.post.return_value = response
        context_manager = AsyncMock()
        context_manager.__aenter__.return_value = http_client
        first_png = self._png_bytes("Chart one")
        second_png = self._png_bytes("Chart two")

        with patch(
            "api.automations.completion_overview.power_automate.httpx.AsyncClient",
            return_value=context_manager,
        ):
            await power_automate.deliver_charts(
                "https://flow.example.test/report",
                filename="completion-report",
                images=[first_png, second_png],
                request_emails=[
                    "first@example.com",
                    "second@example.com",
                ],
            )

        payload = http_client.post.await_args.kwargs["json"]
        self.assertEqual(
            payload["projects_include_Emails"],
            ["first@example.com", "second@example.com"],
        )
        self.assertEqual(
            base64.b64decode(payload["image_b64"][0]),
            first_png,
        )
        self.assertEqual(
            base64.b64decode(payload["image_b64"][1]),
            second_png,
        )
        self.assertTrue(
            all(
                base64.b64decode(item).startswith(b"\x89PNG\r\n\x1a\n")
                for item in payload["image_b64"]
            )
        )
        self.assertEqual(payload["filename"], "completion-report")
        self.assertEqual(payload["content_type"], "image/png")
        self.assertEqual(len(payload["image_b64"]), 2)
        self.assertEqual(
            set(payload),
            {
                "filename",
                "content_type",
                "image_b64",
                "projects_include_Emails",
            },
        )

    async def test_report_service_forwards_rendered_pngs_without_pdf_conversion(
        self,
    ) -> None:
        first_png = b"\x89PNG\r\n\x1a\nfirst"
        second_png = b"\x89PNG\r\n\x1a\nsecond"
        projects = [
            {"id": "1", "name": "BS - Jul 26 BAS (AP)"},
            {"id": "2", "name": "BS - Aug 26 BAS (AP)"},
        ]
        request = ReportRequest(
            projects_include_Names=["bs"],
            projects_include_Emails=[
                "first@example.com",
                "second@example.com",
            ],
            webhook_url="https://flow.example.test/report",
            filename="completion-batch",
        )
        charts = [
            ChartResult(project_id="1", project_name="First", filename="01.png"),
            ChartResult(project_id="2", project_name="Second", filename="02.png"),
        ]

        with (
            patch(
                "api.automations.completion_overview.service.resolve_projects",
                new=AsyncMock(return_value=projects),
            ),
            patch(
                "api.automations.completion_overview.service.client.get_all_tasks",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "api.automations.completion_overview.service._render_project_chart",
                side_effect=[
                    (charts[0], first_png),
                    (charts[1], second_png),
                ],
            ),
            patch(
                "api.automations.completion_overview.service.power_automate.deliver_charts",
                new=AsyncMock(),
            ) as deliver,
        ):
            result = await run_report(request)

        self.assertEqual(deliver.await_count, 1)
        self.assertEqual(
            deliver.await_args.kwargs,
            {
                "filename": "completion-batch",
                "images": [first_png, second_png],
                "request_emails": [
                    "first@example.com",
                    "second@example.com",
                ],
            },
        )
        self.assertEqual(
            deliver.await_args.args,
            ("https://flow.example.test/report",),
        )
        self.assertTrue(all(chart.delivered for chart in result.charts))

    async def test_delivery_request_with_no_matching_projects_fails_clearly(
        self,
    ) -> None:
        request = ReportRequest(
            projects_include_IDs=["missing-project"],
            projects_include_Emails=["first@example.com"],
            webhook_url="https://flow.example.test/report",
            dry_run=False,
        )

        with patch(
            "api.automations.completion_overview.service.resolve_projects",
            new=AsyncMock(return_value=[]),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "No Zoho projects matched",
            ):
                await run_report(request)

    async def test_power_automate_delivery_failure_is_not_silently_completed(
        self,
    ) -> None:
        png = b"\x89PNG\r\n\x1a\nchart"
        project = {"id": "1", "name": "BS - BAS"}
        chart = ChartResult(
            project_id="1",
            project_name="BS - BAS",
            filename="01-bs-bas.png",
            bytes_png=len(png),
        )
        request = ReportRequest(
            projects_include_IDs=["1"],
            projects_include_Emails=["first@example.com"],
            webhook_url="https://flow.example.test/report",
            dry_run=False,
        )

        with (
            patch(
                "api.automations.completion_overview.service.resolve_projects",
                new=AsyncMock(return_value=[project]),
            ),
            patch(
                "api.automations.completion_overview.service.client.get_all_tasks",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "api.automations.completion_overview.service._render_project_chart",
                return_value=(chart, png),
            ),
            patch(
                "api.automations.completion_overview.service.power_automate.deliver_charts",
                new=AsyncMock(side_effect=RuntimeError("HTTP 400")),
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Completion Overview delivery failed",
            ):
                await run_report(request)
