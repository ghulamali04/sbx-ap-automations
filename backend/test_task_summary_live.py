"""
Live test — fetches one head client's real Zoho task register (no sample
data) and renders it through the Task Summary section.

Usage:
    python test_task_summary_live.py "<head_client_id>" [--active-only]

Requires ZOHO_PORTAL_ID / ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / ZOHO_REDIRECT_URI
/ ZOHO_ACCOUNTS_URL set (local.settings.json or the shell environment) and a
Zoho OAuth token already stored via the existing /zoho auth routes — otherwise
this fails with a clear auth error rather than a raw traceback.
"""
import asyncio
import sys

sys.path.insert(0, ".")

from api.settings import load_local_settings

load_local_settings()

from api.lib import pdf_builder as pb
from api.automations.client_review_pack.live.task_summary import fetch_live_task_summary
from api.automations.client_review_pack.sections.task_summary import build_task_summary_section


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    active_only = "--active-only" in sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    head_client_id = args[0]

    print(f"Fetching live Zoho tasks for head_client_id={head_client_id!r} (active_only={active_only})...")
    try:
        data = await fetch_live_task_summary(head_client_id, active_only=active_only)
    except Exception as exc:
        print(f"FAILED: {exc}")
        return 1

    print(f"OK: tasks_total={data.tasks_total}, selected_comments={len(data.selected_comments)}")

    section = build_task_summary_section(data)
    pdf_bytes = pb.render_section_pdf(section)
    out_path = "task_summary_live_output.pdf"
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"wrote {out_path} ({len(pdf_bytes)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
