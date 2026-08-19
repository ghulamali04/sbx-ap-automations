"""
Cash & Performance (AustralianSuper-style) section — sample pack p.10-16: a
household account summary plus, per member, a performance waterfall, fees &
charges, an unrealised-CGT overlay, a cash transaction ledger, a full portfolio
valuation, and a shares/ETF performance-since-inception report.

The source is several separate report exports stitched together (the sample
pack's own footer note calls this out), so this module treats each as an
optional, independently-suppliable sub-report keyed by member — a household with
one member and no cash-ledger detail renders just as well as the full three-member
sample.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from reportlab.platypus import PageBreak, Spacer

from api.lib import pdf_builder as pb
from api.automations.client_review_pack.sections import PORTRAIT_A4, Section


class HouseholdMember(BaseModel):
    name: str
    member_no: str
    product: str
    cash: float
    investments: float
    total_value: float
    return_display: str  # e.g. "(1.0%)" or "n/a" — kept as display text; the source mixes both


class HouseholdSummary(BaseModel):
    head_client: str
    accounts_description: str
    reporting_period: str
    date_prepared: str
    prepared_by: str
    members: list[HouseholdMember] = Field(default_factory=list)
    total_cash: float
    total_investments: float
    total_value: float


class WaterfallRow(BaseModel):
    label: str
    amount: float


class MemberPerformanceSummary(BaseModel):
    member_name: str
    product: str
    rows: list[WaterfallRow]  # e.g. Value at start date, Less pension payments, ...
    adjusted_value: float
    value_as_at: float
    movement: float
    return_since_inception_display: str


class FeeLine(BaseModel):
    category: str
    amount: float


class FeesCharges(BaseModel):
    member_name: str
    period_label: str
    lines: list[FeeLine]
    total: float


class CGTLine(BaseModel):
    description: str
    long_gains: float | None = None


class CGTOverlay(BaseModel):
    member_name: str
    lines: list[CGTLine]
    net_total: float
    cgt_liability_total: float


class CashTransaction(BaseModel):
    effective_date: str
    description: str
    amount: float | None = None
    balance: float


class CashTransactionLedger(BaseModel):
    member_name: str
    member_no: str
    product_type: str
    reporting_period: str
    opening_balance: float
    transactions: list[CashTransaction] = Field(default_factory=list)
    closing_balance: float


class ValuationRow(BaseModel):
    description: str
    quantity: float | None = None
    price: float | None = None
    value: float


class MemberPortfolioValuation(BaseModel):
    member_name: str
    member_no: str
    product_type: str
    reporting_date: str
    transaction_account_rows: list[ValuationRow] = Field(default_factory=list)
    transaction_account_total: float
    term_deposit_rows: list[ValuationRow] = Field(default_factory=list)
    term_deposit_total: float
    shares_etf_rows: list[ValuationRow] = Field(default_factory=list)
    shares_etf_total: float
    investment_option_rows: list[ValuationRow] = Field(default_factory=list)
    investment_option_total: float
    total_portfolio_value: float


class AssetClassValue(BaseModel):
    asset_class: str
    value: float


class LinkedAccountAssetSummary(BaseModel):
    member_name: str
    member_no: str
    entries: list[AssetClassValue]
    total: float


class SharesPerformanceRow(BaseModel):
    investment: str
    investment_transactions: float | None = None
    closing_value: float
    capital_growth: float | None = None
    income: float | None = None
    total_return: float
    total_return_pct: float


class SharesPerformanceReport(BaseModel):
    member_name: str
    member_no: str
    product_type: str
    reporting_period: str
    rows: list[SharesPerformanceRow]
    total: SharesPerformanceRow


class SuperReportData(BaseModel):
    household: HouseholdSummary | None = None
    performance_summaries: list[MemberPerformanceSummary] = Field(default_factory=list)
    fees_charges: list[FeesCharges] = Field(default_factory=list)
    cgt_overlays: list[CGTOverlay] = Field(default_factory=list)
    cash_ledgers: list[CashTransactionLedger] = Field(default_factory=list)
    portfolio_valuations: list[MemberPortfolioValuation] = Field(default_factory=list)
    linked_account_summaries: list[LinkedAccountAssetSummary] = Field(default_factory=list)
    shares_performance_reports: list[SharesPerformanceReport] = Field(default_factory=list)


def _header(title: str, meta: list[str], subtitle: str | None = None) -> list:
    return pb.masthead_block(title, meta=meta, subtitle=subtitle)


def _household_block(h: HouseholdSummary, width: float) -> list:
    columns = [
        pb.Column("Member", "name", weight=1.4),
        pb.Column("Member no.", "member_no", weight=1.0),
        pb.Column("Product", "product", weight=1.4),
        pb.Column("Cash ($)", "cash", weight=1.0, align="right"),
        pb.Column("Investments ($)", "investments", weight=1.2, align="right"),
        pb.Column("Total value ($)", "total_value", weight=1.2, align="right"),
        pb.Column("Return", "return_display", weight=0.9, align="right"),
    ]
    rows = [
        {
            "name": m.name, "member_no": m.member_no, "product": m.product,
            "cash": pb.fmt_money(m.cash), "investments": pb.fmt_money(m.investments),
            "total_value": pb.fmt_money(m.total_value), "return_display": m.return_display,
        }
        for m in h.members
    ]
    rows.append({
        "name": "Household total", "member_no": "", "product": "",
        "cash": pb.fmt_money(h.total_cash), "investments": pb.fmt_money(h.total_investments),
        "total_value": pb.fmt_money(h.total_value), "return_display": "",
    })
    return [
        pb.section_heading("Household account summary"),
        pb.data_table(columns, rows, width, row_bold={len(rows) - 1}),
        pb.note("A head client may hold 1–3 linked accounts; each account also has its own detailed sections."),
    ]


def _performance_summary_block(s: MemberPerformanceSummary, width: float) -> list:
    rows = [(r.label, pb.fmt_money_signed(r.amount)) for r in s.rows]
    rows.append(("Adjusted value", pb.fmt_money(s.adjusted_value)))
    rows.append(("Value as at reporting date", pb.fmt_money(s.value_as_at)))
    rows.append(("Movement in investment value", pb.fmt_money_signed(s.movement)))
    rows.append(("Return since inception (net of pension payments and fees)", s.return_since_inception_display))
    bold = {len(rows) - 4, len(rows) - 2, len(rows) - 1}
    return [
        pb.subsection_heading(f"Performance summary — {s.member_name} ({s.product})"),
        pb.key_value_table(rows, width, bold_rows=bold, rule_above={len(rows) - 4}),
    ]


def _fees_block(f: FeesCharges, width: float) -> list:
    rows = [(line.category, pb.fmt_money(line.amount)) for line in f.lines]
    rows.append(("Total fees & charges", pb.fmt_money(f.total)))
    return [
        pb.subsection_heading(f"Fees & charges — {f.member_name} ({f.period_label})"),
        pb.key_value_table(rows, width, bold_rows={len(rows) - 1}, rule_above={len(rows) - 1}),
    ]


def _cgt_block(c: CGTOverlay, width: float) -> list:
    rows = [(line.description, pb.fmt_money_signed(line.long_gains)) for line in c.lines]
    rows.append(("Net unrealised gains", pb.fmt_money(c.net_total)))
    rows.append(("CGT liability", pb.fmt_money(c.cgt_liability_total)))
    return [
        pb.subsection_heading(f"Unrealised capital gains tax — illustrative tax overlay ({c.member_name})"),
        pb.key_value_table(rows, width, bold_rows={len(rows) - 2, len(rows) - 1}, rule_above={len(rows) - 2}),
    ]


def _meta_line(member_name: str, member_no: str, product_type: str, period: str):
    return pb.p(
        f"Member: {member_name}   ·   Member no.: {member_no}   ·   Product: {product_type}   ·   {period}",
        pb.CELL_MUTED,
    )


def _cash_ledger_block(ledger: CashTransactionLedger, width: float) -> list:
    columns = [
        pb.Column("Effective date", "date", weight=1.0),
        pb.Column("Description", "description", weight=3.4),
        pb.Column("Amount ($)", "amount", weight=1.1, align="right"),
        pb.Column("Balance ($)", "balance", weight=1.1, align="right"),
    ]
    rows = [{"date": "", "description": "Opening balance", "amount": "", "balance": pb.fmt_money(ledger.opening_balance)}]
    for t in ledger.transactions:
        rows.append({
            "date": t.effective_date, "description": t.description,
            "amount": pb.fmt_money_signed(t.amount) if t.amount is not None else "",
            "balance": pb.fmt_money(t.balance),
        })
    rows.append({"date": "", "description": "Closing balance", "amount": "", "balance": pb.fmt_money(ledger.closing_balance)})
    return [
        pb.section_heading("Cash Transaction Report"),
        _meta_line(ledger.member_name, ledger.member_no, ledger.product_type, ledger.reporting_period),
        pb.data_table(columns, rows, width, row_bold={0, len(rows) - 1}),
        pb.note(
            "Shares/ETF sales and purchases are net of any brokerage, GST and Reduced Input Tax Credits (RITC). "
            "Excludes income due but not received and accrued interest not yet paid. Does not include pending orders."
        ),
    ]


def _valuation_rows_table(rows: list[ValuationRow], total: float, width: float, total_label: str):
    columns = [
        pb.Column("Description", "description", weight=3.2),
        pb.Column("Quantity", "quantity", weight=1.0, align="right"),
        pb.Column("Price ($)", "price", weight=1.0, align="right"),
        pb.Column("Value ($)", "value", weight=1.1, align="right"),
    ]
    table_rows = [
        {
            "description": r.description,
            "quantity": pb.fmt_number(r.quantity, decimals=2) if r.quantity is not None else "",
            "price": pb.fmt_money(r.price) if r.price is not None else "",
            "value": pb.fmt_money(r.value),
        }
        for r in rows
    ]
    table_rows.append({"description": total_label, "quantity": "", "price": "", "value": pb.fmt_money(total)})
    return pb.data_table(columns, table_rows, width, row_bold={len(table_rows) - 1})


def _portfolio_valuation_block(v: MemberPortfolioValuation, width: float) -> list:
    story: list = [
        pb.section_heading("Portfolio Valuation"),
        _meta_line(v.member_name, v.member_no, v.product_type, v.reporting_date),
    ]
    if v.transaction_account_rows:
        story.append(pb.subsection_heading("Transaction account"))
        story.append(_valuation_rows_table(v.transaction_account_rows, v.transaction_account_total, width, "Total"))
        story.append(Spacer(1, 8))
    if v.term_deposit_rows:
        story.append(pb.subsection_heading("Term deposits"))
        story.append(_valuation_rows_table(v.term_deposit_rows, v.term_deposit_total, width, "Total"))
        story.append(Spacer(1, 8))
    if v.shares_etf_rows:
        story.append(pb.subsection_heading("Shares & ETFs"))
        story.append(_valuation_rows_table(v.shares_etf_rows, v.shares_etf_total, width, "Total"))
        story.append(Spacer(1, 8))
    if v.investment_option_rows:
        story.append(pb.subsection_heading("Investment options"))
        story.append(_valuation_rows_table(v.investment_option_rows, v.investment_option_total, width, "Total"))
        story.append(Spacer(1, 8))
    story.append(pb.key_value_table(
        [("TOTAL PORTFOLIO VALUE", pb.fmt_money(v.total_portfolio_value))], width, bold_rows={0},
    ))
    return story


def _linked_account_block(s: LinkedAccountAssetSummary, width: float) -> list:
    columns = [pb.Column("Asset class", "asset_class", weight=3), pb.Column("Portfolio value ($)", "value", weight=1.2, align="right")]
    rows = [{"asset_class": e.asset_class, "value": pb.fmt_money(e.value)} for e in s.entries]
    rows.append({"asset_class": "TOTAL PORTFOLIO VALUE", "value": pb.fmt_money(s.total)})
    return [
        pb.section_heading(f"Linked account — {s.member_name} ({s.member_no}) · summary by asset class"),
        pb.data_table(columns, rows, width, row_bold={len(rows) - 1}),
    ]


def _shares_performance_block(r: SharesPerformanceReport, width: float) -> list:
    columns = [
        pb.Column("Investment", "investment", weight=2.6),
        pb.Column("Investment transactions ($)", "txns", weight=1.2, align="right"),
        pb.Column("Closing value ($)", "closing", weight=1.1, align="right"),
        pb.Column("Capital growth ($)", "growth", weight=1.1, align="right"),
        pb.Column("Income ($)", "income", weight=0.9, align="right"),
        pb.Column("Total return ($)", "total_return", weight=1.0, align="right"),
        pb.Column("Total return (%)", "total_return_pct", weight=0.9, align="right"),
    ]
    rows = [
        {
            "investment": row.investment,
            "txns": pb.fmt_money(row.investment_transactions) if row.investment_transactions is not None else "",
            "closing": pb.fmt_money(row.closing_value),
            "growth": pb.fmt_money_signed(row.capital_growth) if row.capital_growth is not None else "",
            "income": pb.fmt_money(row.income) if row.income is not None else "",
            "total_return": pb.fmt_money_signed(row.total_return),
            "total_return_pct": pb.fmt_pct(row.total_return_pct),
        }
        for row in r.rows
    ]
    t = r.total
    rows.append({
        "investment": "Total",
        "txns": pb.fmt_money(t.investment_transactions) if t.investment_transactions is not None else "",
        "closing": pb.fmt_money(t.closing_value),
        "growth": pb.fmt_money_signed(t.capital_growth) if t.capital_growth is not None else "",
        "income": pb.fmt_money(t.income) if t.income is not None else "",
        "total_return": pb.fmt_money_signed(t.total_return),
        "total_return_pct": pb.fmt_pct(t.total_return_pct),
    })
    return [
        pb.section_heading("Performance Report"),
        _meta_line(r.member_name, r.member_no, r.product_type, r.reporting_period),
        pb.subsection_heading("Shares & ETFs — return since inception"),
        pb.data_table(columns, rows, width, row_bold={len(rows) - 1}),
        pb.note(
            "Includes listed securities and/or unitised investments; cash, term deposits and investment options are "
            "excluded. Performance uses an Internal Rate of Return (IRR) methodology. Calculations do not take into "
            "account accrued fees or unrealised tax."
        ),
    ]


def build_super_cash_performance_section(data: SuperReportData) -> Section:
    section = Section(key="super_cash_performance", title="Cash & Performance Report", page_size=PORTRAIT_A4)
    width = section.usable_width
    first_page = True

    def _new_page(title: str, meta: list[str], subtitle: str | None = None) -> None:
        nonlocal first_page
        if not first_page:
            section.story.append(PageBreak())
        section.story += _header(title, meta, subtitle)
        first_page = False

    if data.household:
        h = data.household
        _new_page("Cash & Performance Report", meta=[
            f"<b>Head client:</b> {h.head_client}",
            f"<b>Accounts:</b> {h.accounts_description}",
            f"<b>Reporting period:</b> {h.reporting_period}",
            f"<b>Date prepared:</b> {h.date_prepared}",
            f"<b>Prepared by:</b> {h.prepared_by}",
        ])
        section.story += _household_block(h, width)
        section.story.append(Spacer(1, 12))

    for s in data.performance_summaries:
        if first_page:
            _new_page("Cash & Performance Report", meta=[f"<b>Member:</b> {s.member_name}"])
        section.story += _performance_summary_block(s, width)
        section.story.append(Spacer(1, 10))

    for f in data.fees_charges:
        section.story += _fees_block(f, width)
        section.story.append(Spacer(1, 10))

    for c in data.cgt_overlays:
        section.story += _cgt_block(c, width)
        section.story.append(Spacer(1, 10))

    for ledger in data.cash_ledgers:
        _new_page("Cash Transaction Report", meta=[])
        section.story += _cash_ledger_block(ledger, width)

    for v in data.portfolio_valuations:
        _new_page("Portfolio Valuation", meta=[])
        section.story += _portfolio_valuation_block(v, width)

    for s in data.linked_account_summaries:
        _new_page("Portfolio Valuation", meta=[])
        section.story += _linked_account_block(s, width)

    for r in data.shares_performance_reports:
        _new_page("Performance Report", meta=[])
        section.story += _shares_performance_block(r, width)

    return section
