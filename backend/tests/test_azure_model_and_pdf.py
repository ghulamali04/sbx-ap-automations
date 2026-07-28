from __future__ import annotations

import base64
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from azure.core.exceptions import ClientAuthenticationError
from fastapi.testclient import TestClient

from api.automations.task_summary_report import azure_openai, power_automate
from api.automations.task_summary_report.models import field_map
from api.automations.task_summary_report.pdf import (
    _SELECTED_COMMENTS_TITLE,
    _TASK_COLUMNS,
    _header_block,
    _task_register_table,
    ReportData,
    TaskRow,
    render_task_summary_pdf,
)
from api.automations.task_summary_report.service import (
    _build_rows,
    _build_selected_comments,
    _infer_project_group,
    _matches_head_client,
)
from api.scripts import generate_actual_task_summary
from api.main import app


def _term_deposit_task(
    client_id: str,
    *,
    cash_value,
    maturity_label: str,
    maturity_value,
) -> dict:
    fields = field_map()
    return {
        "id": f"task-{client_id}",
        "name": f"Term deposit review for client {client_id}",
        "status": {"name": "In progress"},
        "details": {"owners": [{"name": "Owner Name"}]},
        "custom_fields": [
            {"label_name": fields["head_client_id"], "value": client_id},
            {"label_name": fields["preparer"], "value": "Accountant"},
            {"label_name": fields["cash_account"], "value": cash_value},
            {"label_name": fields["td_value"], "value": "$12,500"},
            {"label_name": fields["td_term"], "value": "6 months"},
            {"label_name": fields["provider"], "value": "Example Bank"},
            {"label_name": maturity_label, "value": maturity_value},
            {"label_name": fields["td_roa_reason"], "value": "Review"},
            {"label_name": fields["notes"], "value": "<p>Internal task note.</p>"},
        ],
    }


