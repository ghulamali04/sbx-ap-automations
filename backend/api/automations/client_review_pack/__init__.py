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

Live data sourcing, section by section — every section has a `live/<name>.py`
module exposing `fetch_live_<name>(...) -> <Name>Data`; only the actual
external API call is left to add where noted:
  - Task Summary — fully wired. `live/task_summary.py` fetches from Zoho by
    reusing `task_summary_report.service` (still fully present and wired into
    `main.py`, not removed) and maps its rows onto `sections/task_summary.py`'s
    models. `test_task_summary_live.py` (repo root `backend/`) is a quick local
    check of this path.
  - Email summary, investment summary, super & cash performance, SMSF
    snapshot, insurance review, group structure, compliance status — each
    `live/<name>.py` raises `NotImplementedError` with a docstring naming the
    specific source system to integrate (Praemium, AustralianSuper, Class,
    Xero Practice Manager, etc.) and the concrete steps, since no client for
    any of those systems exists anywhere in this codebase yet.
  - Meeting details — `live/meeting_details.py` documents why it doesn't fit
    this package's fetch-by-client-name shape at all: `meeting_notes`/MS Graph
    is push-driven (a transcript notification triggers a handoff to Power
    Automate, which generates the summary and emails it — nothing structured
    comes back to this app).
  - Until a section's stub is filled in, its `build_<name>_section` still takes
    hand-supplied data (see `test_full_pack.py` for the sample data currently
    used for everything but Task Summary).

Not yet built (deliberately, per the phased plan):
  - Combining every section into one final pack — `pdf_builder.combine_sections`
    handles same-page-size groups now; mixing the portrait A4 sections with the
    landscape register-style ones is the deferred follow-up.
  - HTTP routes / async job wiring / Power Automate delivery for this pack as a
    whole — `completion_overview` and `task_summary_report` show the established
    202-plus-poll pattern to follow once more sections have live sourcing.
"""
