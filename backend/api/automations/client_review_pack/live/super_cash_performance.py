"""
Live Cash & Performance (AustralianSuper-style) data — STUB. No AustralianSuper
(or equivalent super-fund platform) API client exists in this codebase.
"""
from __future__ import annotations

from api.automations.client_review_pack.sections.super_cash_performance import SuperReportData


async def fetch_live_super_cash_performance(head_client_id: str) -> SuperReportData:
    """Fetch and shape one head client's household super cash/performance report.

    To make this live:
      1. Add `api/automations/australiansuper/client.py` (or whichever
         platform actually holds these accounts) — follow `api/automations/
         zoho/client.py`'s shape.
      2. Add its credentials to `local.settings.json`.
      3. Replace the `raise` below with: fetch the linked household accounts
         for `head_client_id`, map onto `HouseholdSummary`,
         `MemberPerformanceSummary`, `FeesCharges`, `CGTOverlay`,
         `CashTransactionLedger`, `MemberPortfolioValuation`, etc. (all
         optional sub-reports on `SuperReportData` — supply what the source
         has), return a `SuperReportData`.
    """
    raise NotImplementedError(
        "No AustralianSuper/super-fund API is integrated in this codebase yet — "
        "see this function's docstring for what to add."
    )
