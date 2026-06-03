"""
Test script for coding debug build loop workflow.
"""
import asyncio
import sys
import uuid
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.workflows.coding_loop import run_coding_loop, LoopStatus


async def test_coding_loop():
    """Test the coding debug build loop"""
    print("="*70)
    print("TESTING CODING DEBUG BUILD LOOP")
    print("="*70)
    print()

    # Test case: Simple API endpoint creation
    task = "Create a FastAPI endpoint for user registration"
    language = "python"
    requirements = "Use Pydantic models, hash passwords, validate email"
    workspace_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    print(f"Task: {task}")
    print(f"Language: {language}")
    print(f"Requirements: {requirements}")
    print()
    print("Starting coding loop...")
    print("-"*70)
    print()

    try:
        result = await run_coding_loop(
            task=task,
            language=language,
            workspace_id=workspace_id,
            session_id=session_id,
            requirements=requirements,
            max_iterations=3,
            quality_threshold=80.0,
            coverage_threshold=75.0,
        )

        print("="*70)
        print("LOOP COMPLETED")
        print("="*70)
        print(f"Status: {result.status.value}")
        print(f"Total iterations: {result.total_iterations}")
        print(f"Final code quality: {result.final_code_quality}%")
        print(f"Test coverage: {result.test_coverage}%")
        print(f"Errors fixed: {result.errors_fixed}")
        print()

        print("ITERATIONS:")
        print("-"*70)
        for iteration in result.iterations:
            print(f"Iteration {iteration.iteration_number}:")
            print(f"  Agent: {iteration.agent_used}")
            print(f"  Action: {iteration.action_taken}")
            print(f"  Success: {iteration.success}")
            if iteration.errors:
                print(f"  Errors: {', '.join(iteration.errors)}")
            print()

        print("FINAL OUTPUT:")
        print("-"*70)
        print(result.final_output)
        print()

        # Check success
        if result.status == LoopStatus.SUCCESS:
            print("[OK] Coding loop succeeded!")
            return True
        elif result.status == LoopStatus.MAX_ITERATIONS:
            print("[PARTIAL] Maximum iterations reached")
            return True
        else:
            print("[FAILED] Coding loop failed")
            return False

    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_multiple_scenarios():
    """Test multiple coding scenarios"""
    print("\n" + "="*70)
    print("TESTING MULTIPLE SCENARIOS")
    print("="*70)
    print()

    scenarios = [
        {
            "name": "Simple function",
            "task": "Create a function to check if a number is prime",
            "language": "python",
            "requirements": "Include docstring and type hints",
        },
        {
            "name": "REST API endpoint",
            "task": "Create a POST endpoint for creating blog posts",
            "language": "python",
            "requirements": "Use FastAPI, Pydantic models, async",
        },
        {
            "name": "Data validation",
            "task": "Create email validation function",
            "language": "python",
            "requirements": "Use regex, handle edge cases",
        },
    ]

    results = []
    for i, scenario in enumerate(scenarios, 1):
        print(f"\nSCENARIO {i}: {scenario['name']}")
        print("-"*70)

        try:
            result = await run_coding_loop(
                task=scenario["task"],
                language=scenario["language"],
                workspace_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                requirements=scenario["requirements"],
                max_iterations=2,
            )

            success = result.status in [LoopStatus.SUCCESS, LoopStatus.MAX_ITERATIONS]
            results.append({
                "scenario": scenario["name"],
                "status": result.status.value,
                "iterations": result.total_iterations,
                "quality": result.final_code_quality,
                "success": success,
            })

            status_mark = "[OK]" if success else "[FAIL]"
            print(f"{status_mark} {scenario['name']}: {result.status.value} "
                  f"({result.total_iterations} iterations, {result.final_code_quality}% quality)")

        except Exception as e:
            print(f"[ERROR] {scenario['name']} failed: {e}")
            results.append({
                "scenario": scenario["name"],
                "status": "error",
                "success": False,
            })

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    successful = sum(1 for r in results if r.get("success"))
    print(f"Scenarios passed: {successful}/{len(scenarios)}")

    for result in results:
        status = "[OK]" if result.get("success") else "[FAIL]"
        print(f"{status} {result['scenario']}: {result['status']}")

    return successful == len(scenarios)


async def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("CODING DEBUG BUILD LOOP - COMPREHENSIVE TEST")
    print("="*70)
    print()

    # Test 1: Basic coding loop
    test1_passed = await test_coding_loop()

    # Test 2: Multiple scenarios
    test2_passed = await test_multiple_scenarios()

    # Final result
    print("\n" + "="*70)
    print("FINAL TEST RESULTS")
    print("="*70)
    print(f"Basic coding loop: {'PASSED' if test1_passed else 'FAILED'}")
    print(f"Multiple scenarios: {'PASSED' if test2_passed else 'FAILED'}")
    print()

    if test1_passed and test2_passed:
        print("[SUCCESS] All tests passed!")
        return 0
    else:
        print("[FAILURE] Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
