"""
Full pack test — combines all 9 client_review_pack sections into ONE PDF via
pdf_builder.combine_mixed_sections (handles the portrait A4 / landscape A4 /
landscape A3 mix).

Task Summary uses LIVE Zoho data (fetch_live_task_summary) — its content will
not match the reference pack's Madden sample, that's expected: it's real data.
Every other section has no source-system integration in this codebase yet, so
they're transcribed in full from the reference pack ("0. Combined report (Dan
version)") to check the format end to end.

Known gaps vs. the reference pack (layout, not data): investment summary's
QR-code cover page and line/area charts (page versus cumulative investment,
returns over time) aren't built — this module renders tables and the one pie
chart; multi-page continuation banners ("... continued") aren't reproduced,
reportlab just flows the table across pages.

Usage:
    python test_full_pack.py "<head_client_id>"
"""
import asyncio
import sys

sys.path.insert(0, ".")

from api.settings import load_local_settings

load_local_settings()

from api.lib import pdf_builder as pb
from api.automations.client_review_pack.live.task_summary import fetch_live_task_summary
from api.automations.client_review_pack.sections import (
    meeting_details as md,
    email_summary as es,
    investment_summary as inv,
    super_cash_performance as scp,
    smsf_snapshot as smsf,
    insurance_review as ir,
    group_structure as gs,
    task_summary as ts,
    compliance_status as cs,
)


# ---------- meeting details: reference page 1 is a blank template ----------

def build_meeting_details() -> md.Section:
    return md.build_meeting_details_section(md.MeetingDetailsData())


# ---------- email summary: all 9 correspondence entries (p.2) ----------

def build_email_summary() -> es.Section:
    rows = [
        ("Sep 2024", "Transfer of business name registration: DAN PODIATRY",
         "Dan forwarded an ASIC notice regarding transfer of the Dan Podiatry business name and asked whether further action was required.",
         "Administrative transfer matter raised for action."),
        ("Jan – Jun 2026", "Dan Clinic / Commercial Property Purchase",
         "Dan and Danny explored purchasing the Dan clinic property. Discussions covered borrowing capacity, finance approval, lender requirements, entity structures, and acquisition strategy. Danny initiated enquiries and Dean participated in decisions and confirmations.",
         "Progressed to finance applications and property ownership structuring."),
        ("Apr 2026", "Property Opportunities",
         "Dan and Danny discussed potential property opportunities and whether to proceed, with advice that finance capacity should not be an issue.",
         "Continued evaluating commercial property acquisitions."),
        ("May – Jun 2026", "New Investment Structure Setup",
         "Dan and Danny worked with advisers to establish new trusts and a property company (including proposed family trusts and a property investment company) to acquire commercial property and improve asset protection and tax outcomes.",
         "New trust and company structures established and documents issued for signing."),
        ("May 2026", "Finance & Banking Documentation",
         "Ongoing collaboration between Dan and Danny to provide financial statements, tax returns, trust documents and lender information required for finance approval.",
         "Documentation progressively supplied to broker and lender."),
        ("Mar 2026", "Emblation Rental Strategy",
         "Dan raised concerns about future limits on equipment rentals. Matthew suggested a strategy discussion with Dan and Danny to prepare for future changes and possible alternative income opportunities.",
         "Strategy meeting arranged."),
        ("Mar 2026", "Australian Clinic / Dan Health Operations",
         "Dan discussed Xero access issues, GoCardless setup, GST treatment, and invoicing between Australian Clinic and Dan Health. Danny was included in the correspondence.",
         "Accounting setup and GST treatment clarified."),
        ("Nov 2025", "Colac Property Development Opportunity",
         "Danny shared building costings and development plans for a Colac property with Dan and advisers. Discussions focused on feasibility, construction costs, and strategic value.",
         "Further discussions and analysis recommended."),
        ("Dec 2025", "Property Search Updates",
         "Danny advised the property search was progressing slowly; discussion centred on future borrowing capacity and acquisition opportunities.",
         "Search continued."),
    ]
    data = es.EmailSummaryData(
        client_name="Dan", period_label="September 2024 – June 2026",
        entries=[es.EmailSummaryEntry(date_period=d, topic=t, summary=s, outcome=o) for d, t, s, o in rows],
    )
    return es.build_email_summary_section(data)


# ---------- investment summary: full holdings register (p.3-9) ----------

