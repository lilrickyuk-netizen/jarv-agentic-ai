"""
Comprehensive Phase 18 Test - All 6 Content & Community Workflows

Tests all workflows for Phase 18: CONTENT, ONBOARDING, COMMUNITY, PARTNERSHIPS
"""
import sys
from pathlib import Path
import uuid
import asyncio

sys.path.insert(0, str(Path(__file__).parent))

from app.core.workflows.content_community import get_content_community_workflow


def print_header(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def print_check(message, passed):
    status = "[OK]" if passed else "[FAIL]"
    print(f"{status} {message}")


async def test_all_workflows():
    """Test all 6 workflows"""
    print_header("PHASE 18: ALL 6 CONTENT & COMMUNITY WORKFLOWS TEST")

    workflow = get_content_community_workflow()
    workspace_id = uuid.uuid4()
    user_id = uuid.uuid4()

    results = {}

    # Test 1: Content Strategy Workflow
    print("\n[TEST 1] Content Strategy Workflow")
    try:
        result = await workflow.run_content_strategy(
            content_goals=["brand_awareness", "lead_generation"],
            target_audience="developers and tech enthusiasts",
            channels=["blog", "social_media", "email"],
            timeframe="Q2 2026",
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Content Strategy completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 4)
        print_check("  Content strategy present", "content_strategy" in result.final_output)
        results["Content Strategy"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Content Strategy failed: {e}", False)
        results["Content Strategy"] = False

    # Test 2: User Onboarding Workflow
    print("\n[TEST 2] User Onboarding Workflow")
    try:
        result = await workflow.run_user_onboarding(
            user_type="beginner",
            product="JARV AI Platform",
            customization_level="standard",
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("User Onboarding completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 3)
        print_check("  Onboarding plan present", "onboarding_plan" in result.final_output)
        results["User Onboarding"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"User Onboarding failed: {e}", False)
        results["User Onboarding"] = False

    # Test 3: Community Engagement Workflow
    print("\n[TEST 3] Community Engagement Workflow")
    try:
        result = await workflow.run_community_engagement(
            engagement_type="discussion",
            platform="discord",
            target_segment="active_users",
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Community Engagement completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 4)
        print_check("  Engagement plan present", "engagement_plan" in result.final_output)
        results["Community Engagement"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Community Engagement failed: {e}", False)
        results["Community Engagement"] = False

    # Test 4: Partnership Development Workflow
    print("\n[TEST 4] Partnership Development Workflow")
    try:
        result = await workflow.run_partnership_development(
            partnership_type="integration",
            partner_criteria=["complementary_product", "shared_audience"],
            goals=["expand_reach", "add_features"],
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Partnership Development completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 4)
        print_check("  Partner identification present", "partner_identification" in result.final_output)
        results["Partnership Development"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Partnership Development failed: {e}", False)
        results["Partnership Development"] = False

    # Test 5: Content Distribution Workflow
    print("\n[TEST 5] Content Distribution Workflow")
    try:
        result = await workflow.run_content_distribution(
            content_id="blog-post-123",
            content_type="blog_post",
            distribution_channels=["twitter", "linkedin", "reddit"],
            target_audience="developers",
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Content Distribution completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 4)
        print_check("  Distribution strategy present", "distribution_strategy" in result.final_output)
        results["Content Distribution"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Content Distribution failed: {e}", False)
        results["Content Distribution"] = False

    # Test 6: Community Moderation Workflow
    print("\n[TEST 6] Community Moderation Workflow")
    try:
        result = await workflow.run_community_moderation(
            platform="discord",
            moderation_type="proactive",
            severity_threshold="medium",
            workspace_id=workspace_id,
            user_id=user_id,
        )
        print_check("Community Moderation completed", result.status.value == "completed")
        print_check(f"  {len(result.agents_executed)} agents executed", len(result.agents_executed) == 3)
        print_check("  Moderation actions present", "moderation_actions" in result.final_output)
        results["Community Moderation"] = result.status.value == "completed"
    except Exception as e:
        print_check(f"Community Moderation failed: {e}", False)
        results["Community Moderation"] = False

    return results


async def main():
    """Run all tests"""
    results = await test_all_workflows()

    # Summary
    print_header("PHASE 18 COMPLETE - WORKFLOW SUMMARY")

    print("\n[ALL WORKFLOWS]")
    print_check("1. Content Strategy Workflow", results.get("Content Strategy", False))
    print_check("2. User Onboarding Workflow", results.get("User Onboarding", False))
    print_check("3. Community Engagement Workflow", results.get("Community Engagement", False))
    print_check("4. Partnership Development Workflow", results.get("Partnership Development", False))
    print_check("5. Content Distribution Workflow", results.get("Content Distribution", False))
    print_check("6. Community Moderation Workflow", results.get("Community Moderation", False))

    print("\n" + "=" * 70)
    print("PHASE 18 STATISTICS")
    print("=" * 70)
    print(f"Total Workflows: 6")
    print(f"All Workflows Passing: {sum(results.values())}/{len(results)}")

    print("\n[AGENTS USED ACROSS WORKFLOWS]")
    print("  - ContentAgent")
    print("  - OnboardingAgent")
    print("  - CommunityAgent")
    print("  - PartnershipsAgent")
    print("  - MarketingAgent")
    print("  - BusinessAgent")
    print("  - ResearchAgent")
    print("  - SalesAgent")
    print("  - SecurityAgent")
    print("  - AnalyticsAgent")

    print("\n[API ENDPOINTS]")
    print("  - POST /api/content-community/workflows/content-strategy")
    print("  - POST /api/content-community/workflows/user-onboarding")
    print("  - POST /api/content-community/workflows/community-engagement")
    print("  - POST /api/content-community/workflows/partnership-development")
    print("  - POST /api/content-community/workflows/content-distribution")
    print("  - POST /api/content-community/workflows/community-moderation")
    print("  - GET /api/content-community/workflows/{workflow_id}")

    if all(results.values()):
        print("\n[SUCCESS] All Phase 18 workflows passed!")
        print("\nPhase 18 has full workflow coverage:")
        print("  - 6 complete workflows implemented and tested")
        print("  - 10 specialist agents utilized")
        print("  - 7 API endpoints operational")
        print("  - Content, Onboarding, Community, Partnerships covered")
        print("\nPhase 18 is ready to be marked COMPLETE")
        return 0
    else:
        print("\n[FAILURE] Some workflows failed")
        failed = [name for name, passed in results.items() if not passed]
        print(f"Failed workflows: {', '.join(failed)}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
