#!/usr/bin/env python
"""
JARV Backend Worker Test Script

Tests the Celery worker queue by submitting test tasks.

Usage:
    python scripts/test_worker.py
"""
import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workers.tasks import test_task, async_test_task, health_check_task
from app.core.config import settings


def test_sync_task():
    """Test synchronous task"""
    print("\n" + "=" * 60)
    print("Testing Synchronous Task")
    print("=" * 60)

    # Submit task
    result = test_task.apply_async(
        args=["Testing JARV worker queue"],
        countdown=0,
    )

    print(f"Task submitted: {result.id}")
    print(f"Task status: {result.status}")

    # Wait for result (timeout 10 seconds)
    try:
        task_result = result.get(timeout=10)
        print(f"\nTask completed successfully!")
        print(f"Result: {task_result}")
        return True
    except Exception as e:
        print(f"\nTask failed: {e}")
        return False


def test_async_task():
    """Test asynchronous task"""
    print("\n" + "=" * 60)
    print("Testing Asynchronous Task")
    print("=" * 60)

    # Submit task
    result = async_test_task.apply_async(
        args=["Testing JARV async worker"],
        countdown=0,
    )

    print(f"Task submitted: {result.id}")
    print(f"Task status: {result.status}")

    # Wait for result (timeout 15 seconds)
    try:
        task_result = result.get(timeout=15)
        print(f"\nTask completed successfully!")
        print(f"Result: {task_result}")
        return True
    except Exception as e:
        print(f"\nTask failed: {e}")
        return False


def test_health_check():
    """Test worker health check"""
    print("\n" + "=" * 60)
    print("Testing Worker Health Check")
    print("=" * 60)

    # Submit task
    result = health_check_task.apply_async()

    print(f"Task submitted: {result.id}")

    # Wait for result (timeout 5 seconds)
    try:
        task_result = result.get(timeout=5)
        print(f"\nHealth check completed!")
        print(f"Result: {task_result}")
        return True
    except Exception as e:
        print(f"\nHealth check failed: {e}")
        return False


def main():
    """Run all worker tests"""
    print("=" * 60)
    print("JARV Backend Worker Queue Test")
    print("=" * 60)
    print(f"Environment: {settings.ENVIRONMENT}")
    print(f"Redis URL: {settings.REDIS_URL}")
    print("=" * 60)

    results = {
        "health_check": test_health_check(),
        "sync_task": test_sync_task(),
        "async_task": test_async_task(),
    }

    # Print summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for test_name, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        print(f"{test_name}: {status}")

    all_passed = all(results.values())
    print("=" * 60)
    if all_passed:
        print("All tests passed!")
        sys.exit(0)
    else:
        print("Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