# code, description, qty, avg_cost, mkt_value, weight_pct, gain, gain_pct, est_income, est_yield
_ASX_HOLDINGS = [
    ("ALD", "AMPOL LIMITED FPO", 716, 25.6152, 21465.68, 1.00, 3125.18, 17.04, 322.20, 1.5),
    ("ALQ", "ALS LIMITED FPO", 1168, 17.1012, 24773.28, 1.15, 4799.11, 24.03, 450.85, 1.82),
    ("AN3PJ", "ANZ CAP NOTE 3-BBSW+2.70% PERP NON-CUM RED T-03-29", 191, 99.7639, 19644.35, 0.91, 589.45, 3.09, 1014.31, 5.16),
    ("APA", "APA GROUP FULLY PAID UNITS STAPLED SECURITIES", 4566, 7.8889, 40957.02, 1.91, 4936.17, 13.7, 2602.62, 6.35),
    ("BHP", "BHP GROUP LIMITED FPO", 2352, 37.9421, 98972.16, 4.61, 9732.35, 10.91, 4022.41, 4.06),
    ("BWP", "BWP GROUP FULLY PAID ORDINARY/UNITS STAPLED SECURITIES", 7977, 3.6171, 29913.75, 1.39, 1060.12, 3.67, None, None),
    ("CBA", "COMMONWEALTH BANK OF AUSTRALIA FPO", 261, 101.8107, 44469.18, 2.07, 17896.60, 67.35, 1265.85, 2.85),
    ("CSL", "CSL LIMITED FPO", 100, 193.1637, 20779.00, 0.97, 1462.63, 7.57, 452.19, 2.18),
    ("GMG", "GOODMAN GROUP FULLY PAID ORDINARY/UNITS STAPLED SECURITIES", 927, 12.8076, 31527.27, 1.47, 19654.58, 165.54, 278.10, 0.88),
    ("IAF", "ISHARES CORE COMPOSITE BOND ETF", 95, 103.4725, 9881.90, 0.46, 52.01, 0.53, 283.64, 2.87),
    ("IEU", "ISHARES EUROPE ETF", 721, 95.1628, 72229.78, 3.36, 3617.43, 5.27, 1788.97, 2.48),
    ("IZZ", "ISHARES CHINA LARGE-CAP ETF", 1740, 57.0991, 108454.20, 5.05, 9101.77, 9.16, 3635.73, 3.35),
    ("MQG", "MACQUARIE GROUP LIMITED FPO", 215, 164.656, 48359.95, 2.25, 12958.91, 36.61, 1397.50, 2.89),
    ("MVR", "VANECK AUSTRALIAN RESOURCES ETF", 1734, 34.9392, 69620.10, 3.24, 9035.58, 14.91, 2184.84, 3.14),
    ("NAB", "NATIONAL AUSTRALIA BANK LIMITED FPO", 1244, 26.4968, 55482.40, 2.58, 22520.36, 68.32, 2114.80, 3.81),
    ("NABPJ", "NAB CAP NOTE 3-BBSW+2.80% PERP NON-CUM RED T-09-30", 368, 101.8932, 38448.64, 1.79, 951.94, 2.54, 1796.72, 4.67),
    ("NXT", "NEXTDC LIMITED FPO", 1398, 13.9013, 23682.12, 1.10, 4248.10, 21.86, None, None),
    ("ORG", "ORIGIN ENERGY LIMITED FPO", 3910, 9.1344, 47975.70, 2.23, 12260.15, 34.33, 2346.00, 4.89),
    ("REA", "REA GROUP LTD FPO", 131, 227.4529, 30342.22, 1.41, 545.89, 1.83, 324.88, 1.07),
    ("RGN", "REGION GROUP FULLY PAID UNITS STAPLED SECURITIES", 12610, 2.3449, 30264.00, 1.41, 694.33, 2.35, 1727.57, 5.71),
    ("RMD", "RESMED INC CDI 10:1 FOREIGN EXEMPT NYSE", 1276, 31.726, 53681.32, 2.5, 13198.96, 32.6, 367.01, 0.68),
    ("SCG", "SCENTRE GROUP FULLY PAID ORDINARY/UNITS STAPLED SECURITIES", 5386, 3.5324, 22136.46, 1.03, 3111.11, 16.35, 937.96, 4.24),
    ("SOL", "WASHINGTON H. SOUL PATTINSON AND COMPANY LIMITED FPO", 1548, 29.4453, 60263.64, 2.81, 14682.36, 32.21, None, None),
    ("SUBD", "VANECK AUSTRALIAN SUBORDINATED DEBT ETF", 833, 25.2147, 20999.93, 0.98, -3.95, -0.02, 1203.68, 5.73),
    ("VAP", "VANGUARD AUSTRALIAN PROPERTY SECURITIES INDEX ETF", 676, 95.7699, 70506.80, 3.28, 5766.38, 8.91, 2791.16, 3.96),
    ("VAS", "VANGUARD AUSTRALIAN SHARES INDEX ETF", 784, 93.1806, 87463.04, 4.07, 14409.43, 19.72, 2660.29, 3.04),
    ("VGAD", "VANGUARD MSCI INDEX INTERNATIONAL SHARES (HEDGED) ETF", 1148, 88.8495, 134488.20, 6.26, 32488.95, 31.85, 5922.64, 4.4),
    ("VGB", "VANGUARD AUSTRALIAN GOVERNMENT BOND INDEX ETF", 209, 45.0998, 9827.18, 0.46, 401.33, 4.26, 282.35, 2.87),
    ("WBC", "WESTPAC BANKING CORPORATION FPO", 1363, 21.3096, 53579.53, 2.5, 24534.51, 84.47, 2071.76, 3.87),
    ("WDS", "WOODSIDE ENERGY GROUP LTD FPO", 1552, 28.092, 35696.00, 1.66, -7902.81, -18.13, 2586.90, 7.25),
    ("WES", "WESFARMERS LIMITED FPO", 295, 36.1462, 27007.25, 1.26, 16344.13, 153.28, 595.90, 2.21),
    ("WOW", "WOOLWORTHS GROUP LIMITED FPO", 1879, 30.8403, 49887.45, 2.32, -8061.41, -13.91, 1578.36, 3.16),
]
_HK_HOLDINGS = [("700.HKG", "TENCENT ORD", 466, 103.7493, 61134.66, 2.85, 12787.47, 26.45, 408.47, 0.67)]
_NASDAQ_HOLDINGS = [
    ("AAPL.NSM", "APPLE ORD", 170, 332.0754, 66500.00, 3.1, 10047.18, 17.8, 262.89, 0.4),
    ("AMZN.NSM", "AMAZON COM ORD", 179, 125.6171, 59569.88, 2.77, 37084.42, 164.93, None, None),
    ("GOOG.NSM", "ALPHABET CL C ORD", 233, 89.4051, 87057.08, 4.05, 66225.70, 317.91, 289.66, 0.33),
    ("META.NSM", "META PLATFORMS CL A ORD", 18, 1107.4261, 19390.66, 0.9, -543.01, -2.72, 56.63, 0.29),
    ("MSFT.NSM", "MICROSOFT ORD", 100, 215.7625, 78433.90, 3.65, 56857.65, 263.52, 503.34, 0.64),
    ("NVDA.NSM", "NVIDIA ORD", 221, 24.781, 62862.37, 2.93, 57385.77, 1047.84, 13.40, 0.02),
]
_NYSE_HOLDINGS = [
    ("BRK.B.NYS", "BERKSHIRE HATHAWAY CL B ORD", 152, 345.1936, 114933.29, 5.35, 62463.86, 119.05, None, None),
    ("V.NYS", "VISA ORD CL A", 111, 317.4659, 58872.41, 2.74, 23633.70, 67.07, 397.15, 0.67),
    ("XYZ.NYS", "BLOCK CL A ORD", 219, 125.0396, 25548.89, 1.19, -1834.79, -6.7, None, None),
]
_CASH_HOLDINGS = [("AUDCASH", "MAIN CASH ACCOUNT", 18495.07, 1.00, 18495.07, 0.86, None, None, 549.17, 2.97)]


