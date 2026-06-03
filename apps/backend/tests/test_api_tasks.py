"""
Tests for tasks API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.agent import Agent


@pytest.mark.api
@pytest.mark.integration
def test_list_tasks(client: TestClient, test_task: Task):
    """Test listing tasks"""
    response = client.get("/tasks/list")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    # Check task structure
    task = data[0]
    assert "id" in task
    assert "title" in task
    assert "status" in task


@pytest.mark.api
@pytest.mark.integration
def test_get_task_by_id(client: TestClient, test_task: Task):
    """Test getting task by ID"""
    response = client.get(f"/tasks/{test_task.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == str(test_task.id)
    assert data["title"] == test_task.title
    assert data["status"] == test_task.status


@pytest.mark.api
@pytest.mark.integration
def test_create_task(client: TestClient, test_workspace: Workspace, test_agent: Agent, db_session: Session):
    """Test creating a new task"""
    task_data = {
        "title": "New Test Task",
        "description": "Task created via API test",
        "workspace_id": str(test_workspace.id),
        "assigned_agent_id": str(test_agent.id),
        "priority": "high",
        "task_type": "coding",
    }

    response = client.post("/tasks/create", json=task_data)
    assert response.status_code == 201
    data = response.json()

    assert data["title"] == task_data["title"]
    assert data["priority"] == task_data["priority"]
    assert "id" in data


@pytest.mark.api
@pytest.mark.integration
def test_update_task_status(client: TestClient, test_task: Task):
    """Test updating task status"""
    update_data = {
        "status": "in_progress",
    }

    response = client.patch(f"/tasks/{test_task.id}", json=update_data)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "in_progress"
    assert data["id"] == str(test_task.id)


@pytest.mark.api
@pytest.mark.integration
def test_complete_task(client: TestClient, test_task: Task):
    """Test marking task as complete"""
    response = client.post(f"/tasks/{test_task.id}/complete")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "completed"
    assert "completed_at" in data


@pytest.mark.api
@pytest.mark.integration
def test_task_stats(client: TestClient, test_task: Task):
    """Test task statistics endpoint"""
    response = client.get("/tasks/stats")
    assert response.status_code == 200
    data = response.json()

    assert "total_tasks" in data
    assert "pending_tasks" in data
    assert "completed_tasks" in data
    assert data["total_tasks"] >= 1


@pytest.mark.api
@pytest.mark.integration
def test_list_tasks_by_status(client: TestClient, test_task: Task):
    """Test filtering tasks by status"""
    response = client.get("/tasks/list?status=pending")
    assert response.status_code == 200
    data = response.json()

    # All returned tasks should be pending
    for task in data:
        assert task["status"] == "pending"


@pytest.mark.api
@pytest.mark.integration
def test_list_tasks_by_workspace(client: TestClient, test_task: Task, test_workspace: Workspace):
    """Test filtering tasks by workspace"""
    response = client.get(f"/tasks/list?workspace_id={test_workspace.id}")
    assert response.status_code == 200
    data = response.json()

    # All returned tasks should belong to the workspace
    for task in data:
        assert task["workspace_id"] == str(test_workspace.id)
