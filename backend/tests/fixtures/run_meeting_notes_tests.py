"""Run all meeting_notes manual test cases in one go and print PASS/FAIL per case."""
import asyncio
from datetime import datetime, timezone

from api.settings import load_local_settings

load_local_settings()

from api.automations.meeting_notes import graph, service
from api.automations.meeting_notes.models import NoteJobRequest

TEST_USER = "gali@AdvisoryPartners603.onmicrosoft.com"

# Meeting metadata for the transcript_vtt local-testing path — a .vtt file only
# carries spoken text, so these stand in for what get_transcript_metadata /
# get_online_meeting supply when Graph is reachable (see models.py's *_override
# hooks). Values reflect a realistic scheduled meeting, not placeholder data.
SAMPLE_MEETING_DATE = datetime.now(timezone.utc).isoformat()
SAMPLE_MEETING_TITLE = "Gali Client — Quarterly Financial Planning Review"
SAMPLE_ATTENDEE_EMAILS = [
    "gali@AdvisoryPartners603.onmicrosoft.com",  # organiser (adviser)
    "client.gali@example.test",  # client
    "paraplanner@AdvisoryPartners603.onmicrosoft.com",  # cc'd colleague
]


async def case_1_local_transcript_pipeline() -> None:
   
    vtt = open("tests/fixtures/sample_meeting.vtt", encoding="utf-8").read()
    req = NoteJobRequest(
        transcript_resource="communications/onlineMeetings('test-meeting')/transcripts('test-transcript')",
        transcript_vtt=vtt,
        organizer_id_override=TEST_USER,
        meeting_date_override=SAMPLE_MEETING_DATE,
        meeting_title_override=SAMPLE_MEETING_TITLE,
        attendee_emails_override=SAMPLE_ATTENDEE_EMAILS,
        dry_run=True,
    )
    result = await service.run_note_job(req, job_id="test-1")
    if result.error:
        print(f"[FAIL] case_1_local_transcript_pipeline: {result.error}")
        return
    print(
        f"[PASS] case_1_local_transcript_pipeline: business_area={result.business_area!r}, "
        f"organizer_email={result.organizer_email!r}"
    )
    print(f"       meeting_date={result.meeting_date!r}")
    print(f"       meeting_title={result.meeting_title!r}")
    print(f"       attendee_emails={result.attendee_emails!r}")


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


async def case_4_real_transcript_full_pipeline() -> None:
   
    try:
        transcripts = await graph.list_transcripts_for_user(TEST_USER)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] case_4_real_transcript_full_pipeline: transcript listing failed: {exc}")
        return
    if not transcripts:
        print("[SKIP] case_4_real_transcript_full_pipeline: no real transcripts found for this user")
        return

    latest = transcripts[0]
   
    content_url = latest["transcriptContentUrl"]
    resource = content_url.split("/v1.0/", 1)[1].removesuffix("/content")
    req = NoteJobRequest(transcript_resource=resource, dry_run=True)
    result = await service.run_note_job(req, job_id="test-4")
    if result.error:
        print(f"[FAIL] case_4_real_transcript_full_pipeline: {result.error}")
        return
    print(
        f"[PASS] case_4_real_transcript_full_pipeline: organizer_email={result.organizer_email!r}, "
        f"business_area={result.business_area!r}"
    )
    print(f"       meeting_date={result.meeting_date!r}")
    print(f"       meeting_title={result.meeting_title!r}  <- needs OnlineMeetings.Read.All if this is None")
    print(f"       attendee_emails={result.attendee_emails!r}")


async def case_5_live_power_automate_handoff() -> None:
   
    vtt = open("tests/fixtures/sample_meeting.vtt", encoding="utf-8").read()
    req = NoteJobRequest(
        transcript_resource="communications/onlineMeetings('test-meeting')/transcripts('test-transcript')",
        transcript_vtt=vtt,
        organizer_id_override=TEST_USER,
        meeting_date_override=SAMPLE_MEETING_DATE,
        meeting_title_override=SAMPLE_MEETING_TITLE,
        attendee_emails_override=SAMPLE_ATTENDEE_EMAILS,
        dry_run=False,
    )
    result = await service.run_note_job(req, job_id="test-5")
    status = "PASS" if result.delivered and not result.error else "FAIL"
    print(f"[{status}] case_5_live_power_automate_handoff: delivered={result.delivered}, error={result.error}")


async def main() -> None:
    await case_1_local_transcript_pipeline()
    await case_2_real_user_lookup()
    await case_3_real_transcript_listing()
    await case_4_real_transcript_full_pipeline()
    print(
        "\nNote: case_5_live_power_automate_handoff (real webhook call, sends a "
        "real email) is not run automatically. Run with --live to include it."
    )


if __name__ == "__main__":
    import sys

    asyncio.run(main())
    if "--live" in sys.argv:
        asyncio.run(case_5_live_power_automate_handoff())