def _holding(row) -> inv.Holding:
    code, desc, qty, avg_cost, mkt, wt, gain, gain_pct, income, yld = row
    return inv.Holding(code=code, description=desc, quantity=qty, avg_unit_cost=avg_cost, market_value=mkt,
                        weight_pct=wt, gain_loss=gain, gain_loss_pct=gain_pct, est_income=income, est_yield_pct=yld)


def _group(name: str, rows: list, total_mkt: float, total_wt: float, total_gain: float, total_gain_pct: float,
           total_income: float, total_yield: float) -> inv.ExchangeGroup:
    return inv.ExchangeGroup(
        name=name, holdings=[_holding(r) for r in rows], total_market_value=total_mkt, total_weight_pct=total_wt,
        total_gain_loss=total_gain, total_gain_loss_pct=total_gain_pct, total_est_income=total_income, total_est_yield_pct=total_yield,
    )


def build_investment_summary() -> inv.Section:
    mv = inv.AccountMovement(
        total_additions=1000000.00, net_addition=1000000.00, gains_losses=847810.42,
        total_income_gross=301015.36, ending_market_value=2147284.82,
    )
    alloc = [
        inv.AssetAllocationEntry(asset_class="Domestic Shares", market_value=894457.04, weight_pct=41.66),
        inv.AssetAllocationEntry(asset_class="International Shares", market_value=949475.32, weight_pct=44.21),
        inv.AssetAllocationEntry(asset_class="Domestic Listed Property", market_value=184348.28, weight_pct=8.59),
        inv.AssetAllocationEntry(asset_class="Domestic Fixed Interest", market_value=98802.00, weight_pct=4.6),
        inv.AssetAllocationEntry(asset_class="Cash & Equivalents", market_value=20202.18, weight_pct=0.94),
    ]
    groups = [
        _group("ASX Listed", _ASX_HOLDINGS, 1492779.50, 69.49, 248211.65, 19.94, 49007.19, 3.28),
        _group("Hong Kong Stock Exchange", _HK_HOLDINGS, 61134.66, 2.85, 12787.47, 26.45, 408.47, 0.67),
        _group("NASDAQ", _NASDAQ_HOLDINGS, 373813.89, 17.4, 227057.71, 154.72, 1125.92, 0.3),
        _group("NYSE - New York Stock Exchange", _NYSE_HOLDINGS, 199354.59, 9.28, 84262.77, 73.21, 397.15, 0.2),
        _group("Cash", _CASH_HOLDINGS, 18495.07, 0.86, None, None, 549.17, 2.97),
    ]
    data = inv.InvestmentSummaryData(
        client_name="Dan", model_name="Advisory Partners High Growth Model", account_code="AP0103",
        period_label="26 Jun 2018 to 03 Oct 2025", movement=mv,
        performance=[inv.PerformanceRow(label="Since inception p.a.", return_before_expenses_pct=11.92, return_after_expenses_pct=11.92, benchmark_pct=10.4)],
        asset_allocation=alloc, exchange_groups=groups, net_portfolio_value=2147284.82,
        exchange_rates=[("AUD/HKD", 5.13377), ("AUD/USD", 0.6596)],
    )
    return inv.build_investment_summary_section(data)


# ---------- super & cash performance: full household + Dan's sub-reports (p.10-16) ----------

_DAN_CASH_TXNS = [
    ("01/10/2020", "Buying 2,377 AFI.AU @ AUD6.31", -15042.87, 12420.59),
    ("01/10/2020", "Administration Fee", -32.47, 12388.12),
    ("01/10/2020", "Asset Based Fee", -2.77, 12385.35),
    ("01/10/2020", "DIV: ANZ.AU XD: 24-Aug-2020", 166.50, 12551.85),
    ("01/10/2020", "Franking Credit on ANZ.AU Dividend XD: 24-Aug-2020", 71.36, 12623.21),
    ("01/10/2020", "DIV: CBA.AU XD: 19-Aug-2020", 267.54, 12890.75),
    ("01/10/2020", "Franking Credit on CBA.AU Dividend XD: 19-Aug-2020", 114.66, 13005.41),
    ("01/10/2020", "ASPGST account back to the member — RITC for order 3838534", 3.10, 13008.51),
    ("01/10/2020", "ASPGST account back to the member — RITC for order 3838551", 3.00, 13011.51),
    ("01/10/2020", "Sold 17,510 CMW.AU @ AUD0.8951", 15627.73, 28639.24),
    ("01/10/2020", "Net Interest Payment", 26.49, 28665.73),
    ("02/10/2020", "DIV: WES.AU XD: 25-Aug-2020", 364.80, 29030.53),
    ("02/10/2020", "Franking Credit on WES.AU Dividend XD: 25-Aug-2020", 156.34, 29186.87),
    ("13/10/2020", "DIV: SYI.AU XD: 29-Sep-2020", 420.83, 29607.70),
    ("19/10/2020", "DIV: VGS.AU XD: 01-Oct-2020", 145.94, 29753.64),
    ("20/10/2020", "DIV: VAP.AU XD: 01-Oct-2020", 32.36, 29786.00),
    ("21/10/2020", "DIV: VAS.AU XD: 01-Oct-2020", 326.27, 30112.27),
]

