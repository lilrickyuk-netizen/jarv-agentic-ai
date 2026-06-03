"""
Smoke tests for quick system verification
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.mark.smoke
def test_application_starts(client: TestClient):
    """Test that application starts and responds"""
    response = client.get("/health")
    assert response.status_code == 200


@pytest.mark.smoke
def test_database_connection(db_session: Session):
    """Test database connection is working"""
    from sqlalchemy import text
    result = db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.smoke
def test_critical_endpoints_respond(client: TestClient):
    """Test all critical endpoints respond"""
    critical_endpoints = [
        "/health",
        "/",
        "/workspaces/list",
        "/agents/list",
        "/tasks/list",
        "/tools/list",
    ]

    for endpoint in critical_endpoints:
        response = client.get(endpoint)
        assert response.status_code in [200, 401], f"{endpoint} failed with {response.status_code}"


@pytest.mark.smoke
def test_api_returns_json(client: TestClient):
    """Test API returns valid JSON"""
    response = client.get("/health")
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert isinstance(data, dict)


@pytest.mark.smoke
def test_workspace_crud_basics(client: TestClient, test_workspace):
    """Test basic workspace CRUD operations work"""
    # Read
    response = client.get(f"/workspaces/{test_workspace.id}")
    assert response.status_code == 200

    # Update
    response = client.patch(
        f"/workspaces/{test_workspace.id}",
        json={"name": "Updated Name"}
    )
    assert response.status_code == 200


@pytest.mark.smoke
def test_agent_crud_basics(client: TestClient, test_agent):
    """Test basic agent CRUD operations work"""
    # Read
    response = client.get(f"/agents/{test_agent.id}")
    assert response.status_code == 200

    # List
    response = client.get("/agents/list")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.smoke
def test_task_crud_basics(client: TestClient, test_task):
    """Test basic task CRUD operations work"""
    # Read
    response = client.get(f"/tasks/{test_task.id}")
    assert response.status_code == 200

    # Update status
    response = client.patch(
        f"/tasks/{test_task.id}",
        json={"status": "in_progress"}
    )
    assert response.status_code == 200


@pytest.mark.smoke
def test_error_handling_works(client: TestClient):
    """Test error handling returns proper responses"""
    from uuid import uuid4

    # Test 404 handling
    response = client.get(f"/workspaces/{uuid4()}")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


@pytest.mark.smoke
def test_stats_endpoints_work(client: TestClient, test_workspace, test_agent, test_task):
    """Test statistics endpoints return data"""
    endpoints = [
        "/workspaces/stats",
        "/agents/stats",
        "/tasks/stats",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.smoke
def test_models_can_be_created(db_session: Session, test_user):
    """Test that all primary models can be created"""
    from uuid import uuid4
    from app.models.workspace import Workspace
    from app.models.agent import Agent
    from app.models.task import Task

    # Create instances
    workspace = Workspace(
        id=uuid4(),
        name="Smoke Test WS",
        slug="smoke-test",
        owner_id=test_user.id,
        is_active=True,
    )
    db_session.add(workspace)
    db_session.flush()

    agent = Agent(
        id=uuid4(),
        name="Smoke Test Agent",
        role="smoke_test",
        workspace_id=workspace.id,
        is_active=True,
    )
    db_session.add(agent)
    db_session.flush()

    task = Task(
        id=uuid4(),
        title="Smoke Test Task",
        workspace_id=workspace.id,
        assigned_agent_id=agent.id,
        status="pending",
    )
    db_session.add(task)
    db_session.commit()

    # Verify creation
    assert workspace.id is not None
    assert agent.id is not None
    assert task.id is not None
