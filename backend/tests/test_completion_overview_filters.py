from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.automations.completion_overview.models import ReportRequest
from api.automations.completion_overview.service import resolve_projects
from api.main import app


_PROJECTS = [
    {"id": "1", "name": "BS - Jul 26 BAS (AP)", "status": "active"},
    {"id": "2", "name": "BS - Jul 26 Compliance", "status": "active"},
    {"id": "3", "name": "FP - Advice", "status": "active"},
    {"id": "4", "name": "BS - Aug 26 BAS (AP)", "status": "inactive"},
    {"id": "5", "name": "SMSF - Annual", "status": "active"},
    {"id": "6", "name": None, "status": "active"},
]


class CompletionOverviewFilterTests(IsolatedAsyncioTestCase):
    async def _selected_ids(self, **filters) -> list[str]:
        request = ReportRequest(active_only=False, dry_run=True, **filters)
        with patch(
            "api.automations.completion_overview.service.client.list_projects",
            new=AsyncMock(return_value=_PROJECTS),
        ):
            selected = await resolve_projects(request)
        return sorted(str(project["id"]) for project in selected)

    async def test_filter_precedence_and_combinations(self) -> None:
        cases = [
            (
                "include ids ignore include names",
                {
                    "projects_include_IDs": ["3"],
                    "projects_include_Names": ["bs"],
                },
                ["3"],
            ),
            (
                "unknown include id still prevents name fallback",
                {
                    "projects_include_IDs": ["999"],
                    "projects_include_Names": ["bs"],
                },
                [],
            ),
            (
                "include names when include ids empty",
                {
                    "projects_include_IDs": [],
                    "projects_include_Names": ["bs"],
                },
                ["1", "2", "4"],
            ),
            (
                "multiple include name keywords are OR filters",
                {"projects_include_Names": ["bs", "advice"]},
                ["1", "2", "3", "4"],
            ),
            (
                "exclude name overrides include ids",
                {
                    "projects_include_IDs": ["1", "2"],
                    "projects_exclude_Names": ["compliance"],
                },
                ["1"],
            ),
            (
                "exclude name overrides include names",
                {
                    "projects_include_Names": ["bs"],
                    "projects_exclude_Names": ["compliance"],
                },
                ["1", "4"],
            ),
            (
                "exclude id overrides include names",
                {
                    "projects_include_Names": ["bs"],
                    "projects_exclude_IDs": ["1"],
                },
                ["2", "4"],
            ),
            (
                "exclude id overrides include ids",
                {
                    "projects_include_IDs": ["1", "3"],
                    "projects_exclude_IDs": ["1"],
                },
                ["3"],
            ),
            (
                "exclude ids and names are both enforced",
                {
                    "projects_include_Names": ["bs"],
                    "projects_exclude_IDs": ["1"],
                    "projects_exclude_Names": ["compliance"],
                },
                ["4"],
            ),
            (
                "exclude id works without include filters",
                {"projects_exclude_IDs": ["1"]},
                ["2", "3", "4", "5", "6"],
            ),
            (
                "exclude name works without include filters",
                {"projects_exclude_Names": ["bs"]},
                ["3", "5", "6"],
            ),
            (
                "same project included by id and excluded by id",
                {
                    "projects_include_IDs": ["1"],
                    "projects_exclude_IDs": ["1"],
                },
                [],
            ),
            (
                "same project included by id and excluded by name",
                {
                    "projects_include_IDs": ["1"],
                    "projects_exclude_Names": ["bas"],
                },
                [],
            ),
            (
                "keywords are trimmed and case insensitive",
                {"projects_include_Names": ["  bS  "]},
                ["1", "2", "4"],
            ),
        ]

        for label, filters, expected in cases:
            with self.subTest(label=label):
                self.assertEqual(await self._selected_ids(**filters), expected)

    async def test_active_only_is_applied_after_include_and_exclude_filters(
        self,
    ) -> None:
        request = ReportRequest(
            projects_include_Names=["bs"],
            projects_exclude_Names=["compliance"],
            active_only=True,
            dry_run=True,
        )
        with patch(
            "api.automations.completion_overview.service.client.list_projects",
            new=AsyncMock(return_value=_PROJECTS),
        ):
            selected = await resolve_projects(request)

        self.assertEqual([project["id"] for project in selected], ["1"])

    async def test_duplicate_and_blank_filters_are_normalized(self) -> None:
        request = ReportRequest(
            projects_include_IDs=[" 1 ", "1", ""],
            projects_include_Names=["bs"],
            projects_exclude_IDs=["", " 9 "],
            projects_exclude_Names=[" ", "COMPLIANCE", "compliance"],
            active_only=False,
            dry_run=True,
        )

        self.assertEqual(request.projects_include_IDs, ["1"])
        self.assertEqual(request.projects_exclude_IDs, ["9"])
        self.assertEqual(request.projects_exclude_Names, ["COMPLIANCE"])
        with patch(
            "api.automations.completion_overview.service.client.list_projects",
            new=AsyncMock(return_value=_PROJECTS),
        ):
            selected = await resolve_projects(request)
        self.assertEqual([project["id"] for project in selected], ["1"])

    async def test_power_json_encoded_arrays_are_normalized(self) -> None:
        request = ReportRequest.model_validate(
            {
                "projects_include_IDs": '[" 1 ", "1"]',
                "projects_exclude_IDs": "[]",
                "projects_include_Names": '["advice"]',
                "projects_exclude_Names": '["compliance"]',
                "projects_include_Emails": (
                    '["first@example.com", "second@example.com"]'
                ),
                "active_only": False,
                "dry_run": True,
            }
        )

        self.assertEqual(request.projects_include_IDs, ["1"])
        self.assertEqual(request.projects_exclude_IDs, [])
        self.assertEqual(request.projects_include_Names, ["advice"])
        self.assertEqual(request.projects_exclude_Names, ["compliance"])
        self.assertEqual(
            request.projects_include_Emails,
            ["first@example.com", "second@example.com"],
        )
        with patch(
            "api.automations.completion_overview.service.client.list_projects",
            new=AsyncMock(return_value=_PROJECTS),
        ):
            selected = await resolve_projects(request)
        self.assertEqual([project["id"] for project in selected], ["1"])

    def test_exclude_ids_only_is_a_valid_endpoint_request(self) -> None:
        with (
            patch(
                "api.automations.completion_overview.routes.create_job",
                return_value="exclude-only-job",
            ),
            patch(
                "api.automations.completion_overview.routes.queue.dispatch_report",
            ) as dispatch,
        ):
            response = TestClient(app).post(
                "/reports/completion",
                json={
                    "projects_exclude_IDs": ["2"],
                    "dry_run": True,
                },
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            dispatch.call_args.args[1].projects_exclude_IDs,
            ["2"],
        )

    def test_empty_filter_request_is_rejected(self) -> None:
        response = TestClient(app).post(
            "/reports/completion",
            json={"dry_run": True},
        )
        self.assertEqual(response.status_code, 400)