_DAN_SHARES_ETF = [
    ("APA.AU", "APA Group", 1517.00, 10.16, 15412.72),
    ("ANZ.AU", "Australia and New Zealand Banking Group Limited", 364.00, 27.09, 9860.76),
    ("BHP.AU", "BHP Group Limited", 222.00, 46.81, 10391.82),
    ("BWP.AU", "BWP Trust", 2482.00, 4.03, 10002.46),
    ("CSL.AU", "CSL Limited", 33.00, 258.79, 8540.07),
    ("GMG.AU", "Goodman Group", 432.00, 23.74, 10255.68),
    ("IOO.AU", "iShares Global 100 ETF", 198.00, 107.41, 21267.18),
    ("NAB.AU", "National Australia Bank Limited", 367.00, 27.91, 10242.97),
    ("TCL.AU", "Transurban Group", 797.00, 12.95, 10321.15),
    ("VAF.AU", "Vanguard Australian Fixed Interest Index Fund ETF", 491.00, 48.40, 23764.40),
    ("WES.AU", "Wesfarmers Limited", 175.00, 53.72, 9401.00),
    ("WBC.AU", "Westpac Banking Corporation", 388.00, 21.52, 8349.76),
    ("ARG.AU", "Argo Investments Limited", 2133.00, 9.90, 21116.70),
]

_DAN_INVESTMENT_OPTIONS = [
    ("AS_DIVFI", "Diversified Fixed Interest", 33427.00, 1.00, 33427.00),
    ("AS_AUSSHAR", "Australian Shares", 67229.25, 1.00, 67229.25),
    ("AS_INTSHAR", "International Shares", 116577.87, 1.00, 116577.87),
    ("AS_CASH", "Cash", 4517.17, 1.00, 4517.17),
]

_DAN_SHARES_PERFORMANCE = [
    ("Australia and New Zealand Banking Group Limited", 10077.24, 9860.76, -216.48, 374.40, 157.92, 1.6),
    ("APA Group", 15082.13, 15412.72, 330.59, 379.25, 709.84, 4.7),
    ("Argo Investments Limited", 20144.30, 21116.70, 972.40, None, 972.40, 4.8),
    ("BHP Group Limited", 10056.32, 10391.82, 335.50, 861.13, 1196.63, 12.8),
    ("BWP Trust", 10076.73, 10002.46, -74.27, 223.88, 149.61, 1.5),
    ("CSL Limited", 10171.60, 8540.07, -1631.53, 54.71, -1576.82, -15.6),
    ("Goodman Group", 10070.51, 10255.68, 185.17, 64.80, 249.97, 2.5),
    ("iShares Global 100 ETF", 20058.47, 21267.18, 1208.71, 122.67, 1331.38, 6.7),
    ("National Australia Bank Limited", 10071.95, 10242.97, 171.02, 351.27, 522.29, 5.2),
    ("Transurban Group", 11102.66, 10321.15, -781.51, 119.55, -661.96, -6.2),
    ("Vanguard Australian Fixed Interest Index Fund ETF", 25102.58, 23764.40, -1338.18, 276.97, -1061.21, -4.2),
    ("Westpac Banking Corporation", 10083.27, 8349.76, -1733.51, 332.57, -1400.94, -14.0),
    ("Wesfarmers Limited", 9731.10, 9401.00, -330.10, None, -330.10, -3.3),
]


def build_super_cash_performance() -> scp.Section:
    hh = scp.HouseholdSummary(
        head_client="Dan (illustrative sample)", accounts_description="3 linked AustralianSuper accounts (husband & wife)",
        reporting_period="1 Aug 2021 – 7 Feb 2022", date_prepared="07/02/2022", prepared_by="Advisory Partners",
        members=[
            scp.HouseholdMember(name="Dan", member_no="10741795", product="Retirement income", cash=4939.58, investments=390677.96, total_value=395617.54, return_display="(1.0%)"),
            scp.HouseholdMember(name="Mandy", member_no="10735153", product="Retirement income", cash=29017.03, investments=233482.40, total_value=262499.43, return_display="n/a"),
            scp.HouseholdMember(name="Zac", member_no="10726336", product="Retirement income", cash=30112.27, investments=0, total_value=30112.27, return_display="n/a"),
        ],
        total_cash=64068.88, total_investments=624160.36, total_value=688229.24,
    )
    perf = scp.MemberPerformanceSummary(
        member_name="Dan", product="Choice Income",
        rows=[
            scp.WaterfallRow(label="Value at start date (3/08/2021)", amount=413967.04),
            scp.WaterfallRow(label="Less pension payments", amount=-12012.00),
            scp.WaterfallRow(label="Less administration fees", amount=-279.82),
            scp.WaterfallRow(label="Less brokerage, administration, adviser service & asset based fees", amount=-2075.29),
        ],
        adjusted_value=399599.93, value_as_at=395617.54, movement=-3982.39, return_since_inception_display="(1.0%)",
    )
    fees = scp.FeesCharges(
        member_name="Dan", period_label="1 Aug 2021 – 7 Feb 2022",
        lines=[
            scp.FeeLine(category="Portfolio administration fee", amount=187.22),
            scp.FeeLine(category="Thomson Reuters fee", amount=0),
            scp.FeeLine(category="Brokerage", amount=493.27),
            scp.FeeLine(category="Adviser service fee", amount=1372.19),
            scp.FeeLine(category="Asset based fee", amount=22.61),
        ],
        total=2075.29,
    )
    cgt = scp.CGTOverlay(
        member_name="Dan",
        lines=[
            scp.CGTLine(description="Gross unrealised capital gains", long_gains=19043.06),
            scp.CGTLine(description="Less unused realised/unrealised capital losses", long_gains=-2480.42),
        ],
        net_total=16562.64, cgt_liability_total=1656.26,
    )
    ledger = scp.CashTransactionLedger(
        member_name="Dan", member_no="10726336", product_type="Retirement income", reporting_period="28/09/2020 – 22/10/2020",
        opening_balance=27463.46,
        transactions=[scp.CashTransaction(effective_date=d, description=desc, amount=amt, balance=bal) for d, desc, amt, bal in _DAN_CASH_TXNS],
        closing_balance=30112.27,
    )
    valuation = scp.MemberPortfolioValuation(
        member_name="Dan", member_no="10741795", product_type="Retirement income", reporting_date="07/02/2022",
        transaction_account_rows=[
            scp.ValuationRow(description="Actual cash", quantity=4151.44, price=1.00, value=4151.44),
            scp.ValuationRow(description="Accrued interest net of unrealised tax (if applicable)", quantity=0.66, price=1.00, value=0.66),
            scp.ValuationRow(description="Income due but not yet received", quantity=787.48, price=1.00, value=787.48),
            scp.ValuationRow(description="Unsettled trades", quantity=0, price=1.00, value=0),
        ],
        transaction_account_total=4939.58,
        term_deposit_rows=[], term_deposit_total=0,
        shares_etf_rows=[scp.ValuationRow(description=f"{code} {desc}", quantity=q, price=p, value=v) for code, desc, q, p, v in _DAN_SHARES_ETF],
        shares_etf_total=168926.67,
        investment_option_rows=[scp.ValuationRow(description=f"{code} {desc}", quantity=q, price=p, value=v) for code, desc, q, p, v in _DAN_INVESTMENT_OPTIONS],
        investment_option_total=221751.29,
        total_portfolio_value=395617.54,
    )
    linked = scp.LinkedAccountAssetSummary(
        member_name="Mandy", member_no="10735153",
        entries=[
            scp.AssetClassValue(asset_class="Transaction account", value=29017.03),
            scp.AssetClassValue(asset_class="Term deposits", value=45022.19),
            scp.AssetClassValue(asset_class="Shares & ETFs", value=103303.99),
            scp.AssetClassValue(asset_class="Investment options", value=85156.22),
        ],
        total=262499.43,
    )
    shares_perf_rows = [
        scp.SharesPerformanceRow(investment=inv_name, investment_transactions=txn, closing_value=close, capital_growth=growth, income=inc, total_return=tot, total_return_pct=pct)
        for inv_name, txn, close, growth, inc, tot, pct in _DAN_SHARES_PERFORMANCE
    ]
    shares_perf = scp.SharesPerformanceReport(
        member_name="Dan", member_no="10741795", product_type="Pension", reporting_period="01/08/2021 – 07/02/2022",
        rows=shares_perf_rows,
        total=scp.SharesPerformanceRow(investment="Total", investment_transactions=171828.86, closing_value=168926.67, capital_growth=-2902.19, income=3161.20, total_return=259.01, total_return_pct=0.2),
    )
    data = scp.SuperReportData(
        household=hh, performance_summaries=[perf], fees_charges=[fees], cgt_overlays=[cgt],
        cash_ledgers=[ledger], portfolio_valuations=[valuation], linked_account_summaries=[linked],
        shares_performance_reports=[shares_perf],
    )
    return scp.build_super_cash_performance_section(data)


