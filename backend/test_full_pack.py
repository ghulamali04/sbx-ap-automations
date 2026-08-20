"""
Full pack test — combines all 9 client_review_pack sections into ONE PDF via
pdf_builder.combine_mixed_sections (handles the portrait A4 / landscape A4 /
landscape A3 mix).

Task Summary uses LIVE Zoho data (fetch_live_task_summary). Every other
section has no source-system integration in this codebase yet (see
client_review_pack/__init__.py), so they're built from sample data shaped
like the original reference pack, clearly labelled below.

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


# ---------- sample data (no live source exists for these sections yet) ----------

def build_meeting_details() -> md.Section:
    data = md.MeetingDetailsData(
        client_name="Dan",
        date="12 Aug 2026", time="10:00 AM", location="Advisory Partners Office",
        attendees="Dan, Danny, Cameron White",
        objectives="Review Q2 progress and confirm next steps",
        agenda=[md.AgendaItem(item="Portfolio performance review", presenter="Cameron White")],
        action_items=[md.ActionItem(action="Send updated trust documents", who="Cameron", when="19 Aug 2026", status="Open")],
    )
    return md.build_meeting_details_section(data)


def build_email_summary() -> es.Section:
    data = es.EmailSummaryData(
        client_name="Dan",
        period_label="September 2024 – June 2026",
        entries=[
            es.EmailSummaryEntry(
                date_period="Sep 2024", topic="Transfer of business name registration: DAN PODIATRY",
                summary="Dan forwarded an ASIC notice regarding transfer of the Dan Podiatry business name.",
                outcome="Administrative transfer matter raised for action.",
            ),
            es.EmailSummaryEntry(
                date_period="Jan – Jun 2026", topic="Dan Clinic / Commercial Property Purchase",
                summary="Dan and Danny explored purchasing the Dan clinic property.",
                outcome="Progressed to finance applications and property ownership structuring.",
            ),
        ],
    )
    return es.build_email_summary_section(data)


def build_investment_summary() -> inv.Section:
    mv = inv.AccountMovement(net_addition=1000000, gains_losses=847810.42, total_income_gross=301015.36, ending_market_value=2147284.82)
    alloc = [
        inv.AssetAllocationEntry(asset_class="Domestic Shares", market_value=894457.04, weight_pct=41.66),
        inv.AssetAllocationEntry(asset_class="International Shares", market_value=949475.32, weight_pct=44.21),
    ]
    holding = inv.Holding(code="ALD", description="AMPOL LIMITED", quantity=716, market_value=21465.68, weight_pct=1.0)
    grp = inv.ExchangeGroup(name="ASX Listed", holdings=[holding], total_market_value=21465.68, total_weight_pct=1.0)
    data = inv.InvestmentSummaryData(
        client_name="Dan", model_name="Advisory Partners High Growth Model",
        period_label="26 Jun 2018 to 03 Oct 2025", movement=mv,
        performance=[inv.PerformanceRow(label="Since inception p.a.", return_before_expenses_pct=11.92, return_after_expenses_pct=11.92, benchmark_pct=10.4)],
        asset_allocation=alloc, exchange_groups=[grp], net_portfolio_value=2147284.82,
        exchange_rates=[("AUD/USD", 0.6596)],
    )
    return inv.build_investment_summary_section(data)


def build_super_cash_performance() -> scp.Section:
    hh = scp.HouseholdSummary(
        head_client="Dan", accounts_description="3 linked AustralianSuper accounts (husband & wife)",
        reporting_period="1 Aug 2021 – 7 Feb 2022", date_prepared="07/02/2022", prepared_by="Advisory Partners",
        members=[
            scp.HouseholdMember(name="Dan", member_no="10741795", product="Retirement income", cash=4939.58, investments=390677.96, total_value=395617.54, return_display="(1.0%)"),
            scp.HouseholdMember(name="Mandy", member_no="10735153", product="Retirement income", cash=29017.03, investments=233482.40, total_value=262499.43, return_display="n/a"),
        ],
        total_cash=64068.88, total_investments=624160.36, total_value=688229.24,
    )
    perf = scp.MemberPerformanceSummary(
        member_name="Dan", product="Choice Income",
        rows=[scp.WaterfallRow(label="Value at start date (3/08/2021)", amount=413967.04),
              scp.WaterfallRow(label="Less pension payments", amount=-12012.00)],
        adjusted_value=399599.93, value_as_at=395617.54, movement=-3982.39, return_since_inception_display="(1.0%)",
    )
    data = scp.SuperReportData(household=hh, performance_summaries=[perf])
    return scp.build_super_cash_performance_section(data)


def build_smsf_snapshot() -> smsf.Section:
    fo = smsf.FundOverview(
        fund_name="Dan Superannuation Fund", abn="12 345 678 910", compliance_status="Complying",
        gst_status="Registered", registered_address="15 Pakington St, Geelong West VIC 3218",
        financial_year="2026–27", trustee_structure="Corporate – 4 Directors",
        corporate_trustee="Dan SMSF Nominees Pty Ltd", latest_trust_deed="6 June 2023",
        adviser="Cameron White", accountant_tax_agent="Matthew Le Maitre", auditor="Deanne Firth (Tactical Super)",
    )
    fp = smsf.FinancialPosition(
        total_assets=1450937.86, total_liabilities=501164.69, net_assets=949773.17,
        member_entitlement_accounts=929322.79, unallocated_member_entitlements=20450.38,
        total_member_entitlements=949773.17, asset_allocation=[("Direct property", 91.3), ("Australian equities", 3.5)],
    )
    fs = smsf.SMSFFundSnapshotData(as_at="5 July 2026", overview=fo, financial_position=fp)
    return smsf.build_smsf_snapshot_section(smsf.SMSFSnapshotData(fund_snapshot=fs))


def build_insurance_review() -> ir.Section:
    data = ir.InsuranceReviewData(
        household_name="Dan family (Dan & Mandy)", adviser="Cameron White", as_at="5 July 2026",
        household_total_policies=8, household_total_premium=30961.83,
        household_summary=[
            ir.HouseholdInsuranceRow(client="Mandy", age=40, review_month="Apr", service_date="01/04/2026",
                                      policies=4, annual_premium=5601.23, insurers="Zurich (3), NEOS (1)",
                                      watchlist_insurer="None", exclusions_loadings="None"),
        ],
        policy_risk_register=[
            ir.PolicyRiskRow(client="Dan", policy="P2", type="TPD & Income Protection", insurer="TAL",
                              owner="Individual", sum_insured="TPD $3,341,833 / IP $62,436 pa",
                              annual_premium=14033.36, watchlist=True, risk_score=64, risk_rating="High priority",
                              review_summary="Highest-risk policy. TAL income-protection provider trigger."),
        ],
    )
    return ir.build_insurance_review_section(data)


def build_group_structure() -> gs.Section:
    company = gs.EntityBox(id="holdings", heading="Dan Holdings Pty Ltd", fields=[("ACN", "615 752 442"), ("Director", "Luke Adams")], kind="company")
    trust = gs.EntityBox(id="family_trust", heading="Dan Family Trust", fields=[("Trustee", "Luke Adams")], kind="trust")
    data = gs.GroupStructureData(
        client_name="Dan", as_at="5 July 2026",
        levels=[[company], [trust]],
        edges=[("holdings", "family_trust"), ("family_trust", "__root__")],
        root_label="Dan",
    )
    return gs.build_group_structure_section(data)


def build_compliance_status() -> cs.Section:
    data = cs.ComplianceStatusData(
        client_name="Dan", generated_on="05/07/2026", last_updated="03/07/2026",
        years=["2023", "2024", "2025", "2026"],
        rows=[
            cs.ComplianceRow(entity="Dan", year_status={"2023": "Received", "2024": "Received", "2025": "Received", "2026": "Not Received"}),
            cs.ComplianceRow(entity="Dan Holdings Pty Ltd", bas_ias_outstanding=1,
                              year_status={"2023": "Received", "2024": "Received", "2025": "Received", "2026": "Not Received"}),
        ],
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
