"""
Tests for agents API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.agent import Agent
from app.models.workspace import Workspace


@pytest.mark.api
@pytest.mark.integration
def test_list_agents(client: TestClient, test_agent: Agent):
    """Test listing agents"""
    response = client.get("/agents/list")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    # Check agent structure
    agent = data[0]
    assert "id" in agent
    assert "name" in agent
    assert "role" in agent
    assert agent["name"] == test_agent.name


@pytest.mark.api
@pytest.mark.integration
def test_get_agent_by_id(client: TestClient, test_agent: Agent):
    """Test getting agent by ID"""
    response = client.get(f"/agents/{test_agent.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == str(test_agent.id)
    assert data["name"] == test_agent.name
    assert data["role"] == test_agent.role
    assert data["authority_level"] == test_agent.authority_level


@pytest.mark.api
@pytest.mark.integration
def test_get_nonexistent_agent(client: TestClient):
    """Test getting non-existent agent returns 404"""
    from uuid import uuid4
    fake_id = uuid4()
    response = client.get(f"/agents/{fake_id}")
    assert response.status_code == 404


@pytest.mark.api
@pytest.mark.integration
def test_create_agent(client: TestClient, test_workspace: Workspace, db_session: Session):
    """Test creating a new agent"""
    agent_data = {
        "name": "New Test Agent",
        "role": "test_creator",
        "workspace_id": str(test_workspace.id),
        "authority_level": 3,
        "capabilities": ["read", "write"],
    }

    response = client.post("/agents/create", json=agent_data)
    assert response.status_code == 201
    data = response.json()

    assert data["name"] == agent_data["name"]
    assert data["role"] == agent_data["role"]
    assert "id" in data

    # Verify in database
    agent = db_session.query(Agent).filter(Agent.role == agent_data["role"]).first()
    assert agent is not None
    assert agent.name == agent_data["name"]


@pytest.mark.api
@pytest.mark.integration
def test_update_agent(client: TestClient, test_agent: Agent):
    """Test updating agent"""
    update_data = {
        "name": "Updated Agent Name",
        "is_active": False,
    }

    response = client.patch(f"/agents/{test_agent.id}", json=update_data)
    assert response.status_code == 200
    data = response.json()

    assert data["name"] == update_data["name"]
    assert data["is_active"] is False
    assert data["id"] == str(test_agent.id)


@pytest.mark.api
@pytest.mark.integration
def test_agent_stats(client: TestClient, test_agent: Agent):
    """Test agent statistics endpoint"""
    response = client.get("/agents/stats")
    assert response.status_code == 200
    data = response.json()

    assert "total_agents" in data
    assert "active_agents" in data
    assert data["total_agents"] >= 1


@pytest.mark.api
@pytest.mark.integration
def test_list_agents_by_workspace(client: TestClient, test_agent: Agent, test_workspace: Workspace):
    """Test listing agents filtered by workspace"""
    response = client.get(f"/agents/list?workspace_id={test_workspace.id}")
    assert response.status_code == 200
    data = response.json()

    # All returned agents should belong to the workspace
    for agent in data:
        assert agent["workspace_id"] == str(test_workspace.id)


@pytest.mark.api
@pytest.mark.integration
def test_delete_agent(client: TestClient, db_session: Session, test_workspace: Workspace):
    """Test deleting agent"""
    from uuid import uuid4

    # Create agent to delete
    agent = Agent(
        id=uuid4(),
        name="To Delete Agent",
        role="delete_test",
        workspace_id=test_workspace.id,
        is_active=True,
    )
    db_session.add(agent)
    db_session.commit()
    agent_id = agent.id

    # Delete it
    response = client.delete(f"/agents/{agent_id}")
    assert response.status_code == 204

    # Verify deleted
    deleted = db_session.query(Agent).filter(Agent.id == agent_id).first()
    assert deleted is None