class AzureModelRouteTests(TestCase):
    def test_azure_model_test_route(self) -> None:
        with (
            patch(
                "api.main.azure_openai.test_model",
                new=AsyncMock(return_value="The capital of France is Paris."),
            ),
            patch(
                "api.main.azure_openai.deployment_name",
                return_value="Mistral-Large-3",
            ),
        ):
            response = TestClient(app).get("/azure-model-test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["model"], "Mistral-Large-3")
        self.assertIn("Paris", response.json()["response"])

    def test_azure_model_test_returns_clean_authentication_error(self) -> None:
        with patch(
            "api.main.azure_openai.test_model",
            new=AsyncMock(side_effect=ClientAuthenticationError("expired token")),
        ):
            response = TestClient(app).get("/azure-model-test")

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("expired token", response.json()["detail"])


class PdfRenderTests(TestCase):
    def test_task_register_has_only_the_approved_columns(self) -> None:
        labels = [label for label, _field, _weight in _TASK_COLUMNS]

        self.assertIn("Notes", labels)
        self.assertNotIn("Project Group", labels)
        self.assertNotIn("Latest Comment", labels)
        self.assertNotIn("Head Client Name", labels)

    def test_unknown_project_prefix_is_uncategorized(self) -> None:
        self.assertEqual(_infer_project_group("FP - Annual Review"), "Financial Planning")
        self.assertEqual(_infer_project_group("BS - BAS"), "Business Services")
        self.assertEqual(_infer_project_group("Other Project"), "Uncategorized")

    def test_term_deposit_fields_for_clients_101_53_and_3(self) -> None:
        fields = field_map()
        project = {"id": "td-project", "name": "FP - Term Deposits"}
        fixtures = {
            "101": (
                _term_deposit_task(
                    "101",
                    cash_value={"display_value": "Macquarie CMA 101"},
                    maturity_label="Maturity Instructions",
                    maturity_value=[{"display_value": "Renew"}, {"display_value": "Review rate"}],
                ),
                "Macquarie CMA 101",
                "Renew, Review rate",
            ),
            "53": (
                _term_deposit_task(
                    "53",
                    cash_value="Cash Hub 53",
                    maturity_label=fields["maturity_instruction"],
                    maturity_value="Renew at maturity",
                ),
                "Cash Hub 53",
                "Renew at maturity",
            ),
            "3": (
                _term_deposit_task(
                    "3",
                    cash_value={"formatted_value": "CMA 3"},
                    maturity_label="Maturity Instruction",
                    maturity_value={"name": "Transfer to cash"},
                ),
                "CMA 3",
                "Transfer to cash",
            ),
        }

        for client_id, (task, expected_cash, expected_maturity) in fixtures.items():
            with self.subTest(head_client_id=client_id):
                self.assertTrue(
                    _matches_head_client(task, project, client_id, fields)
                )
                rows = _build_rows([(task, project)], fields)
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row.cash_account, expected_cash)
                self.assertEqual(row.maturity_instruction, expected_maturity)
                self.assertEqual(row.td_value, 12_500)
                self.assertEqual(row.owner, "Owner Name")
                self.assertTrue(row.td_applicable)
                if client_id == "53":
                    self.assertEqual(row.custom_status, "In progress")
                    self.assertEqual(row.preparer, "Accountant")
                    self.assertEqual(row.td_term, "6 months")
                    self.assertEqual(row.provider, "Example Bank")
                    self.assertEqual(row.td_roa_reason, "Review")
                    self.assertEqual(row.notes, "Internal task note.")

    def test_term_deposit_fields_are_not_applicable_without_td_project(self) -> None:
        rows = _build_rows(
            [({"name": "Prepare BAS"}, {"name": "BS - Quarterly Compliance"})],
            field_map(),
        )

        self.assertFalse(rows[0].td_applicable)

    def test_missing_values_render_as_blank_cells(self) -> None:
        row = TaskRow(
            project_name="BS - BAS",
            task_name="Prepare BAS",
            project_group="Business Services",
            custom_status="In progress",
            owner="_",
            preparer="Not applicable",
            cash_account="",
            td_value=None,
            td_term="",
            provider="",
            maturity_instruction="",
            td_roa_reason="",
            notes="",
            td_applicable=False,
        )
        table = _task_register_table([row], 1_000)
        body_text = [cell.getPlainText() for cell in table._cellvalues[1]]
        self.assertNotIn("Not applicable", body_text)
        self.assertNotIn("_", body_text)
        self.assertEqual(body_text[3:], [""] * 9)

    def test_owner_uses_complete_zoho_name(self) -> None:
        rows = _build_rows(
            [
                (
                    {
                        "name": "Prepare BAS",
                        "details": {
                            "owners": [
                                {
                                    "name": "Alex",
                                    "first_name": "Alex",
                                    "last_name": "Morgan",
                                    "full_name": "Alex Morgan",
                                }
                            ]
                        },
                    },
                    {"name": "BS - BAS"},
                )
            ],
            field_map(),
        )
        self.assertEqual(rows[0].owner, "Alex Morgan")

    def test_head_client_id_is_displayed_at_top(self) -> None:
        data = ReportData(
            title="Client Snapshot Report",
            head_client_id="53",
            tasks_total=0,
            prepared_by="Advisory Partners",
            as_at="28 July 2026",
            rows=[],
            selected_comments=[],
        )

        header_text = [paragraph.getPlainText() for paragraph in _header_block(data)]

        self.assertEqual(header_text[2], "Head Client ID: 53")

    def test_selected_section_is_named_task_comments(self) -> None:
        self.assertEqual(_SELECTED_COMMENTS_TITLE, "Selected Task Comments")

    def test_task_summary_renders_for_clients_101_53_and_3(self) -> None:
        row = TaskRow(
            project_name="FP - Reviews",
            task_name="Review term deposit",
            project_group="Financial Planning",
            custom_status="In progress",
            owner="Test Owner",
            preparer="Test Preparer",
            cash_account="Cash account",
            td_value=10_000,
            td_term="6 months",
            provider="Test Bank",
            maturity_instruction="Renew",
            td_roa_reason="Review",
            notes="Client approved the proposed renewal.",
        )
        for client_id in ("101", "53", "3"):
            with self.subTest(head_client_id=client_id):
                data = ReportData(
                    title="Client Snapshot Report",
                    head_client_id=client_id,
                    tasks_total=1,
                    prepared_by="Advisory Partners",
                    as_at="28 July 2026",
                    rows=[row],
                    selected_comments=[
                        (
                            row.task_name,
                            row.project_name,
                            "The client asked to renew the term deposit.",
                        )
                    ],
                )

                pdf_bytes = render_task_summary_pdf(data)

                self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
                self.assertGreater(len(pdf_bytes), 1_000)


