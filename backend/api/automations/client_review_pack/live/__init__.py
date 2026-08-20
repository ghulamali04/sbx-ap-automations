"""
Live data-fetch adapters for `client_review_pack` sections.

Every section has a `fetch_live_<name>(...)` here. Where a source system is
already integrated elsewhere in this codebase (currently just Zoho, for
`task_summary`), the module reuses that integration's fetch/auth logic rather
than duplicating it. Everywhere else the module is a stub: the request/return
shape is real, but it raises `NotImplementedError` — see each module's
docstring for exactly which API client to add and where the call belongs.
"""
