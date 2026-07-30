from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from api.automations.completion_overview import power_automate, queue
from api.automations.completion_overview.charts import (
    Panel,
    Row,
    render_combined_chart,
)
from api.automations.completion_overview.models import (
    ChartResult,
    JobResult,
    ReportRequest,
)
from api.automations.completion_overview.service import (
    _render_project_chart,
    resolve_projects,
    run_report,
)
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
            "email_subject": "Current completion statistics",
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
        self.assertEqual(
            queued_request.email_subject,
            "Current completion statistics",
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
        self.assertIn("email_subject", request_schema["properties"])
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
            "email_subject": "Current completion statistics",
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
        self.assertEqual(
            queued_request.email_subject,
            "Current completion statistics",
        )
        self.assertFalse(queued_request.dry_run)

    def test_power_payload_preserves_visible_project_key_subject_and_emails(
        self,
    ) -> None:
        payload = {
            "projects_include_IDs": ["AI-7"],
            "projects_exclude_IDs": [],
            "projects_include_Names": ["bs"],
            "projects_exclude_Names": ["compliance"],
            "email_subject": "HTML EMAIL",
            "projects_include_Emails": [
                "matiurrehman1237@gmail.com",
                "hmjathol@gmail.com",
            ],
            "dry_run": False,
        }

        with (
            patch(
                "api.automations.completion_overview.routes.create_job",
                return_value="power-contract-job",
            ),
            patch(
                "api.automations.completion_overview.routes.queue.dispatch_report",
            ) as dispatch,
        ):
            response = TestClient(app).post("/reports/completion", json=payload)

        self.assertEqual(response.status_code, 202)
        request = dispatch.call_args.args[1]
        self.assertEqual(request.projects_include_IDs, ["AI-7"])
        self.assertEqual(request.email_subject, "HTML EMAIL")
        self.assertEqual(
            request.projects_include_Emails,
            [
                "matiurrehman1237@gmail.com",
                "hmjathol@gmail.com",
            ],
        )

    async def test_durable_queue_preserves_power_subject_and_emails(self) -> None:
        queued_body = json.dumps(
            {
                "job_id": "power-queue-job",
                "request": {
                    "projects_include_IDs": ["AI-7"],
                    "projects_exclude_IDs": [],
                    "projects_include_Names": ["bs"],
                    "projects_exclude_Names": ["compliance"],
                    "email_subject": "HTML EMAIL",
                    "projects_include_Emails": [
                        "matiurrehman1237@gmail.com",
                        "hmjathol@gmail.com",
                    ],
                    "dry_run": False,
                },
            }
        )
        result = JobResult(job_id="", status="running")

        with (
            patch.object(queue.jobs, "set_status"),
            patch.object(
                queue.service,
                "run_report",
                new=AsyncMock(return_value=result),
            ) as run_report,
            patch.object(queue.jobs, "save_job"),
        ):
            await queue.process_message(queued_body)

        worker_request = run_report.await_args.args[0]
        self.assertEqual(worker_request.email_subject, "HTML EMAIL")
        self.assertEqual(worker_request.projects_include_IDs, ["AI-7"])
        self.assertEqual(
            worker_request.projects_include_Emails,
            [
                "matiurrehman1237@gmail.com",
                "hmjathol@gmail.com",
            ],
        )

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
                email_subject="Current completion statistics",
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
        self.assertEqual(
            payload["email_subject"],
            "Current completion statistics",
        )
        self.assertNotIn("attachments", payload)
        self.assertEqual(len(payload["image_b64"]), 2)
        self.assertEqual(
            set(payload),
            {
                "filename",
                "content_type",
                "image_b64",
                "projects_include_Emails",
                "email_subject",
            },
        )

    async def test_transient_power_disconnect_is_retried(self) -> None:
        response = MagicMock(status_code=200)
        http_client = AsyncMock()
        http_client.post.side_effect = [
            power_automate.httpx.RemoteProtocolError(
                "Server disconnected without sending a response."
            ),
            response,
        ]
        context_manager = AsyncMock()
        context_manager.__aenter__.return_value = http_client

        with (
            patch(
                "api.automations.completion_overview.power_automate.httpx.AsyncClient",
                return_value=context_manager,
            ),
            patch(
                "api.automations.completion_overview.power_automate.asyncio.sleep",
                new=AsyncMock(),
            ) as sleep,
        ):
            await power_automate.deliver_charts(
                "https://flow.example.test/report",
                filename="completion-report",
                images=[self._png_bytes("Retry chart")],
                request_emails=["first@example.com"],
                email_subject="Retry test",
            )

        self.assertEqual(http_client.post.await_count, 2)
        sleep.assert_awaited_once_with(1)

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
            email_subject="Current completion statistics",
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
                "email_subject": "Current completion statistics",
            },
        )
        self.assertEqual(
            deliver.await_args.args,
            ("https://flow.example.test/report",),
        )
        self.assertTrue(all(chart.delivered for chart in result.charts))

    def test_chart_statistics_match_the_current_task_values(self) -> None:
        request = ReportRequest(
            projects_include_IDs=["1"],
            group_by=["Partner"],
            metric_field="Completion Percentage",
            dry_run=True,
        )
        tasks = [
            {
                "percent_complete": 50,
                "custom_fields": [
                    {"label_name": "Partner", "value": "Alice"},
                ]
            },
            {
                "percent_complete": 100,
                "custom_fields": [
                    {"label_name": "Partner", "value": "Alice"},
                ]
            },
            {
                "percent_complete": 20,
                "custom_fields": [
                    {"label_name": "Partner", "value": "Bob"},
                ]
            },
        ]

        chart, png = _render_project_chart(
            request,
            {"id": "1", "name": "Current project"},
            tasks,
            "01-current-project.png",
        )

        self.assertIsNotNone(png)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(
            [item.model_dump() for item in chart.panels[0].statistics],
            [
                {"label": "Alice", "value": 75.0, "count": 2},
                {"label": "Bob", "value": 20.0, "count": 1},
            ],
        )

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
