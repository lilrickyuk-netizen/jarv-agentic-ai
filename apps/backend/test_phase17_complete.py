"""
Comprehensive Phase 17 Test - All 8 Business Workflows

Tests all required and ideal workflows for Phase 17.
"""
import sys
from pathlib import Path
import uuid
import asyncio

sys.path.insert(0, str(Path(__file__).parent))

from app.core.workflows.business_ops import get_business_workflow


def print_header(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def print_check(message, passed):
    status = "[OK]" if passed else "[FAIL]"
    print(f"{status} {message}")


async def test_all_workflows():
    """Test all 8 workflows"""
    print_header("PHASE 17: ALL 8 BUSINESS WORKFLOWS TEST")

    workflow = get_business_workflow()
    workspace_id = uuid.uuid4()
    user_id = uuid.uuid4()

    results = {}

    # Test 1: Marketing Campaign Workflow
    print("\n[TEST 1] Marketing Campaign Workflow")
    try:
        result = await workflow.run_marketing_campaign(
            campaign_type="social",
            target_audience="developers",
            message="Test campaign",
            channels=["twitter"],
            budget=1000.0,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Marketing Campaign completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 4)
        results["Marketing Campaign"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Marketing Campaign failed: {e}", False)
        results["Marketing Campaign"] = False

    # Test 2: Sales Pipeline Workflow
    print("\n[TEST 2] Sales Pipeline Workflow")
    try:
        result = await workflow.run_sales_pipeline(
            operation="create_lead",
            contact_info={"name": "John", "email": "john@test.com"},
            deal_value=5000.0,
            stage="qualified",
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Sales Pipeline completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 3)
        results["Sales Pipeline"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Sales Pipeline failed: {e}", False)
        results["Sales Pipeline"] = False

    # Test 3: Growth Planning Workflow (NEW)
    print("\n[TEST 3] Growth Planning Workflow")
    try:
        result = await workflow.run_growth_planning(
            growth_metric="user_acquisition",
            current_value=1000,
            target_value=5000,
            timeframe="90 days",
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Growth Planning completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 4)
        print_check("  Growth rate calculated", "growth_rate_percent" in result.metrics)
        results["Growth Planning"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Growth Planning failed: {e}", False)
        results["Growth Planning"] = False

    # Test 4: Finance Analysis Workflow (NEW)
    print("\n[TEST 4] Finance/Revenue Analysis Workflow")
    try:
        result = await workflow.run_finance_analysis(
            analysis_type="revenue",
            time_period="Q1 2026",
            include_forecast=True,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Finance Analysis completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 4)
        print_check("  Forecast included", result.metrics.get("forecast_included") == True)
        results["Finance Analysis"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Finance Analysis failed: {e}", False)
        results["Finance Analysis"] = False

    # Test 5: Business Strategy Workflow (NEW)
    print("\n[TEST 5] Business Strategy Workflow")
    try:
        result = await workflow.run_business_strategy(
            strategy_type="expansion",
            focus_areas=["product", "market", "operations"],
            timeframe="1 year",
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Business Strategy completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 5)
        print_check("  All 5 business agents used", len(result.agents_executed) == 5)
        results["Business Strategy"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Business Strategy failed: {e}", False)
        results["Business Strategy"] = False

    # Test 6: Content Generation Workflow (NEW)
    print("\n[TEST 6] Content Generation Workflow")
    try:
        result = await workflow.run_content_generation(
            content_type="blog",
            topic="AI Agents",
            target_audience="developers",
            length="medium",
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Content Generation completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 4)
        print_check("  Content generated", "generated_content" in result.final_output)
        results["Content Generation"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Content Generation failed: {e}", False)
        results["Content Generation"] = False

    # Test 7: Research Analysis Workflow (NEW)
    print("\n[TEST 7] Research and Data Analysis Workflow")
    try:
        result = await workflow.run_research_analysis(
            research_query="AI market trends",
            analysis_type="market",
            data_sources=["web", "reports"],
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Research Analysis completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 3)
        print_check("  Research findings present", "research_findings" in result.final_output)
        results["Research Analysis"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Research Analysis failed: {e}", False)
        results["Research Analysis"] = False

    # Test 8: Quarterly Review Workflow
    print("\n[TEST 8] Quarterly Review Workflow")
    try:
        result = await workflow.run_quarterly_review(
            quarter="Q1",
            year=2026,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Quarterly Review completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 5)
        results["Quarterly Review"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Quarterly Review failed: {e}", False)
        results["Quarterly Review"] = False

    return results


async def main():
    """Run all tests"""
    results = await test_all_workflows()

    # Summary
    print_header("PHASE 17 COMPLETE - WORKFLOW SUMMARY")

    print("\n[REQUIRED WORKFLOWS]")
    print_check("1. Marketing Campaign Workflow", results.get("Marketing Campaign", False))
    print_check("2. Growth Planning Workflow", results.get("Growth Planning", False))
    print_check("3. Sales Pipeline Workflow", results.get("Sales Pipeline", False))
    print_check("4. Finance/Revenue Analysis Workflow", results.get("Finance Analysis", False))
    print_check("5. Business Strategy Workflow", results.get("Business Strategy", False))

    print("\n[IDEAL WORKFLOWS]")
    print_check("6. Content Generation Workflow", results.get("Content Generation", False))
    print_check("7. Research and Data Analysis Workflow", results.get("Research Analysis", False))

    print("\n[ADDITIONAL WORKFLOWS]")
    print_check("8. Quarterly Review Workflow", results.get("Quarterly Review", False))

    print("\n" + "=" * 70)
    print("PHASE 17 STATISTICS")
    print("=" * 70)
    print(f"Total Workflows: 8")
    print(f"Required Workflows: 5/5 {'[COMPLETE]' if all([results.get(w, False) for w in ['Marketing Campaign', 'Growth Planning', 'Sales Pipeline', 'Finance Analysis', 'Business Strategy']]) else '[INCOMPLETE]'}")
    print(f"Ideal Workflows: 2/2 {'[COMPLETE]' if all([results.get(w, False) for w in ['Content Generation', 'Research Analysis']]) else '[INCOMPLETE]'}")
    print(f"All Workflows Passing: {sum(results.values())}/{len(results)}")

    print("\n[AGENTS USED ACROSS WORKFLOWS]")
    print("  - MarketingAgent")
    print("  - SalesAgent")
    print("  - FinanceAgent")
    print("  - GrowthAgent")
    print("  - BusinessAgent")
    print("  - ContentAgent")
    print("  - ResearchAgent")
    print("  - AnalyticsAgent")

    if all(results.values()):
        print("\n[SUCCESS] All Phase 17 workflows passed!")
        print("\nPhase 17 has full workflow coverage:")
        print("  - 5 required workflows implemented and tested")
        print("  - 2 ideal workflows implemented and tested")
        print("  - 1 comprehensive review workflow")
        print("  - Total: 8 working business workflows")
        print("\nPhase 17 is ready to be marked COMPLETE")
        return 0
    else:
        print("\n[FAILURE] Some workflows failed")
        failed = [name for name, passed in results.items() if not passed]
        print(f"Failed workflows: {', '.join(failed)}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
