"""
Live Compliance Lodgement Status data — STUB. No Xero Practice Manager (or
equivalent practice-management platform) API client exists in this codebase.
"""
from __future__ import annotations

from api.automations.client_review_pack.sections.compliance_status import ComplianceStatusData


async def fetch_live_compliance_status(client_name: str) -> ComplianceStatusData:
    """Fetch and shape one client group's ATO lodgement/compliance status.

    To make this live:
      1. Add `api/automations/xpm/client.py` (Xero Practice Manager, or
         whichever platform actually tracks ICA/ITA balances and lodgement
         status) — follow `api/automations/zoho/client.py`'s shape.
      2. Add its credentials to `local.settings.json`.
      3. Replace the `raise` below with: fetch ICA/ITA balances, outstanding
         BAS/IAS counts, and per-year lodgement status for every entity under
         `client_name`, map onto `ComplianceRow`, return a
         `ComplianceStatusData`.
    """
    raise NotImplementedError(
        "No Xero Practice Manager/compliance API is integrated in this codebase yet — "
        "see this function's docstring for what to add."
    )
