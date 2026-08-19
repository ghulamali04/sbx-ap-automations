"""
Client Review Pack / Global Client Summary automation.

Combines the several per-system reports Advisory Partners already prepares for a
client household (meeting notes, email correspondence, managed-portfolio
investment reports, AustralianSuper cash & performance, SMSF snapshots, personal
insurance risk review, group structure, Zoho task register, ATO lodgement status)
into one branded PDF pack.

Each report type lives in its own module under `sections/`, with a typed
Pydantic input model decoupled from any particular source system, and a
`build_<name>_section(data) -> Section` function.

Live data sourcing, section by section:
  - Task Summary — wired. `live/task_summary.py` fetches from Zoho by reusing
    `task_summary_report.service` (which is still fully present and wired into
    `main.py`, not removed) and maps its rows onto `sections/task_summary.py`'s
    models. `test_task_summary_live.py` (repo root `backend/`) is a quick local
    check of this path.
  - Everything else (email summary, investment summary/Praemium, super &
    performance/AustralianSuper, SMSF/Class, insurance, group structure,
    compliance/Xero Practice Manager, meeting details) — no client for these
    source systems exists in this codebase yet (or, for meeting details, the
    existing `meeting_notes`/MS Graph automation hands transcripts to Power
    Automate for AI summarization and never returns structured agenda/action
    data to this app). Those sections still take pre-resolved sample data.

Not yet built (deliberately, per the phased plan):
  - Combining every section into one final pack — `pdf_builder.combine_sections`
    handles same-page-size groups now; mixing the portrait A4 sections with the
    landscape register-style ones is the deferred follow-up.
  - HTTP routes / async job wiring / Power Automate delivery for this pack as a
    whole — `completion_overview` and `task_summary_report` show the established
    202-plus-poll pattern to follow once more sections have live sourcing.
"""