class SelectedCommentsTests(IsolatedAsyncioTestCase):
    async def test_only_comments_from_past_180_days_are_summarized(self) -> None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        recent_ms = now_ms - 179 * 24 * 60 * 60 * 1000
        old_ms = now_ms - 181 * 24 * 60 * 60 * 1000
        comments = [
            {
                "created_time_long": old_ms,
                "created_time": "01-01-2026",
                "added_person": "Advisor",
                "content": "This comment is outside the permitted window.",
            },
            {
                "created_time_long": recent_ms,
                "created_time": "27-07-2026",
                "added_person": "Advisor",
                "content": "This comment is within the permitted window.",
            },
        ]
        matched = [
            (
                {
                    "id": "task-1",
                    "name": "Advice task",
                    "last_updated_time_long": now_ms,
                    "custom_fields": [
                        {"label_name": "Notes", "value": "Do not summarize this note."}
                    ],
                },
                {"id": "project-1", "name": "FP - Advice"},
            )
        ]
        rows = _build_rows(matched, field_map())

        with (
            patch(
                "api.automations.task_summary_report.service.client.get_task_comments",
                new=AsyncMock(return_value=comments),
            ),
            patch(
                "api.automations.task_summary_report.service.azure_openai.summarize_comments",
                new=AsyncMock(return_value="The recent comment was summarized."),
            ) as summarize,
        ):
            selected = await _build_selected_comments(matched, rows)

        self.assertEqual(len(selected), 1)
        context = summarize.await_args.args[2]
        self.assertIn("within the permitted window", context)
        self.assertNotIn("outside the permitted window", context)
        self.assertNotIn("Do not summarize this note", context)

    async def test_comments_stay_attached_to_the_correct_sorted_task(self) -> None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        matched = [
            (
                {"id": "fp-task", "name": "FP task"},
                {"id": "fp-project", "name": "FP - Advice"},
            ),
            (
                {"id": "bs-task", "name": "BS task"},
                {"id": "bs-project", "name": "BS - Compliance"},
            ),
        ]
        rows = _build_rows(matched, field_map())

        async def comments_for_task(_project_id: str, task_id: str) -> list[dict]:
            return [
                {
                    "created_time_long": now_ms,
                    "content": f"Comment for {task_id}",
                }
            ]

        async def summarize_for_task(
            task_name: str,
            _project_name: str,
            comments: str,
        ) -> str:
            return f"{task_name}: {comments}"

        with (
            patch(
                "api.automations.task_summary_report.service.client.get_task_comments",
                new=AsyncMock(side_effect=comments_for_task),
            ),
            patch(
                "api.automations.task_summary_report.service.azure_openai.summarize_comments",
                new=AsyncMock(side_effect=summarize_for_task),
            ),
        ):
            selected = await _build_selected_comments(matched, rows)

        by_task = {task: summary for task, _project, summary in selected}
        self.assertIn("Comment for bs-task", by_task["BS task"])
        self.assertIn("Comment for fp-task", by_task["FP task"])

    async def test_task_notes_or_activity_without_recent_comments_are_excluded(self) -> None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        matched = [
            (
                {
                    "id": "task-3",
                    "name": "Client 3 task",
                    "last_updated_time_long": now_ms,
                    "custom_fields": [
                        {"label_name": "Notes", "value": "Recent task note only."}
                    ],
                },
                {"id": "project-3", "name": "FP - Advice"},
            )
        ]
        rows = _build_rows(matched, field_map())

        with (
            patch(
                "api.automations.task_summary_report.service.client.get_task_comments",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "api.automations.task_summary_report.service.azure_openai.summarize_comments",
                new=AsyncMock(),
            ) as summarize,
        ):
            selected = await _build_selected_comments(matched, rows)

        self.assertEqual(selected, [])
        summarize.assert_not_awaited()

    async def test_ai_prompt_is_comments_only_with_no_weighting(self) -> None:
        with patch(
            "api.automations.task_summary_report.azure_openai._create_completion",
            return_value="Summary",
        ) as create_completion:
            result = await azure_openai.summarize_comments(
                "Task name",
                "Project name",
                "28-07-2026 - Advisor: Client requested renewal.",
            )

        self.assertEqual(result, "Summary")
        messages = create_completion.call_args.args[0]
        system_prompt = messages[0]["content"]
        user_prompt = messages[1]["content"]
        self.assertIn("past 180 days", system_prompt)
        self.assertIn("Do not infer or summarise overall task activity", system_prompt)
        self.assertIn("Do not weight", system_prompt)
        self.assertNotIn("Task name", user_prompt)
        self.assertNotIn("Project name", user_prompt)
        self.assertNotIn("Notes:", user_prompt)
        self.assertIn("Client requested renewal.", user_prompt)


