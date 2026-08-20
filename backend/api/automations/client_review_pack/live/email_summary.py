"""
Live Email Summary data — STUB. No correspondence/email API is integrated
anywhere in this codebase (no Outlook/Graph mail client, no CRM client). This
module owns everything except that one call: the request shape, the return
model, and where the fetch belongs. Wire the actual API call where marked
below, then this section is live.
"""
from __future__ import annotations

from api.automations.client_review_pack.sections.email_summary import EmailSummaryData


async def fetch_live_email_summary(client_name: str, *, period_start: str | None = None, period_end: str | None = None) -> EmailSummaryData:
    """Fetch and shape one client's correspondence summary.

    To make this live:
      1. Add a client module (e.g. `api/automations/outlook/client.py` or a CRM
         client) that authenticates and lists/searches messages for a client —
         follow `api/automations/zoho/client.py`'s shape (thin async wrapper,
         token from an auth/session module, plain dicts back).
      2. Add its credentials to `local.settings.json` (e.g. reuse
         `GRAPH_TENANT_ID`/`GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET` if Outlook
         mail via Graph, or new `*_API_KEY` vars for a CRM).
      3. Replace the `raise` below with: fetch raw messages/threads for
         `client_name` within [`period_start`, `period_end`], summarize each
         into an `EmailSummaryEntry` (date_period, topic, summary, outcome),
         return `EmailSummaryData(client_name=..., period_label=..., entries=...)`.
    """
    raise NotImplementedError(
        "No email/correspondence API is integrated in this codebase yet — "
        "see this function's docstring for what to add."
    )