# ---------- SMSF fund + portfolio snapshot (p.17-18) ----------

def build_smsf_snapshot() -> smsf.Section:
    fo = smsf.FundOverview(
        fund_name="Dan Superannuation Fund", abn="12 345 678 910", compliance_status="Complying (updated 03 Jul 2026)",
        gst_status="Registered", registered_address="15 Pakington St Geelong West VIC 3218", financial_year="2026–27",
        trustee_structure="Corporate – 4 Directors", corporate_trustee="Dan SMSF Nominees Pty Ltd (ACN 345 678 910)",
        latest_trust_deed="6 June 2023", adviser="Cameron White", accountant_tax_agent="Matthew Le Maitre",
        auditor="Deanne Firth (Tactical Super)",
    )
    currency_checks = [
        smsf.StatusCheckRow(check="Latest period update (last processed year-end)", value="30 Jun 2025", status="Review", comment="Processed to FY2024–25; FY2025–26 not yet finalised"),
        smsf.StatusCheckRow(check="Oldest open year", value="2026", status="Review", comment="FY2025–26 open for processing"),
        smsf.StatusCheckRow(check="Unmatched cash transactions", value="3", status="Review", comment="Allocate before finalising accounts"),
        smsf.StatusCheckRow(check="Unmatched business events", value="1", status="Review", comment="Match to source transaction"),
        smsf.StatusCheckRow(check="Incomplete business events", value="0", status="Clear", comment="—"),
        smsf.StatusCheckRow(check="Outstanding corporate actions", value="0", status="Clear", comment="—"),
    ]
    bank_feeds = [
        smsf.BankFeedRow(feed="Macquarie CMA – 182-512/963057", status="OK", last_processed="4 Jul 2026"),
        smsf.BankFeedRow(feed="Loan – 15 Pakington St – 083-646/905416", status="OK", last_processed="4 Jul 2026"),
        smsf.BankFeedRow(feed="Rabobank HISA 9800 – 142-201/360509", status="Feed no longer active", last_processed="5 Jun 2025"),
    ]
    fp = smsf.FinancialPosition(
        total_assets=1450937.86, total_liabilities=501164.69, net_assets=949773.17,
        member_entitlement_accounts=929322.79, unallocated_member_entitlements=20450.38, total_member_entitlements=949773.17,
        asset_allocation=[("Direct property", 91.3), ("Australian equities", 3.5), ("International equities", 2.7), ("Cash", 2.3), ("Australian fixed interest", 0.3)],
    )
    member_caps = [
        smsf.MemberCapRow(member="Mr Dan", age=41, total_balance=317961.24, accumulation=317961.24, pension=0, conc_cap=138000.00, conc_used=0, conc_available=138000.00, non_conc_cap=130000.00, non_conc_used=0, non_conc_available=130000.00),
        smsf.MemberCapRow(member="Mrs Mandy", age=46, total_balance=106514.46, accumulation=106514.46, pension=0, conc_cap=147934.29, conc_used=479.47, conc_available=147454.82, non_conc_cap=130000.00, non_conc_used=0, non_conc_available=130000.00),
        smsf.MemberCapRow(member="Mr Zac", age=40, total_balance=339131.10, accumulation=339131.10, pension=0, conc_cap=125994.61, conc_used=0, conc_available=125994.61, non_conc_cap=130000.00, non_conc_used=0, non_conc_available=130000.00),
        smsf.MemberCapRow(member="Mr Ash", age=45, total_balance=165715.99, accumulation=165715.99, pension=0, conc_cap=175000.00, conc_used=0, conc_available=175000.00, non_conc_cap=130000.00, non_conc_used=0, non_conc_available=130000.00),
    ]
    fund_total = smsf.MemberCapRow(member="Fund total", age=0, total_balance=929322.79, accumulation=929322.79, pension=0, conc_cap=0, conc_used=479.47, conc_available=586449.43, non_conc_cap=0, non_conc_used=0, non_conc_available=520000.00)
    member_pensions = [smsf.MemberPensionRow(member=m, pension_accounts="-", minimum_pension="-", pension_paid_ytd="-", over_under="-") for m in ("Mr Dan", "Mrs Mandy", "Mr Zac", "Mr Ash")]
    fs = smsf.SMSFFundSnapshotData(
        as_at="5 July 2026", overview=fo, currency_checks=currency_checks, bank_feeds=bank_feeds,
        financial_position=fp, member_caps=member_caps, fund_total_caps=fund_total, member_pensions=member_pensions,
    )
    holdings = [
        smsf.HoldingRow(market_type="Bank", holding="Macquarie CMA (60400)", quantity=20582.30, cost=20582.30, market_price=1.00, market_value=20582.30, unrealised_gain_loss=0, asset_pool="Default Pool"),
        smsf.HoldingRow(market_type="Bank", holding="Loan – 15 Pakington St (NABLOAN)", quantity=-487461.39, cost=-487461.39, market_price=1.00, market_value=-487461.39, unrealised_gain_loss=0, asset_pool="Default Pool"),
        smsf.HoldingRow(market_type="Bank", holding="Rabobank HISA 9800 (Rabo #9800)", quantity=0, cost=0, market_price=1.00, market_value=0, unrealised_gain_loss=0, asset_pool="Default Pool"),
        smsf.HoldingRow(market_type="Non-Investment Asset", holding="ASIC Prepayment", quantity=1.00, cost=103.00, market_price=103.00, market_value=103.00, unrealised_gain_loss=0, asset_pool="Default Pool"),
        smsf.HoldingRow(market_type="Non-Investment Asset", holding="Borrowing costs", quantity=0, cost=0, market_price=0, market_value=0, unrealised_gain_loss=0, asset_pool="Default Pool"),
        smsf.HoldingRow(market_type="Property (Direct)", holding="15 Pakington St, Geelong West (15PAKO)", quantity=1.00, cost=1059995.63, market_price=1361000.00, market_value=1361000.00, unrealised_gain_loss=301004.37, asset_pool="Default Pool"),
        smsf.HoldingRow(market_type="Wrap / Platform", holding="Praemium Portfolio", quantity=1.00, cost=55378.28, market_price=68076.06, market_value=68076.06, unrealised_gain_loss=12697.78, asset_pool="Default Pool"),
    ]
    ps = smsf.SMSFPortfolioSnapshotData(
        holdings_as_at="5 July 2026", holdings=holdings, total_cost=648597.82, total_market_value=962299.97, total_unrealised=313702.15,
        asset_allocation=[("Direct property", 91.3), ("Australian equities", 3.5), ("International equities", 2.7), ("Cash", 2.3), ("Australian fixed interest", 0.3)],
        notes="Holdings are shown at the fund's holding level and include the limited-recourse borrowing (NAB loan) as a negative bank balance. The market value of investment assets differs from accounting net assets ($949,773.17) due to accrued items and other liabilities carried in the financial position. Property and Praemium holdings drive the unrealised gain; bank and non-investment assets are carried at cost.",
    )
    return smsf.build_smsf_snapshot_section(smsf.SMSFSnapshotData(fund_snapshot=fs, portfolio_snapshot=ps))


