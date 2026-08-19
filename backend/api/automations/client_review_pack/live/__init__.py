"""
Live data-fetch adapters for `client_review_pack` sections.

Each module here fetches from a source system already integrated elsewhere in
this codebase and maps the result onto the matching section's Pydantic input
model — it does not duplicate fetch/auth logic that automation already owns.
Only sections with a genuine existing client get a module here; see each
section's own docstring for whether live wiring exists yet.
"""
