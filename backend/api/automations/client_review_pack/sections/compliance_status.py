"""
Compliance Lodgement Status section — the ATO integrated-client-account and
lodgement-status register (sample pack p.24): ICA/ITA balances, outstanding
BAS/IAS counts, and per-year lodgement status by entity in the client's group.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from api.lib import pdf_builder as pb
from api.automations.client_review_pack.sections import LANDSCAPE_A4, Section


def _tone(status: str) -> str:
    s = status.strip().lower()
    if s == "received":
        return "good"
    if s == "not received":
        return "bad"
    return "neutral"


class ComplianceRow(BaseModel):
    entity: str
    ica_debit: float = 0.0
    ica_credit: float = 0.0
    ita_debit: float = 0.0
    ita_credit: float = 0.0
    bas_ias_outstanding: int | None = None
    year_status: dict[str, str] = Field(default_factory=dict)  # {"2023": "Received", ...}
    fbt_return: str = "-"


class ComplianceStatusData(BaseModel):
    client_name: str
    generated_on: str
    last_updated: str
    years: list[str]  # column order, e.g. ["2023", "2024", "2025", "2026"]
    rows: list[ComplianceRow] = Field(default_factory=list)


def _columns(years: list[str]) -> list[pb.Column]:
    columns = [
        pb.Column("Client", "entity", weight=1.8),
        pb.Column("ICA Debit ($)", "ica_debit", weight=1.0, align="right"),
        pb.Column("ICA Credit ($)", "ica_credit", weight=1.0, align="right"),
        pb.Column("ITA Debit ($)", "ita_debit", weight=1.0, align="right"),
        pb.Column("ITA Credit ($)", "ita_credit", weight=1.0, align="right"),
        pb.Column("BAS/IAS Outstanding", "bas_ias_outstanding", weight=1.0, align="right"),
    ]
    columns += [pb.Column(f"{y} Status", f"status_{y}", weight=0.9, align="center") for y in years]
    columns.append(pb.Column("FBT Return", "fbt_return", weight=0.9, align="center"))
    return columns


def build_compliance_status_section(data: ComplianceStatusData) -> Section:
    title = f"{data.client_name} — Compliance Lodgement Status"
    section = Section(key="compliance_status", title=title, page_size=LANDSCAPE_A4)
    width = section.usable_width
    section.story += pb.masthead_block(
        title,
        meta=[f"<b>Last updated:</b> {data.last_updated}", f"<b>Generated on:</b> {data.generated_on}"],
        subtitle="ICA / ITA balances, outstanding BAS/IAS, and FBT/annual lodgement status by entity",
    )

    columns = _columns(data.years)
    rows: list[dict] = []
    tones: dict[tuple[int, str], str] = {}
    for i, r in enumerate(data.rows):
        row = {
            "entity": r.entity, "ica_debit": pb.fmt_money(r.ica_debit), "ica_credit": pb.fmt_money(r.ica_credit),
            "ita_debit": pb.fmt_money(r.ita_debit), "ita_credit": pb.fmt_money(r.ita_credit),
            "bas_ias_outstanding": str(r.bas_ias_outstanding) if r.bas_ias_outstanding is not None else "-",
        }
        for y in data.years:
            status = r.year_status.get(y, "-")
            row[f"status_{y}"] = status
            tones[(i, f"status_{y}")] = _tone(status)
        row["fbt_return"] = r.fbt_return
        tones[(i, "fbt_return")] = _tone(r.fbt_return)
        rows.append(row)

    section.story.append(pb.data_table(columns, rows, width, tones=tones))
    return section
