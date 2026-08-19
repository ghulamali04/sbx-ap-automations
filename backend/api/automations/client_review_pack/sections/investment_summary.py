"""
Investment Summary section — managed-portfolio report (sample pack p.3-9): account
movement, performance vs benchmark, asset allocation, and the full holdings
register by exchange. Modelled on the Advisory Partners High Growth Model sample;
generic across any single-portfolio investment report of that shape (Praemium or
otherwise).

Landscape A4 throughout, including the summary page, so the summary and the
wide holdings register share one page size within this section.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pydantic import BaseModel, Field
from reportlab.platypus import Image, PageBreak, Spacer

from api.lib import pdf_builder as pb
from api.automations.client_review_pack.sections import LANDSCAPE_A4, Section

_ALLOCATION_COLORS = ["#1f6f6e", "#0f5352", "#5fa8a7", "#a7cfcf", "#d8e8e8", "#8a8a8a", "#c9c9c9"]


class AccountMovement(BaseModel):
    starting_market_value: float | None = None
    total_additions: float | None = None
    total_withdrawals: float | None = None
    net_addition: float | None = None
    gains_losses: float | None = None
    total_income_gross: float | None = None
    total_expenses: float | None = None
    forex_movements: float | None = None
    net_internal_transfers: float | None = None
    ending_market_value: float


class PerformanceRow(BaseModel):
    label: str  # e.g. "Since inception p.a."
    return_before_expenses_pct: float
    return_after_expenses_pct: float
    benchmark_pct: float | None = None


class AssetAllocationEntry(BaseModel):
    asset_class: str
    market_value: float
    weight_pct: float


class Holding(BaseModel):
    code: str
    description: str
    quantity: float
    avg_unit_cost: float | None = None
    market_value: float
    weight_pct: float
    gain_loss: float | None = None
    gain_loss_pct: float | None = None
    est_income: float | None = None
    est_yield_pct: float | None = None


class ExchangeGroup(BaseModel):
    name: str  # e.g. "ASX Listed", "NASDAQ", "Cash"
    holdings: list[Holding] = Field(default_factory=list)
    total_market_value: float
    total_weight_pct: float
    total_gain_loss: float | None = None
    total_gain_loss_pct: float | None = None
    total_est_income: float | None = None
    total_est_yield_pct: float | None = None


class InvestmentSummaryData(BaseModel):
    client_name: str
    model_name: str  # e.g. "Advisory Partners High Growth Model"
    account_code: str | None = None
    period_label: str  # e.g. "26 Jun 2018 to 03 Oct 2025"
    movement: AccountMovement
    performance: list[PerformanceRow] = Field(default_factory=list)
    asset_allocation: list[AssetAllocationEntry] = Field(default_factory=list)
    exchange_groups: list[ExchangeGroup] = Field(default_factory=list)
    net_portfolio_value: float
    exchange_rates: list[tuple[str, float]] = Field(default_factory=list)


def _asset_allocation_chart(entries: list[AssetAllocationEntry]) -> Image:
    fig, ax = plt.subplots(figsize=(2.6, 2.3), dpi=150)
    labels = [f"{e.asset_class} {e.weight_pct:.1f}%" for e in entries]
    values = [e.weight_pct for e in entries]
    ax.pie(
        values, colors=_ALLOCATION_COLORS[: len(values)], startangle=90,
        wedgeprops={"linewidth": 1, "edgecolor": "white"},
    )
    ax.legend(labels, loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=6.5, frameon=False)
    ax.set_aspect("equal")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=150, height=132)


def _account_block(movement: AccountMovement, width: float) -> list:
    rows = [
        ("Starting market value", pb.fmt_money(movement.starting_market_value, na="-")),
        ("Total additions", pb.fmt_money(movement.total_additions, na="-")),
        ("Total withdrawals", pb.fmt_money(movement.total_withdrawals, na="-")),
        ("Net addition", pb.fmt_money(movement.net_addition, na="-")),
        ("Realised and unrealised gains/losses", pb.fmt_money(movement.gains_losses, na="-")),
        ("Total income gross of foreign tax paid", pb.fmt_money(movement.total_income_gross, na="-")),
        ("Total expenses", pb.fmt_money(movement.total_expenses, na="-")),
        ("Forex movements", pb.fmt_money(movement.forex_movements, na="-")),
        ("Net internal transfers", pb.fmt_money(movement.net_internal_transfers, na="-")),
        ("Ending market value", pb.fmt_money(movement.ending_market_value)),
    ]
    last = len(rows) - 1
    return [
        pb.subsection_heading("Your account"),
        pb.key_value_table(rows, width, bold_rows={last}, rule_above={last}),
    ]


def _performance_block(rows: list[PerformanceRow], width: float) -> list:
    columns = [
        pb.Column("Period", "label", weight=1.6),
        pb.Column("Return before expenses", "before", weight=1.1, align="right"),
        pb.Column("Return after expenses", "after", weight=1.1, align="right"),
        pb.Column("Benchmark", "benchmark", weight=1.0, align="right"),
    ]
    table_rows = [
        {
            "label": r.label,
            "before": pb.fmt_pct(r.return_before_expenses_pct),
            "after": pb.fmt_pct(r.return_after_expenses_pct),
            "benchmark": pb.fmt_pct(r.benchmark_pct) if r.benchmark_pct is not None else "—",
        }
        for r in rows
    ]
    return [pb.subsection_heading("Your performance"), pb.data_table(columns, table_rows, width)]


def _asset_allocation_block(entries: list[AssetAllocationEntry], net_value: float, width: float) -> list:
    half = (width - 14) / 2
    columns = [
        pb.Column("Asset class", "asset_class", weight=2),
        pb.Column("Market value", "market_value", weight=1.2, align="right"),
        pb.Column("% net portfolio", "weight_pct", weight=1.1, align="right"),
    ]
    rows = [
        {"asset_class": e.asset_class, "market_value": pb.fmt_money(e.market_value), "weight_pct": pb.fmt_pct(e.weight_pct)}
        for e in entries
    ]
    table = pb.data_table(columns, rows, half)
    return [
        pb.subsection_heading(f"Asset class allocation — net portfolio value {pb.fmt_money(net_value)}"),
        pb.two_column_layout([table], [_asset_allocation_chart(entries)], width),
    ]


def _holdings_table(group: ExchangeGroup, width: float):
    columns = [
        pb.Column("Code", "code", weight=0.8),
        pb.Column("Description", "description", weight=2.6),
        pb.Column("Qty", "quantity", weight=0.9, align="right"),
        pb.Column("Avg cost $", "avg_unit_cost", weight=0.9, align="right"),
        pb.Column("Mkt value $", "market_value", weight=1.0, align="right"),
        pb.Column("Wt %", "weight_pct", weight=0.6, align="right"),
        pb.Column("Gain/loss $", "gain_loss", weight=1.0, align="right"),
        pb.Column("Gain/loss %", "gain_loss_pct", weight=0.8, align="right"),
        pb.Column("Est income $", "est_income", weight=0.9, align="right"),
        pb.Column("Est yield %", "est_yield_pct", weight=0.8, align="right"),
    ]
    rows = [
        {
            "code": h.code, "description": h.description,
            "quantity": pb.fmt_number(h.quantity, decimals=0 if float(h.quantity).is_integer() else 2),
            "avg_unit_cost": pb.fmt_money(h.avg_unit_cost),
            "market_value": pb.fmt_money(h.market_value),
            "weight_pct": pb.fmt_pct(h.weight_pct),
            "gain_loss": pb.fmt_money_signed(h.gain_loss),
            "gain_loss_pct": pb.fmt_pct(h.gain_loss_pct),
            "est_income": pb.fmt_money(h.est_income),
            "est_yield_pct": pb.fmt_pct(h.est_yield_pct),
        }
        for h in group.holdings
    ]
    rows.append({
        "code": "", "description": "Totals", "quantity": "", "avg_unit_cost": "",
        "market_value": pb.fmt_money(group.total_market_value),
        "weight_pct": pb.fmt_pct(group.total_weight_pct),
        "gain_loss": pb.fmt_money_signed(group.total_gain_loss),
        "gain_loss_pct": pb.fmt_pct(group.total_gain_loss_pct),
        "est_income": pb.fmt_money(group.total_est_income),
        "est_yield_pct": pb.fmt_pct(group.total_est_yield_pct),
    })
    return pb.data_table(columns, rows, width, row_bold={len(rows) - 1})


def build_investment_summary_section(data: InvestmentSummaryData) -> Section:
    section = Section(key="investment_summary", title=data.model_name, page_size=LANDSCAPE_A4)
    width = section.usable_width
    meta = [f"<b>Client:</b> {data.client_name}"]
    if data.account_code:
        meta.append(f"<b>Account:</b> {data.account_code}")
    section.story += pb.masthead_block(data.model_name, meta=meta, subtitle=f"Investment summary · {data.period_label}")

    half = (width - 14) / 2
    section.story.append(pb.two_column_layout(
        _account_block(data.movement, half), _performance_block(data.performance, half), width,
    ))
    section.story.append(Spacer(1, 16))
    section.story += _asset_allocation_block(data.asset_allocation, data.net_portfolio_value, width)

    if data.exchange_groups:
        section.story.append(PageBreak())
        section.story += pb.masthead_block(data.model_name, subtitle=f"Portfolio valuation · {data.period_label}")
        for group in data.exchange_groups:
            section.story.append(pb.subsection_heading(group.name))
            section.story.append(_holdings_table(group, width))
            section.story.append(Spacer(1, 10))

    if data.exchange_rates:
        section.story.append(pb.note(
            "Exchange rates used: " + "; ".join(f"{k} = {v}" for k, v in data.exchange_rates)
        ))

    return section
