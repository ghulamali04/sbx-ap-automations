from __future__ import annotations

import base64
from datetime import datetime, timezone
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from azure.core.exceptions import ClientAuthenticationError
from fastapi.testclient import TestClient

from api.automations.task_summary_report import power_automate
from api.automations.task_summary_report.models import field_map
from api.automations.task_summary_report.pdf import (
    _TASK_COLUMNS,
    ReportData,
    TaskRow,
    render_task_summary_pdf,
)
from api.automations.task_summary_report.service import (
    _build_rows,
    _build_selected_notes,
    _infer_project_group,
)
from api.main import app


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

    def test_task_fields_are_populated_from_zoho_custom_fields(self) -> None:
        fields = field_map()
        task = {
            "name": "Prepare BAS",
            "status": {"name": "In progress"},
            "details": {"owners": [{"name": "Owner Name"}]},
            "custom_fields": [
                {"label_name": fields["preparer"], "value": "Accountant"},
                {"label_name": fields["cash_account"], "value": "Cash Hub"},
                {"label_name": fields["td_value"], "value": "$12,500"},
                {"label_name": fields["td_term"], "value": "6 months"},
                {"label_name": fields["provider"], "value": "Example Bank"},
                {"label_name": fields["maturity_instruction"], "value": "Renew"},
                {"label_name": fields["td_roa_reason"], "value": "Review"},
                {"label_name": fields["notes"], "value": "<p>Client approved renewal.</p>"},
            ],
        }
        rows = _build_rows([(task, {"name": "FP - Term Deposits"})], fields)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.owner, "Owner Name")
        self.assertEqual(row.custom_status, "In progress")
        self.assertEqual(row.preparer, "Accountant")
        self.assertEqual(row.td_value, 12_500)
        self.assertEqual(row.notes, "Client approved renewal.")
        self.assertTrue(row.td_applicable)

    def test_term_deposit_fields_are_not_applicable_without_td_project(self) -> None:
        rows = _build_rows(
            [({"name": "Prepare BAS"}, {"name": "BS - Quarterly Compliance"})],
            field_map(),
        )

        self.assertFalse(rows[0].td_applicable)

    def test_task_summary_renders_as_pdf(self) -> None:
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
        data = ReportData(
            title="Client Snapshot Report",
            tasks_total=1,
            prepared_by="Advisory Partners",
            as_at="27 July 2026",
            rows=[row],
            selected_notes=[
                (
                    row.task_name,
                    row.project_name,
                    "The client approved renewing the term deposit.",
                )
            ],
        )

        pdf_bytes = render_task_summary_pdf(data)

        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 1_000)


class SelectedNotesTests(IsolatedAsyncioTestCase):
    async def test_recent_comment_qualifies_and_full_history_is_summarized(self) -> None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        old_ms = now_ms - 120 * 24 * 60 * 60 * 1000
        comments = [
            {
                "created_time_long": old_ms,
                "created_time": "01-01-2026",
                "added_person": "Advisor",
                "content": "Initial advice was prepared.",
            },
            {
                "created_time_long": now_ms,
                "created_time": "27-07-2026",
                "added_person": "Advisor",
                "content": "Client approved the advice.",
            },
        ]
        matched = [
            (
                {"id": "task-1", "name": "Advice task"},
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
                "api.automations.task_summary_report.service.azure_openai.summarize_note",
                new=AsyncMock(return_value="The advice was prepared and approved."),
            ) as summarize,
        ):
            selected = await _build_selected_notes(matched, rows)

        self.assertEqual(len(selected), 1)
        context = summarize.await_args.args[2]
        self.assertIn("Initial advice was prepared.", context)
        self.assertIn("Client approved the advice.", context)


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
        # The flow requires {filename, content_type, pdf_b64, request_email}.
        self.assertEqual(payload["request_email"], "requestor@example.test")
        self.assertEqual(payload["filename"], "snapshot.pdf")
        self.assertEqual(payload["content_type"], "application/pdf")
        self.assertEqual(base64.b64decode(payload["pdf_b64"]), b"%PDF-test")
