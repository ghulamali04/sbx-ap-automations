"""
Live Investment Summary data — STUB. No Praemium (or other managed-portfolio
platform) API client exists in this codebase. This module owns everything
except that one call.
"""
from __future__ import annotations

from api.automations.client_review_pack.sections.investment_summary import InvestmentSummaryData


async def fetch_live_investment_summary(account_code: str) -> InvestmentSummaryData:
    """Fetch and shape one managed-portfolio account's investment summary.

    To make this live:
      1. Add `api/automations/praemium/client.py` (or whichever platform
         actually holds these portfolios) — follow `api/automations/zoho/
         client.py`'s shape: thin async wrapper, token from an auth/session
         module, plain dicts back.
      2. Add its credentials to `local.settings.json` (e.g. `PRAEMIUM_*`).
      3. Replace the `raise` below with: fetch the account's movement/
         performance/allocation/holdings for `account_code`, map onto
         `AccountMovement`, `PerformanceRow`, `AssetAllocationEntry`,
         `ExchangeGroup`/`Holding`, return an `InvestmentSummaryData`.
    """
    raise NotImplementedError(
        "No Praemium/managed-portfolio API is integrated in this codebase yet — "
        "see this function's docstring for what to add."
    )
