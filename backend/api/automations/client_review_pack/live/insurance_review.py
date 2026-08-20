"""
Live Personal Insurance Summary & Risk Review data — STUB. No insurer/policy
administration API client exists in this codebase, and the risk-scoring
framework itself (§4 scoring matrix, watchlist basis text) is currently
business logic that lives only in the sample data — it needs a real source
(a documented framework, likely still authored by an adviser) as much as the
policy data does.
"""
from __future__ import annotations

from api.automations.client_review_pack.sections.insurance_review import InsuranceReviewData


async def fetch_live_insurance_review(household_name: str) -> InsuranceReviewData:
    """Fetch and shape one household's insurance summary + risk review.

    To make this live:
      1. Add a client for wherever policy data actually lives (an insurer
         portal API, or more likely the practice's CRM/policy register) —
         follow `api/automations/zoho/client.py`'s shape.
      2. Add its credentials to `local.settings.json`.
      3. Decide where the risk-scoring framework (watchlist providers, score
         thresholds, review-summary rationale) is authored and fetched from —
         this isn't in any system today.
      4. Replace the `raise` below with: fetch policies for `household_name`,
         map onto `HouseholdInsuranceRow`/`PolicyRiskRow`, apply the scoring
         framework, return an `InsuranceReviewData`.
    """
    raise NotImplementedError(
        "No insurance/policy API is integrated in this codebase yet — "
        "see this function's docstring for what to add."
    )