class PowerAutomateDeliveryTests(IsolatedAsyncioTestCase):
    async def test_flow_receives_recipient_and_pdf_attachment(self) -> None:
        response = MagicMock(status_code=200)
        http_client = AsyncMock()
        http_client.post.return_value = response
        context_manager = AsyncMock()
        context_manager.__aenter__.return_value = http_client

        with patch(
            "api.automations.task_summary_report.power_automate.httpx.AsyncClient",
            return_value=context_manager,
        ):
            await power_automate.deliver_pdf(
                "https://flow.example.test/report",
                requestor_email="requestor@example.test",
                filename="snapshot.pdf",
                pdf_bytes=b"%PDF-test",
            )

        payload = http_client.post.await_args.kwargs["json"]
        self.assertEqual(payload["request_email"], "requestor@example.test")
        self.assertEqual(payload["filename"], "snapshot.pdf")
        self.assertEqual(payload["content_type"], "application/pdf")
        self.assertEqual(base64.b64decode(payload["pdf_b64"]), b"%PDF-test")
        self.assertEqual(
            set(payload),
            {"filename", "content_type", "pdf_b64", "request_email"},
        )


class LiveReportScriptTests(IsolatedAsyncioTestCase):
    async def test_live_script_uses_standard_renderer_azure_summary_and_email(self) -> None:
        task = _term_deposit_task(
            "53",
            cash_value="Cash Hub 53",
            maturity_label="Maturity Instructions",
            maturity_value="Renew",
        )
        project = {"id": "td-project", "name": "FP - Term Deposits"}
        args = Namespace(
            head_client_id="53",
            requestor_email="requestor@example.test",
            webhook_url="https://flow.example.test/report",
            output=Path("output/pdf/live-client-53.pdf"),
            active_only=False,
        )
        rendered_pdf = b"%PDF-live-report"

        with (
            patch.object(
                generate_actual_task_summary,
                "resolve_matching_tasks",
                new=AsyncMock(return_value=([(task, project)], 8)),
            ),
            patch.object(
                generate_actual_task_summary,
                "_build_selected_comments",
                new=AsyncMock(
                    return_value=[
                        (
                            task["name"],
                            project["name"],
                            "The client requested renewal.",
                        )
                    ]
                ),
            ) as build_comments,
            patch.object(
                generate_actual_task_summary,
                "render_task_summary_pdf",
                return_value=rendered_pdf,
            ) as render_pdf,
            patch.object(Path, "mkdir"),
            patch.object(Path, "write_bytes", return_value=len(rendered_pdf)) as write_pdf,
            patch.object(
                generate_actual_task_summary.power_automate,
                "validate_webhook_url",
            ) as validate_webhook,
            patch.object(
                generate_actual_task_summary.power_automate,
                "deliver_pdf",
                new=AsyncMock(),
            ) as deliver_pdf,
        ):
            output = await generate_actual_task_summary.generate_live_report(args)

        report = render_pdf.call_args.args[0]
        self.assertEqual(report.title, "Client Snapshot Report")
        self.assertEqual(report.head_client_id, "53")
        self.assertEqual(
            report.selected_comments[0][2],
            "The client requested renewal.",
        )
        build_comments.assert_awaited_once()
        write_pdf.assert_called_once_with(rendered_pdf)
        validate_webhook.assert_called_once_with(args.webhook_url)
        deliver_pdf.assert_awaited_once()
        self.assertEqual(
            deliver_pdf.await_args.kwargs["requestor_email"],
            args.requestor_email,
        )
        self.assertEqual(deliver_pdf.await_args.kwargs["pdf_bytes"], rendered_pdf)
        self.assertEqual(output.name, "live-client-53.pdf")
