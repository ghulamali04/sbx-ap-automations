
from __future__ import annotations

from api.automations.client_review_pack.sections.investment_summary import InvestmentSummaryData


async def fetch_live_investment_summary(account_code: str) -> InvestmentSummaryData:

    raise NotImplementedError(
        "No Praemium/managed-portfolio API is integrated in this codebase yet — "
        "see this function's docstring for what to add."
    )
