import asyncio

from api.settings import load_local_settings

load_local_settings()

from api.automations.meeting_notes import artifacts, service
from api.automations.meeting_notes.models import NoteJobRequest


async def main() -> None:
    vtt = open("tests/fixtures/sample_meeting.vtt", encoding="utf-8").read()
    req = NoteJobRequest(
        transcript_resource="communications/onlineMeetings('test-meeting')/transcripts('test-transcript')",
        transcript_vtt=vtt,
        dry_run=True,
    )
    result = await service.run_note_job(req, job_id="test-1")
    print(result.model_dump_json(indent=2))
    html = artifacts.load_note("test-1")
    if html:
        out_path = "tests/fixtures/sample_note_output.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n--- rendered note saved to {out_path} ({len(html)} chars) ---")


asyncio.run(main())
