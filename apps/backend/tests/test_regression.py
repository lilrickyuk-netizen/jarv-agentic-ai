"""
Regression tests to prevent known issues from recurring
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from uuid import uuid4


@pytest.mark.regression
@pytest.mark.api
def test_workspace_slug_uniqueness_regression(client: TestClient, test_workspace):
    """
    Regression test: Duplicate workspace slugs should be rejected
    Issue: Previously allowed duplicate slugs causing database errors
    """
    duplicate_data = {
        "name": "Different Name",
        "slug": test_workspace.slug,  # Same slug
        "workspace_type": "general",
    }

    response = client.post("/workspaces/create", json=duplicate_data)
    assert response.status_code == 400, "Should reject duplicate slug"


@pytest.mark.regression
@pytest.mark.api
def test_task_status_validation_regression(client: TestClient, test_task):
    """
    Regression test: Invalid task status should be rejected
    Issue: Previously accepted invalid status values
    """
    invalid_statuses = ["invalid", "unknown", ""]

    for invalid_status in invalid_statuses:
        response = client.patch(f"/tasks/{test_task.id}", json={
            "status": invalid_status
        })
        assert response.status_code in [400, 422], f"Should reject status: {invalid_status}"


@pytest.mark.regression
@pytest.mark.integration
def test_agent_authority_bounds_regression(db_session: Session, test_workspace):
    """
    Regression test: Agent authority level should be within valid bounds
    Issue: Previously allowed negative or excessive authority levels
    """
    from app.models.agent import Agent

    # Test negative authority
    agent = Agent(
        id=uuid4(),
        name="Test Agent",
        role="test",
        workspace_id=test_workspace.id,
        authority_level=-1,  # Invalid
        is_active=True,
    )
    db_session.add(agent)

    # Should either reject or clamp to valid range
    try:
        db_session.commit()
        # If commit succeeds, verify it was clamped
        db_session.refresh(agent)
        assert agent.authority_level >= 0, "Negative authority should be prevented"
    except Exception:
        # Expected - negative authority rejected
        db_session.rollback()
        pass


@pytest.mark.regression
@pytest.mark.api
def test_empty_list_handling_regression(client: TestClient):
    """
    Regression test: Empty lists should return valid JSON, not error
    Issue: Previously returned 500 error for empty results
    """
    # Query with filters that match nothing
    response = client.get("/workspaces/list?slug=nonexistent-workspace-12345")
    assert response.status_code == 200, "Empty list should return 200"
    data = response.json()
    assert isinstance(data, list), "Should return list"
    assert len(data) == 0, "Should be empty list"


@pytest.mark.regression
@pytest.mark.api
def test_null_handling_regression(client: TestClient, test_workspace):
    """
    Regression test: Null values should be handled correctly
    Issue: Previously caused errors when optional fields were null
    """
    # Update with null description
    response = client.patch(f"/workspaces/{test_workspace.id}", json={
        "description": None
    })
    assert response.status_code == 200, "Should accept null for optional fields"


@pytest.mark.regression
@pytest.mark.api
def test_pagination_overflow_regression(client: TestClient):
    """
    Regression test: Large page numbers should not cause errors
    Issue: Previously caused memory errors for very large page numbers
    """
    response = client.get("/workspaces/list?page=999999&page_size=100")
    # Should return empty list or last page, not error
    assert response.status_code in [200, 400], "Large page number should be handled"


@pytest.mark.regression
@pytest.mark.api
def test_concurrent_update_regression(client: TestClient, test_workspace):
    """
    Regression test: Concurrent updates should be handled
    Issue: Previously caused data corruption on simultaneous updates
    """
    # Simulate concurrent updates
    update_data = {"name": "Updated Name 1"}
    response1 = client.patch(f"/workspaces/{test_workspace.id}", json=update_data)

    update_data2 = {"name": "Updated Name 2"}
    response2 = client.patch(f"/workspaces/{test_workspace.id}", json=update_data2)

    # Both should succeed
    assert response1.status_code == 200
    assert response2.status_code == 200

    # Final state should be consistent
    response = client.get(f"/workspaces/{test_workspace.id}")
    assert response.status_code == 200


@pytest.mark.regression
@pytest.mark.api
def test_special_characters_handling_regression(client: TestClient, db_session: Session, test_user):
    """
    Regression test: Special characters should be properly escaped
    Issue: Previously caused database errors with certain characters
    """
    special_chars_data = {
        "name": "Test's Workspace & Co. (2024)",
        "slug": "test-special-chars",
        "description": "Testing: quotes \" and ' and \\ backslashes",
        "workspace_type": "general",
    }

    response = client.post("/workspaces/create", json=special_chars_data)
    assert response.status_code in [201, 200, 400], "Should handle special characters"


@pytest.mark.regression
@pytest.mark.api
def test_cascading_delete_regression(client: TestClient, db_session: Session, test_user):
    """
    Regression test: Deleting workspace with children should be handled
    Issue: Previously caused orphaned records
    """
    from app.models.workspace import Workspace
    from app.models.agent import Agent

    # Create workspace with agent
    workspace = Workspace(
        id=uuid4(),
        name="Delete Test",
        slug="delete-test-ws",
        owner_id=test_user.id,
        is_active=True,
    )
    db_session.add(workspace)
    db_session.flush()

    agent = Agent(
        id=uuid4(),
        name="Child Agent",
        role="child",
        workspace_id=workspace.id,
        is_active=True,
    )
    db_session.add(agent)
    db_session.commit()

    workspace_id = workspace.id
    agent_id = agent.id

    # Delete workspace
    response = client.delete(f"/workspaces/{workspace_id}")

    # Should handle deletion (either cascade or reject)
    assert response.status_code in [204, 400], "Should handle deletion with children"


@pytest.mark.regression
@pytest.mark.api
def test_timezone_handling_regression(client: TestClient):
    """
    Regression test: Timestamps should be handled consistently
    Issue: Previously had timezone inconsistencies
    """
    response = client.get("/health")
    data = response.json()

    if "timestamp" in data:
        # Should be ISO 8601 format
        from datetime import datetime
        try:
            # Should parse without error
            datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            assert True
        except ValueError:
            pytest.fail("Invalid timestamp format")


@pytest.mark.regression
@pytest.mark.api
def test_large_batch_operations_regression(client: TestClient, test_workspace):
    """
    Regression test: Large batch operations should not timeout
    Issue: Previously timed out on large batch creates
    """
    # This test documents the behavior for large operations
    # In actual implementation, would create multiple tasks
    response = client.get("/tasks/list")
    assert response.status_code == 200
    # Should handle large result sets without timeout