# ---------- insurance summary & risk review (p.19-20) ----------

def build_insurance_review() -> ir.Section:
    household_summary = [
        ir.HouseholdInsuranceRow(client="Mandy", age=40, review_month="Apr", service_date="01/04/2026", policies=4, annual_premium=5601.23, insurers="Zurich (3), NEOS (1)", watchlist_insurer="—", exclusions_loadings="None"),
        ir.HouseholdInsuranceRow(client="Dan", age=43, review_month="Jun", service_date="13/05/2026", policies=4, annual_premium=25360.60, insurers="TAL (2), Zurich (2)", watchlist_insurer="TAL", exclusions_loadings="1"),
    ]
    risk_rows = [
        ir.PolicyRiskRow(client="Mandy", policy="P1", type="Income Protection", insurer="Zurich", owner="Individual", sum_insured="IP: $100,368 pa", annual_premium=1104.92, watchlist=False, risk_score=25, risk_rating="Low–moderate",
                          review_summary="Income protection — review more frequently: confirm waiting/benefit period still match sick-leave and cash reserves and that income can be substantiated at claim. Zurich not on the service-risk watchlist. Client at age 40 review band. Priority: next scheduled annual review."),
        ir.PolicyRiskRow(client="Mandy", policy="P2", type="Life & TPD", insurer="Zurich", owner="Super fund", sum_insured="Life $2,781,833 / TPD $2,781,833", annual_premium=1802.20, watchlist=False, risk_score=30, risk_rating="Low–moderate",
                          review_summary="Held inside super — confirm beneficiary nomination, estate/tax-effectiveness and that the TPD definition and super release conditions align. Recalculate life/TPD need vs debt, dependants and estate liquidity. Zurich not watchlisted. Priority: next annual review."),
        ir.PolicyRiskRow(client="Mandy", policy="P3", type="TPD & Trauma", insurer="Zurich", owner="Individual", sum_insured="TPD $2,781,834 / Trauma $417,276", annual_premium=1477.20, watchlist=False, risk_score=35, risk_rating="Low–moderate",
                          review_summary="TPD is also held individually (~$2.78m) alongside the super TPD — confirm this is intentional split / flexible-linking rather than duplication. Review trauma definitions and partial-payment / buy-back features vs current market. Zurich not watchlisted."),
        ir.PolicyRiskRow(client="Mandy", policy="P4", type="Life & TPD", insurer="NEOS", owner="Third party (4 owners)", sum_insured="Life $1,579,017 / TPD $1,579,017", annual_premium=1216.91, watchlist=False, risk_score=42, risk_rating="Review ≤6 months",
                          review_summary="Business buy/sell cross-ownership (cover on 4 principals: M Le Maitre, C White, J Purser, N Bethune; $1,216.91 x4 policies). Confirm sum insured matches current business valuation, ownership remains consistent with the shareholder/buy-sell agreement, and entity/tax treatment is correct. NEOS not watchlisted. Priority: review within 6 months (business-succession dependency)."),
        ir.PolicyRiskRow(client="Dan", policy="P1", type="Life", insurer="TAL", owner="Super fund", sum_insured="Life $3,341,833", annual_premium=1647.80, watchlist=True, risk_score=44, risk_rating="Review ≤6 months",
                          review_summary="Provider-service trigger: TAL is on the framework watchlist (2021 Federal Court duty-of-utmost-good-faith finding and subsequent ASIC claims remediation) — confirm current claims service; do not assume replacement. Held in super — check nomination, estate and tax. Recalculate life need. Priority: review within 6 months."),
        ir.PolicyRiskRow(client="Dan", policy="P2", type="TPD & Income Protection", insurer="TAL", owner="Individual", sum_insured="TPD $3,341,833 / IP $62,436 pa", annual_premium=14033.36, watchlist=True, risk_score=64, risk_rating="High priority",
                          review_summary="Highest-risk policy. TAL income-protection provider trigger — framework specifically notes TAL IP procedural-fairness / payment-cessation concerns and client reliance on timely income. High premium ($14,033 pa) — affordability review. Confirm benefit/waiting period, offsets and income substantiation. Client carries an underwriting exclusion/loading — factor into any replacement assessment. Priority: high — review within 6 months."),
        ir.PolicyRiskRow(client="Dan", policy="P3", type="Trauma", insurer="Zurich", owner="Individual", sum_insured="Trauma $333,780", annual_premium=2047.20, watchlist=False, risk_score=30, risk_rating="Low–moderate",
                          review_summary="Trauma — compare heart-attack / cancer / stroke and partial-payment definitions vs current market; preserve any valuable legacy wording. Zurich not watchlisted. Priority: next annual review."),
        ir.PolicyRiskRow(client="Dan", policy="P4", type="Income Protection", insurer="Zurich", owner="Individual", sum_insured="IP: $90,168 pa", annual_premium=7632.24, watchlist=False, risk_score=48, risk_rating="Review ≤6 months",
                          review_summary="Second income-protection layer alongside the TAL IP (P2) — review combined cover for over-insurance/duplication (total IP benefit ≈ $152.6k pa; combined IP premium ≈ $21.7k pa) and confirm income can be substantiated at claim. Zurich not watchlisted. Priority: review within 6 months."),
    ]
    watchlist = [
        ir.InsurerWatchlistRow(provider="TAL / Asteron", on_watchlist=True,
                                basis="2021 Federal Court found TAL breached its duty of utmost good faith on an income-protection claim; ASIC claims-calc/payment remediation; AFCA criticism of IP payment cessation without warning; acquired legacy books add admin complexity.",
                                suggested_response="Do not assume replacement. For IP, check procedural-fairness risk, benefit period, offsets, claim-evidence requirements and reliance on timely income. Review policy age, book, premium increases and claim vulnerability."),
        ir.InsurerWatchlistRow(provider="Zurich", on_watchlist=False, basis="Not listed on the framework watchlist. Standard review only.",
                                suggested_response="Apply standard review triggers (needs, definitions, ownership, affordability). No provider-service points added."),
        ir.InsurerWatchlistRow(provider="NEOS", on_watchlist=False, basis="Not listed on the framework watchlist. NEOS cover here is a business buy/sell arrangement.",
                                suggested_response="Standard review; focus on buy/sell ownership, business valuation and shareholder-agreement consistency rather than provider-service risk."),
    ]
    scoring = [
        ir.ScoringMatrixRow(score_range="0–20", rating="Monitor", recommended_action="No immediate review; confirm at next annual client meeting."),
        ir.ScoringMatrixRow(score_range="21–40", rating="Low–moderate", recommended_action="Low-to-moderate priority; review at next scheduled annual review."),
        ir.ScoringMatrixRow(score_range="41–60", rating="Review ≤6 months", recommended_action="Review within six months, or sooner if affordability / claims risk is present."),
        ir.ScoringMatrixRow(score_range="61–80", rating="High priority", recommended_action="High-priority review; consider comprehensive insurance analysis."),
        ir.ScoringMatrixRow(score_range="81–100", rating="Immediate", recommended_action="Immediate comprehensive review; document risk, affordability and replacement considerations."),
    ]
    notes = [
        "Risk scores are indicative and framework-based. Policy commencement dates and premium history were not in the dataset, so policy-age (§2–3) and premium-movement triggers could not be scored — scores are lower bounds pending that data.",
        "The framework is a triage tool, not replacement advice. A provider appearing on the watchlist does not make a policy unsuitable; provider-service concerns are one input only and must be verified against current APRA/ASIC, AFCA and Life Code sources before use in client advice.",
        "Watchlist commentary reflects public signals as at July 2026 and should be refreshed before client use. TAL is the only insurer held here that appears on the framework watchlist; Zurich and NEOS are not listed.",
        "Source data note: the P4 columns in the supplied file were column-shifted (insurer/premium/owner rotated); these have been decoded to their correct fields in this summary.",
    ]
    data = ir.InsuranceReviewData(
        household_name="Dan family (Dan & Mandy)", adviser="Cameron White", as_at="5 July 2026",
        household_summary=household_summary, household_total_policies=8, household_total_premium=30961.83,
        policy_risk_register=risk_rows, insurer_watchlist=watchlist, scoring_matrix=scoring, notes=notes,
    )
    return ir.build_insurance_review_section(data)


