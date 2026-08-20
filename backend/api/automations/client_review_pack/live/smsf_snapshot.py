"""
Live SMSF Fund/Portfolio Snapshot data — STUB. No Class (or equivalent SMSF
administration platform) API client exists in this codebase.
"""
from __future__ import annotations

from api.automations.client_review_pack.sections.smsf_snapshot import SMSFSnapshotData


async def fetch_live_smsf_snapshot(fund_code: str) -> SMSFSnapshotData:
    """Fetch and shape one SMSF's fund + portfolio snapshot.

    To make this live:
      1. Add `api/automations/class/client.py` (or whichever platform actually
         administers these funds) — follow `api/automations/zoho/client.py`'s
         shape.
      2. Add its credentials to `local.settings.json`.
      3. Replace the `raise` below with: fetch fund overview, data-currency
         checks, bank feeds, financial position, member caps/pensions, and
         holdings for `fund_code`, map onto `SMSFFundSnapshotData` and
         `SMSFPortfolioSnapshotData`, return an `SMSFSnapshotData`.
    """
    raise NotImplementedError(
        "No Class/SMSF administration API is integrated in this codebase yet — "
        "see this function's docstring for what to add."
    )
