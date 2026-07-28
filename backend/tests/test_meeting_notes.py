from __future__ import annotations

import os
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.main import app
from api.automations.meeting_notes import azure_openai, graph, notes, routing, service, vtt
from api.automations.meeting_notes.models import ActionItem, MeetingNote, NoteJobRequest

_SAMPLE_VTT = """WEBVTT

00:00:03.000 --> 00:00:06.480
<v Jane Adviser>Thanks for joining today.</v>

00:00:06.500 --> 00:00:09.000
<v Jane Adviser>Let us review your super.</v>

00:00:09.500 --> 00:00:12.000
<v Client Bob>Sounds good, I want to increase contributions.</v>
"""

_RESOURCE = "communications/onlineMeetings('MID')/transcripts('TID')"


class VttParsingTests(TestCase):
    def test_merges_consecutive_turns_and_attributes_speakers(self):
        parsed = vtt.parse_vtt(_SAMPLE_VTT)
        self.assertIn(
            "Jane Adviser: Thanks for joining today. Let us review your super.",
            parsed,
        )
        self.assertIn("Client Bob: Sounds good", parsed)

    def test_untagged_cues_fall_back_to_unattributed_text(self):
        parsed = vtt.parse_vtt("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello there.")
        self.assertEqual(parsed, "Hello there.")


class RoutingTests(TestCase):
    def test_group_membership_wins(self):
        area = routing.resolve_business_area({"department": "anything"}, {"FP-Advisers"})
        self.assertEqual(area.key, "financial_planning")

    def test_department_keyword_matches(self):
        area = routing.resolve_business_area({"department": "Business Services team"}, set())
        self.assertEqual(area.key, "business_services")

    def test_unknown_organiser_falls_back_and_is_flagged(self):
        area = routing.resolve_business_area({"department": "Marketing"}, set())
        self.assertEqual(area.key, "general")
        self.assertTrue(area.flagged)


class NoteRenderingTests(TestCase):
    def test_missing_owner_and_date_render_not_specified(self):
        note = MeetingNote(
            summary="S", decisions=["D1"], actions=[ActionItem(description="Do X")]
        )
        html = notes.render_note_html(
            note,
            area=routing.GENERAL_AREA,
            subject="Test",
            organizer_name="Jane",
            meeting_date="2026-07-28",
        )
        self.assertIn("Not specified", html)
        self.assertIn("Do X", html)

    def test_general_area_shows_flag_banner(self):
        html = notes.render_note_html(
            MeetingNote(summary="S"),
            area=routing.GENERAL_AREA,
            subject="Test",
            organizer_name=None,
            meeting_date=None,
        )
        self.assertIn("general template", html)


class HelperTests(TestCase):
    def test_extract_meeting_and_transcript_ids(self):
        mid, tid = graph.extract_meeting_and_transcript_ids(
            "communications/onlineMeetings('MID==')/transcripts('TID==')"
        )
        self.assertEqual((mid, tid), ("MID==", "TID=="))

    def test_extract_json_tolerates_prose_and_fences(self):
        self.assertEqual(
            azure_openai._extract_json('junk {"summary": "ok", "decisions": []} tail')["summary"],
            "ok",
        )
        self.assertEqual(
            azure_openai._extract_json('```json\n{"summary":"x"}\n```')["summary"],
            "x",
        )


class ServiceTests(IsolatedAsyncioTestCase):
    async def test_end_to_end_delivery_routes_and_sends(self):
        metadata = {
            "meetingId": "MID",
            "createdDateTime": "2026-07-28T01:00:00Z",
            "meetingOrganizer": {"user": {"id": "org-1", "displayName": "Jane Adviser"}},
        }
        with patch.dict(os.environ, {"MEETING_NOTES_MAIL_SENDER": "service@firm.com"}), \
            patch.object(service.graph, "get_transcript_metadata", AsyncMock(return_value=metadata)), \
            patch.object(service.graph, "get_transcript_content", AsyncMock(return_value=_SAMPLE_VTT)), \
            patch.object(service.graph, "get_user", AsyncMock(return_value={
                "displayName": "Jane Adviser",
                "mail": "jane@firm.com",
                "department": "Financial Planning",
            })), \
            patch.object(service.graph, "user_group_names", AsyncMock(return_value={"FP-Advisers"})), \
            patch.object(azure_openai, "generate_note", AsyncMock(return_value=MeetingNote(
                summary="Reviewed super", decisions=["Increase contributions"]
            ))), \
            patch.object(service.graph, "send_mail", AsyncMock()) as send_mail:
            result = await service.run_note_job(
                NoteJobRequest(transcript_resource=_RESOURCE), job_id="job-e2e"
            )

        self.assertEqual(result.business_area, "Financial Planning")
        self.assertEqual(result.organizer_email, "jane@firm.com")
        self.assertTrue(result.delivered)
        self.assertIsNone(result.error)
        send_mail.assert_awaited_once()
        self.assertEqual(send_mail.await_args.kwargs["to_email"], "jane@firm.com")
        self.assertEqual(send_mail.await_args.kwargs["sender_id"], "service@firm.com")

    async def test_dry_run_stores_note_without_sending(self):
        from api.automations.meeting_notes import artifacts

        with patch.object(azure_openai, "generate_note", AsyncMock(return_value=MeetingNote(summary="x"))), \
            patch.object(service.graph, "send_mail", AsyncMock()) as send_mail:
            result = await service.run_note_job(
                NoteJobRequest(
                    transcript_resource=_RESOURCE,
                    transcript_vtt=_SAMPLE_VTT,
                    dry_run=True,
                ),
                job_id="job-dry",
            )

        self.assertFalse(result.delivered)
        send_mail.assert_not_awaited()
        self.assertIsNotNone(artifacts.load_note("job-dry"))


class WebhookRouteTests(TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_validation_handshake_echoes_token(self):
        resp = self.client.post("/meeting-notes/notifications?validationToken=abc%20123")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "abc 123")

    def test_bad_client_state_is_dropped(self):
        with patch.dict(os.environ, {"MEETING_NOTES_CLIENT_STATE": "secret123"}), \
            patch("api.automations.meeting_notes.routes.queue.dispatch_note") as dispatch:
            resp = self.client.post(
                "/meeting-notes/notifications",
                json={"value": [{"subscriptionId": "s", "resource": _RESOURCE, "clientState": "WRONG"}]},
            )
        self.assertEqual(resp.status_code, 202)
        dispatch.assert_not_called()

    def test_good_client_state_enqueues_job(self):
        with patch.dict(os.environ, {"MEETING_NOTES_CLIENT_STATE": "secret123"}), \
            patch("api.automations.meeting_notes.routes.queue.dispatch_note") as dispatch:
            resp = self.client.post(
                "/meeting-notes/notifications",
                json={"value": [{"subscriptionId": "s", "resource": _RESOURCE, "clientState": "secret123"}]},
            )
        self.assertEqual(resp.status_code, 202)
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.args[1].transcript_resource, _RESOURCE)

    def test_unknown_job_returns_404(self):
        self.assertEqual(self.client.get("/meeting-notes/does-not-exist").status_code, 404)