# ---------- group structure (p.23) ----------

def build_group_structure() -> gs.Section:
    tree_trimming = gs.EntityBox(id="tree_trimming", heading="Dan Tree Trimming Pty Ltd", kind="company",
                                  fields=[("ACN", "160 075 …"), ("Director", "Dano, Dan2"), ("Secretary", "Dan"), ("Shareholder", "Dan Holdings Pty Ltd [6]")])
    car_wash = gs.EntityBox(id="car_wash", heading="Dan Car Wash Pty Ltd", kind="company",
                             fields=[("ACN", "626 401 123"), ("Director", "Dan"), ("Public Officer", "Dan"), ("Secretary", "Dan"), ("Shareholder", "Dan Holdings Pty Ltd [180]")])
    tower_hire = gs.EntityBox(id="tower_hire", heading="Dan & Tower Hire Pty Ltd", kind="company",
                               fields=[("ACN", "153 753 123"), ("Director", "Dan"), ("Secretary", "Dan"), ("Shareholder", "Dan Holdings Pty Ltd [12]")])
    holdings = gs.EntityBox(id="holdings", heading="Dan Holdings Pty Ltd", kind="company",
                             fields=[("ACN", "615 752 442"), ("Director", "Luke Adams"), ("Public Officer", "Luke Adams"), ("Secretary", "Luke Adams"), ("Shareholder", "Adams Family Trust [100]")])
    investments = gs.EntityBox(id="investments", heading="Dan Investments Pty Ltd", kind="company",
                                fields=[("ACN", "619 248 001"), ("Director", "Luke Adams"), ("Public Officer", "Luke Adams"), ("Secretary", "Luke Adams"), ("Shareholder", "Adams Family Trust [100]")])
    family_trust = gs.EntityBox(id="family_trust", heading="Dan Family Trust", kind="trust",
                                 fields=[("Appointor", "Luke Adams"), ("Beneficiary", "Luke Adams"), ("Trustee", "Luke Adams")])
    data = gs.GroupStructureData(
        client_name="Dan", as_at=None,
        levels=[[tree_trimming, car_wash, tower_hire], [holdings, investments], [family_trust]],
        edges=[
            ("tree_trimming", "holdings"), ("car_wash", "holdings"), ("tower_hire", "holdings"),
            ("holdings", "family_trust"), ("investments", "family_trust"),
            ("holdings", "__root__"), ("investments", "__root__"), ("family_trust", "__root__"),
        ],
        root_label="Dan",
    )
    return gs.build_group_structure_section(data)


