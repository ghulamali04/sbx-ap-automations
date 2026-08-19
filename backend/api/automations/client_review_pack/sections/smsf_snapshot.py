"""
SMSF Fund Snapshot + SMSF Portfolio Snapshot sections — sample pack p.17-18: fund
overview, data-currency/processing checks, bank feeds, financial position, member
balances/contribution caps, member pension obligations, then the holdings-level
portfolio snapshot with its own valuation summary.

Both snapshots are built from one `SMSFSnapshotData` input and rendered as one
Section (portfolio snapshot on its own page) since they describe the same fund
as at the same date and are always read together.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from reportlab.platypus import PageBreak, Spacer

from api.lib import pdf_builder as pb
from api.automations.client_review_pack.sections import PORTRAIT_A4, Section


def _tone_for_status(status: str) -> str:
    s = status.strip().lower()
    if s in {"clear", "ok", "complying"}:
        return "good"
    if s in {"review", "feed no longer active"}:
        return "warn"
    return "neutral"


class FundOverview(BaseModel):
    fund_name: str
    abn: str
    compliance_status: str
    gst_status: str
    registered_address: str
    financial_year: str
    trustee_structure: str
    corporate_trustee: str
    latest_trust_deed: str
    adviser: str
    accountant_tax_agent: str
    auditor: str


class StatusCheckRow(BaseModel):
    check: str
    value: str
    status: str  # e.g. "Review", "Clear"
    comment: str


class BankFeedRow(BaseModel):
    feed: str
    status: str  # e.g. "OK", "Feed no longer active"
    last_processed: str


class FinancialPosition(BaseModel):
    total_assets: float
    total_liabilities: float
    net_assets: float
    member_entitlement_accounts: float
    unallocated_member_entitlements: float
    total_member_entitlements: float
    asset_allocation: list[tuple[str, float]] = Field(default_factory=list)


class MemberCapRow(BaseModel):
    member: str
    age: int
    total_balance: float
    accumulation: float
    pension: float
    conc_cap: float
    conc_used: float
    conc_available: float
    non_conc_cap: float
    non_conc_used: float
    non_conc_available: float


class MemberPensionRow(BaseModel):
    member: str
    pension_accounts: str
    minimum_pension: str
    pension_paid_ytd: str
    over_under: str


class SMSFFundSnapshotData(BaseModel):
    as_at: str
    overview: FundOverview
    currency_checks: list[StatusCheckRow] = Field(default_factory=list)
    bank_feeds: list[BankFeedRow] = Field(default_factory=list)
    financial_position: FinancialPosition
    member_caps: list[MemberCapRow] = Field(default_factory=list)
    fund_total_caps: MemberCapRow | None = None
    member_pensions: list[MemberPensionRow] = Field(default_factory=list)


class HoldingRow(BaseModel):
    market_type: str
    holding: str
    quantity: float
    cost: float
    market_price: float
    market_value: float
    unrealised_gain_loss: float
    asset_pool: str


class SMSFPortfolioSnapshotData(BaseModel):
    holdings_as_at: str
    holdings: list[HoldingRow] = Field(default_factory=list)
    total_cost: float
    total_market_value: float
    total_unrealised: float
    asset_allocation: list[tuple[str, float]] = Field(default_factory=list)
    notes: str | None = None


class SMSFSnapshotData(BaseModel):
    fund_snapshot: SMSFFundSnapshotData
    portfolio_snapshot: SMSFPortfolioSnapshotData | None = None


def _overview_columns(o: FundOverview, width: float):
    left = [
        ("SMSF", o.fund_name), ("ABN", o.abn), ("Compliance status", o.compliance_status),
        ("GST status", o.gst_status), ("Registered address", o.registered_address),
        ("Financial year", o.financial_year),
    ]
    right = [
        ("Trustee structure", o.trustee_structure), ("Corporate trustee", o.corporate_trustee),
        ("Latest trust deed", o.latest_trust_deed), ("Adviser", o.adviser),
        ("Accountant / Tax agent", o.accountant_tax_agent), ("Auditor", o.auditor),
    ]
    half = (width - 14) / 2
    return pb.two_column_layout(
        [pb.key_value_table(left, half, value_align="left", label_weight=1.1, value_weight=1.6)],
        [pb.key_value_table(right, half, value_align="left", label_weight=1.1, value_weight=1.6)],
        width,
    )


def _currency_checks_table(rows: list[StatusCheckRow], width: float):
    columns = [
        pb.Column("Check", "check", weight=1.6),
        pb.Column("Value", "value", weight=0.9, align="right"),
        pb.Column("Status", "status", weight=0.8, align="center"),
        pb.Column("Comment", "comment", weight=2.6),
    ]
    table_rows = [{"check": r.check, "value": r.value, "status": r.status, "comment": r.comment} for r in rows]
    tones = {(i, "status"): _tone_for_status(r.status) for i, r in enumerate(rows)}
    return pb.data_table(columns, table_rows, width, tones=tones)


def _bank_feeds_table(rows: list[BankFeedRow], width: float):
    columns = [
        pb.Column("Feed", "feed", weight=2.4),
        pb.Column("Status", "status", weight=1.0, align="center"),
        pb.Column("Last processed", "last_processed", weight=1.0, align="right"),
    ]
    table_rows = [{"feed": r.feed, "status": r.status, "last_processed": r.last_processed} for r in rows]
    tones = {(i, "status"): _tone_for_status(r.status) for i, r in enumerate(rows)}
    return pb.data_table(columns, table_rows, width, tones=tones)


def _financial_position_block(fp: FinancialPosition, width: float):
    left = [
        ("Total assets", pb.fmt_money(fp.total_assets)),
        ("Total liabilities", pb.fmt_money_signed(-abs(fp.total_liabilities))),
        ("Net assets", pb.fmt_money(fp.net_assets)),
        ("Member entitlement accounts", pb.fmt_money(fp.member_entitlement_accounts)),
        ("Unallocated member entitlements", pb.fmt_money(fp.unallocated_member_entitlements)),
        ("Total member entitlements", pb.fmt_money(fp.total_member_entitlements)),
    ]
    right = [(label, pb.fmt_pct(pct)) for label, pct in fp.asset_allocation]
    half = (width - 14) / 2
    return pb.two_column_layout(
        [pb.key_value_table(left, half, bold_rows={2, 5}, rule_above={2, 5})],
        [pb.key_value_table(right, half)],
        width,
    )


def _member_caps_table(rows: list[MemberCapRow], total: MemberCapRow | None, width: float):
    columns = [
        pb.Column("Member", "member", weight=1.3),
        pb.Column("Age", "age", weight=0.5, align="right"),
        pb.Column("Total ($)", "total_balance", weight=1.0, align="right"),
        pb.Column("Accum. ($)", "accumulation", weight=1.0, align="right"),
        pb.Column("Pension ($)", "pension", weight=0.9, align="right"),
        pb.Column("Conc. cap ($)", "conc_cap", weight=0.9, align="right"),
        pb.Column("Conc. used ($)", "conc_used", weight=0.9, align="right"),
        pb.Column("Conc. avail. ($)", "conc_available", weight=0.9, align="right"),
        pb.Column("Non-conc. avail. ($)", "non_conc_available", weight=1.0, align="right"),
    ]
    def _row(m: MemberCapRow) -> dict:
        return {
            "member": m.member, "age": str(m.age),
            "total_balance": pb.fmt_money(m.total_balance, decimals=0),
            "accumulation": pb.fmt_money(m.accumulation, decimals=0),
            "pension": pb.fmt_money(m.pension, decimals=0) if m.pension else "-",
            "conc_cap": pb.fmt_money(m.conc_cap, decimals=0),
            "conc_used": pb.fmt_money(m.conc_used, decimals=0) if m.conc_used else "-",
            "conc_available": pb.fmt_money(m.conc_available, decimals=0),
            "non_conc_available": pb.fmt_money(m.non_conc_available, decimals=0),
        }
    table_rows = [_row(m) for m in rows]
    row_bold = set()
    if total is not None:
        table_rows.append(_row(total) | {"member": "Fund total"})
        row_bold = {len(table_rows) - 1}
    return pb.data_table(columns, table_rows, width, row_bold=row_bold)


def _member_pensions_table(rows: list[MemberPensionRow], width: float):
    columns = [
        pb.Column("Member", "member", weight=1.4),
        pb.Column("Pension accounts", "pension_accounts", weight=1.4, align="right"),
        pb.Column("Minimum pension ($)", "minimum_pension", weight=1.2, align="right"),
        pb.Column("Pension paid YTD ($)", "pension_paid_ytd", weight=1.2, align="right"),
        pb.Column("Over/(under) ($)", "over_under", weight=1.1, align="right"),
    ]
    table_rows = [
        {
            "member": r.member, "pension_accounts": r.pension_accounts, "minimum_pension": r.minimum_pension,
            "pension_paid_ytd": r.pension_paid_ytd, "over_under": r.over_under,
        }
        for r in rows
    ]
    return pb.data_table(columns, table_rows, width)


def _holdings_table(holdings: list[HoldingRow], total_cost: float, total_value: float, total_gain: float, width: float):
    columns = [
        pb.Column("Market type", "market_type", weight=1.1),
        pb.Column("Holding", "holding", weight=2.4),
        pb.Column("Quantity", "quantity", weight=1.0, align="right"),
        pb.Column("Cost ($)", "cost", weight=1.1, align="right"),
        pb.Column("Market value ($)", "market_value", weight=1.2, align="right"),
        pb.Column("Unrealised gain/(loss) ($)", "gain", weight=1.3, align="right"),
        pb.Column("Asset pool", "asset_pool", weight=1.0),
    ]
    rows = [
        {
            "market_type": h.market_type, "holding": h.holding,
            "quantity": pb.fmt_number(h.quantity, decimals=2),
            "cost": pb.fmt_money(h.cost), "market_value": pb.fmt_money(h.market_value),
            "gain": pb.fmt_money_signed(h.unrealised_gain_loss) if h.unrealised_gain_loss else "-",
            "asset_pool": h.asset_pool,
        }
        for h in holdings
    ]
    rows.append({
        "market_type": "", "holding": "Total portfolio", "quantity": "",
        "cost": pb.fmt_money(total_cost), "market_value": pb.fmt_money(total_value),
        "gain": pb.fmt_money_signed(total_gain), "asset_pool": "",
    })
    return pb.data_table(columns, rows, width, row_bold={len(rows) - 1})


def build_smsf_snapshot_section(data: SMSFSnapshotData) -> Section:
    fs = data.fund_snapshot
    section = Section(key="smsf_snapshot", title="SMSF Fund Snapshot", page_size=PORTRAIT_A4)
    width = section.usable_width

    section.story += pb.masthead_block(
        "SMSF Fund Snapshot",
        meta=[f"<b>{fs.overview.fund_name}</b>"],
        subtitle=f"Prepared by Advisory Partners · As at {fs.as_at}",
    )
    section.story.append(pb.section_heading("Fund overview"))
    section.story.append(_overview_columns(fs.overview, width))
    section.story.append(Spacer(1, 12))

    if fs.currency_checks:
        section.story.append(pb.section_heading("Data currency & processing status"))
        section.story.append(_currency_checks_table(fs.currency_checks, width))
        section.story.append(Spacer(1, 12))

    if fs.bank_feeds:
        section.story.append(pb.section_heading("Bank & data feeds"))
        section.story.append(_bank_feeds_table(fs.bank_feeds, width))
        section.story.append(Spacer(1, 12))

    section.story.append(pb.section_heading(f"Financial position (as at {fs.as_at})"))
    section.story.append(_financial_position_block(fs.financial_position, width))
    section.story.append(Spacer(1, 12))

    if fs.member_caps:
        section.story.append(pb.section_heading("Member summary — balances & contribution caps"))
        section.story.append(_member_caps_table(fs.member_caps, fs.fund_total_caps, width))
        section.story.append(Spacer(1, 8))

    if fs.member_pensions:
        section.story.append(pb.section_heading("Member pension obligations"))
        section.story.append(_member_pensions_table(fs.member_pensions, width))

    ps = data.portfolio_snapshot
    if ps:
        section.story.append(PageBreak())
        section.story += pb.masthead_block(
            "SMSF Portfolio Snapshot",
            meta=[f"<b>{fs.overview.fund_name}</b>"],
            subtitle=f"Holdings as at {ps.holdings_as_at}",
        )
        section.story.append(pb.section_heading("Portfolio holdings"))
        section.story.append(_holdings_table(ps.holdings, ps.total_cost, ps.total_market_value, ps.total_unrealised, width))
        section.story.append(Spacer(1, 12))

        section.story.append(pb.section_heading("Valuation summary"))
        half = (width - 14) / 2
        left = pb.key_value_table([
            ("Total cost base", pb.fmt_money(ps.total_cost)),
            ("Total market value", pb.fmt_money(ps.total_market_value)),
            ("Total unrealised gain/(loss)", pb.fmt_money_signed(ps.total_unrealised)),
        ], half, bold_rows={2})
        right = pb.key_value_table([(label, pb.fmt_pct(pct)) for label, pct in ps.asset_allocation], half)
        section.story.append(pb.two_column_layout([left], [right], width))

        if ps.notes:
            section.story.append(pb.note(ps.notes))

    return section
