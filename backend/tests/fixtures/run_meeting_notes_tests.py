"""Run all meeting_notes manual test cases in one go and print PASS/FAIL per case."""
import asyncio

from api.settings import load_local_settings

load_local_settings()

from api.automations.meeting_notes import artifacts, graph, service
from api.automations.meeting_notes.models import NoteJobRequest

TEST_USER = "gali@AdvisoryPartners603.onmicrosoft.com"


async def case_1_fake_transcript_pipeline() -> None:
    """Fake .vtt -> parse -> Azure OpenAI note -> HTML + PDF render (no Graph, no email).

    organizer_id_override=TEST_USER is a test-only hook (see models.py) so the
    fake transcript still exercises routing and calendar scheduling exactly like
    a real one would, keyed off Gali's real Graph identity.
    """
    vtt = open("tests/fixtures/sample_meeting.vtt", encoding="utf-8").read()
    req = NoteJobRequest(
        transcript_resource="communications/onlineMeetings('test-meeting')/transcripts('test-transcript')",
        transcript_vtt=vtt,
        organizer_id_override=TEST_USER,
        dry_run=True,
    )
    result = await service.run_note_job(req, job_id="test-1")
    html = artifacts.load_note("test-1")
    pdf_bytes = artifacts.load_note_pdf("test-1")
    if result.error or not html or not pdf_bytes:
        print(f"[FAIL] case_1_fake_transcript_pipeline: {result.error}")
        return
    with open("tests/fixtures/sample_note_output.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open("tests/fixtures/sample_note_output.pdf", "wb") as f:
        f.write(pdf_bytes)
    print(
        f"[PASS] case_1_fake_transcript_pipeline: html={len(html)} chars, "
        f"pdf={len(pdf_bytes)} bytes, business_area={result.business_area!r}"
    )
    print(f"       calendar_events: {result.calendar_events}")


async def case_2_real_user_lookup() -> None:
    """Graph.get_user() for the real tenant user — needs User.Read.All admin consent."""
    try:
        user = await graph.get_user(TEST_USER)
        print(f"[PASS] case_2_real_user_lookup: {user}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] case_2_real_user_lookup: {exc}")


async def case_3_real_transcript_listing() -> None:
    """Graph.list_transcripts_for_user() — needs OnlineMeetingTranscript.Read.All."""
    try:
        transcripts = await graph.list_transcripts_for_user(TEST_USER)
        print(f"[PASS] case_3_real_transcript_listing: {len(transcripts)} transcript(s) found")
        for t in transcripts:
            print(f"   - meetingId={t.get('meetingId')} id={t.get('id')} created={t.get('createdDateTime')}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] case_3_real_transcript_listing: {exc}")


async def main() -> None:
    await case_1_fake_transcript_pipeline()
    await case_2_real_user_lookup()
    await case_3_real_transcript_listing()


asyncio.run(main())