# ---------- compliance lodgement status (p.24) ----------

def build_compliance_status() -> cs.Section:
    entities = [
        ("Mandy", 0, 0, 0, 0, None, {"2023": "Received", "2024": "Received", "2025": "Not Received", "2026": "Not Received"}),
        ("Dan", 0, 0, 0, 0, 1, {"2023": "Received", "2024": "Received", "2025": "Received", "2026": "Not Received"}),
        ("Dan Trees & Tower Hire Pty Ltd", 34989.00, 0, 0, 0, 1, {"2023": "Received", "2024": "Received", "2025": "Received", "2026": "Not Received"}),
        ("Dan Tree Trimming Pty Ltd", 0, 0, 0, 0, None, {"2023": "-", "2024": "-", "2025": "-", "2026": "-"}),
        ("Dan Holdings Pty Ltd", 0, 0, 0, 0, 1, {"2023": "Received", "2024": "Received", "2025": "Received", "2026": "Not Received"}),
        ("Dan Family Trust", 0, 0, 0, 0, None, {"2023": "Received", "2024": "Received", "2025": "Received", "2026": "Not Received"}),
        ("Dan Investments Pty Ltd", 0, 0, 0, 0, 1, {"2023": "Received", "2024": "Received", "2025": "Received", "2026": "Not Received"}),
        ("Dan Car Wash Pty Ltd", 0, 0, 0, 0, None, {"2023": "Received", "2024": "Received", "2025": "Received", "2026": "Not Received"}),
        ("Zac", 0, 0, 0, 0, None, {"2023": "-", "2024": "-", "2025": "-", "2026": "-"}),
    ]
    rows = [
        cs.ComplianceRow(entity=name, ica_debit=icad, ica_credit=icac, ita_debit=itad, ita_credit=itac, bas_ias_outstanding=out, year_status=status, fbt_return="-")
        for name, icad, icac, itad, itac, out, status in entities
    ]
    data = cs.ComplianceStatusData(
        client_name="Dan", generated_on="05/07/2026", last_updated="03/07/2026",
        years=["2023", "2024", "2025", "2026"], rows=rows,
    )
    return cs.build_compliance_status_section(data)


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    head_client_id = sys.argv[1]

    print(f"Fetching live Zoho task summary for head_client_id={head_client_id!r}...")
    try:
        task_data = await fetch_live_task_summary(head_client_id)
        task_section = ts.build_task_summary_section(task_data)
        print(f"  live: tasks_total={task_data.tasks_total}")
    except Exception as exc:
        print(f"  live fetch failed ({exc}) — falling back to a placeholder Task Summary section")
        task_section = ts.build_task_summary_section(ts.TaskSummaryData(
            head_client_id=head_client_id, tasks_total=0, prepared_by="Advisory Partners", as_at="19 Aug 2026",
        ))

    sections = [
        build_meeting_details(),
        build_email_summary(),
        build_investment_summary(),
        build_super_cash_performance(),
        build_smsf_snapshot(),
        build_insurance_review(),
        build_group_structure(),
        task_section,
        build_compliance_status(),
    ]

    pdf_bytes = pb.combine_mixed_sections(sections, title="Client Review Pack")
    out_path = "full_client_review_pack.pdf"
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"wrote {out_path} ({len(pdf_bytes)} bytes, {len(sections)} sections)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
