"""
Personal Insurance Summary & Risk Review section — sample pack p.19-20: household
premium summary, a per-policy risk register (framework-scored), the insurer
watchlist behind those scores, and the scoring-matrix/notes appendix.

Landscape A4 — the policy risk register runs to eleven columns including a long
free-text rationale column.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from reportlab.platypus import Spacer

from api.lib import pdf_builder as pb
from api.automations.client_review_pack.sections import LANDSCAPE_A4, Section


def _risk_tone(rating: str) -> str:
    r = rating.lower()
    if "high" in r or "immediate" in r:
        return "bad"
    if "review" in r:
        return "warn"
    if "low" in r or "monitor" in r:
        return "good"
    return "neutral"


class HouseholdInsuranceRow(BaseModel):
    client: str
    age: int
    review_month: str
    service_date: str
    policies: int
    annual_premium: float
    insurers: str
    watchlist_insurer: str  # e.g. "TAL", or "None"
    exclusions_loadings: str


class PolicyRiskRow(BaseModel):
    client: str
    policy: str
    type: str
    insurer: str
    owner: str
    sum_insured: str
    annual_premium: float
    watchlist: bool
    risk_score: int
    risk_rating: str  # e.g. "Low–moderate", "Review ≤6 months", "High priority"
    review_summary: str


class InsurerWatchlistRow(BaseModel):
    provider: str
    on_watchlist: bool
    basis: str
    suggested_response: str


class ScoringMatrixRow(BaseModel):
    score_range: str
    rating: str
    recommended_action: str


class InsuranceReviewData(BaseModel):
    household_name: str
    adviser: str
    as_at: str
    household_summary: list[HouseholdInsuranceRow] = Field(default_factory=list)
    household_total_policies: int
    household_total_premium: float
    policy_risk_register: list[PolicyRiskRow] = Field(default_factory=list)
    insurer_watchlist: list[InsurerWatchlistRow] = Field(default_factory=list)
    scoring_matrix: list[ScoringMatrixRow] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _household_summary_table(data: InsuranceReviewData, width: float):
    columns = [
        pb.Column("Client", "client", weight=1.0),
        pb.Column("Age", "age", weight=0.5, align="right"),
        pb.Column("Review month", "review_month", weight=0.9),
        pb.Column("Service (OSA) date", "service_date", weight=1.0),
        pb.Column("Policies", "policies", weight=0.7, align="right"),
        pb.Column("Annual premium ($)", "annual_premium", weight=1.1, align="right"),
        pb.Column("Insurers", "insurers", weight=1.6),
        pb.Column("Watchlist insurer", "watchlist_insurer", weight=1.1),
        pb.Column("Exclusions / loadings", "exclusions_loadings", weight=1.2),
    ]
    rows = [
        {
            "client": r.client, "age": str(r.age), "review_month": r.review_month,
            "service_date": r.service_date, "policies": str(r.policies),
            "annual_premium": pb.fmt_money(r.annual_premium), "insurers": r.insurers,
            "watchlist_insurer": r.watchlist_insurer, "exclusions_loadings": r.exclusions_loadings,
        }
        for r in data.household_summary
    ]
    tones = {(i, "watchlist_insurer"): ("bad" if r.watchlist_insurer.lower() not in ("none", "—", "") else "neutral")
             for i, r in enumerate(data.household_summary)}
    rows.append({
        "client": "Household total", "age": "", "review_month": "", "service_date": "",
        "policies": str(data.household_total_policies), "annual_premium": pb.fmt_money(data.household_total_premium),
        "insurers": "", "watchlist_insurer": "", "exclusions_loadings": "",
    })
    return pb.data_table(columns, rows, width, tones=tones, row_bold={len(rows) - 1})


def _policy_risk_table(rows: list[PolicyRiskRow], width: float):
    columns = [
        pb.Column("Client", "client", weight=0.9),
        pb.Column("Policy", "policy", weight=0.6),
        pb.Column("Type", "type", weight=1.1),
        pb.Column("Insurer", "insurer", weight=0.8),
        pb.Column("Owner", "owner", weight=1.0),
        pb.Column("Sum insured", "sum_insured", weight=1.3),
        pb.Column("Annual premium ($)", "annual_premium", weight=1.0, align="right"),
        pb.Column("Watch-list", "watchlist", weight=0.7, align="center"),
        pb.Column("Risk score", "risk_score", weight=0.7, align="right"),
        pb.Column("Risk rating", "risk_rating", weight=1.1),
        pb.Column("Review summary & rationale", "review_summary", weight=4.2),
    ]
    table_rows = [
        {
            "client": r.client, "policy": r.policy, "type": r.type, "insurer": r.insurer, "owner": r.owner,
            "sum_insured": r.sum_insured, "annual_premium": pb.fmt_money(r.annual_premium),
            "watchlist": "Yes" if r.watchlist else "No", "risk_score": str(r.risk_score),
            "risk_rating": r.risk_rating, "review_summary": r.review_summary,
        }
        for r in rows
    ]
    tones = {}
    for i, r in enumerate(rows):
        tones[(i, "risk_rating")] = _risk_tone(r.risk_rating)
        tones[(i, "watchlist")] = "bad" if r.watchlist else "neutral"
    return pb.data_table(columns, table_rows, width, band_key="client", tones=tones)


def _insurer_watchlist_table(rows: list[InsurerWatchlistRow], width: float):
    columns = [
        pb.Column("Provider", "provider", weight=1.0),
        pb.Column("On watchlist", "on_watchlist", weight=0.9, align="center"),
        pb.Column("Basis for enhanced review", "basis", weight=3.2),
        pb.Column("Suggested review response", "suggested_response", weight=3.2),
    ]
    table_rows = [
        {"provider": r.provider, "on_watchlist": "Yes" if r.on_watchlist else "No",
         "basis": r.basis, "suggested_response": r.suggested_response}
        for r in rows
    ]
    tones = {(i, "on_watchlist"): ("bad" if r.on_watchlist else "good") for i, r in enumerate(rows)}
    return pb.data_table(columns, table_rows, width, tones=tones)


def _scoring_matrix_table(rows: list[ScoringMatrixRow], width: float):
    columns = [
        pb.Column("Score", "score_range", weight=0.8),
        pb.Column("Rating", "rating", weight=1.2),
        pb.Column("Recommended action", "recommended_action", weight=4.0),
    ]
    table_rows = [{"score_range": r.score_range, "rating": r.rating, "recommended_action": r.recommended_action} for r in rows]
    tones = {(i, "rating"): _risk_tone(r.rating) for i, r in enumerate(rows)}
    return pb.data_table(columns, table_rows, width, tones=tones)


def build_insurance_review_section(data: InsuranceReviewData) -> Section:
    section = Section(key="insurance_review", title="Personal Insurance Summary & Risk Review", page_size=LANDSCAPE_A4)
    width = section.usable_width

    section.story += pb.masthead_block(
        "Personal Insurance Summary & Risk Review",
        meta=[f"<b>{data.household_name}</b>", f"<b>Adviser:</b> {data.adviser}", "Insurance-only clients"],
        subtitle=f"Prepared by Advisory Partners · As at {data.as_at}",
    )

    if data.household_summary:
        section.story.append(pb.section_heading("Household summary"))
        section.story.append(_household_summary_table(data, width))
        section.story.append(Spacer(1, 12))

    if data.policy_risk_register:
        section.story.append(pb.section_heading("Policy risk register — risk rating & review summary per policy"))
        section.story.append(_policy_risk_table(data.policy_risk_register, width))
        section.story.append(Spacer(1, 12))

    if data.insurer_watchlist:
        section.story.append(pb.section_heading("Insurer watchlist — relevant providers"))
        section.story.append(_insurer_watchlist_table(data.insurer_watchlist, width))
        section.story.append(Spacer(1, 12))

    if data.scoring_matrix:
        section.story.append(pb.section_heading("Framework scoring matrix"))
        section.story.append(_scoring_matrix_table(data.scoring_matrix, width))
        section.story.append(Spacer(1, 10))

    if data.notes:
        section.story.append(pb.subsection_heading("Notes & caveats"))
        for line in data.notes:
            section.story.append(pb.note(f"• {line}"))

    return section
