"""
Tests for workspace API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.workspace import Workspace
from app.models.user import User


@pytest.mark.api
@pytest.mark.integration
def test_list_workspaces(client: TestClient, test_workspace: Workspace):
    """Test listing workspaces"""
    response = client.get("/workspaces/list")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    # Check workspace structure
    workspace = data[0]
    assert "id" in workspace
    assert "name" in workspace
    assert "slug" in workspace
    assert workspace["name"] == test_workspace.name


@pytest.mark.api
@pytest.mark.integration
def test_get_workspace_by_id(client: TestClient, test_workspace: Workspace):
    """Test getting workspace by ID"""
    response = client.get(f"/workspaces/{test_workspace.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == str(test_workspace.id)
    assert data["name"] == test_workspace.name
    assert data["slug"] == test_workspace.slug
    assert data["authority_level"] == test_workspace.authority_level


@pytest.mark.api
@pytest.mark.integration
def test_get_nonexistent_workspace(client: TestClient):
    """Test getting non-existent workspace returns 404"""
    from uuid import uuid4
    fake_id = uuid4()
    response = client.get(f"/workspaces/{fake_id}")
    assert response.status_code == 404


@pytest.mark.api
@pytest.mark.integration
def test_create_workspace(client: TestClient, db_session: Session, test_user: User):
    """Test creating a new workspace"""
    workspace_data = {
        "name": "New Test Workspace",
        "slug": "new-test-workspace",
        "description": "Created via API test",
        "workspace_type": "general",
        "authority_level": 5,
    }

    response = client.post("/workspaces/create", json=workspace_data)
    assert response.status_code == 201
    data = response.json()

    assert data["name"] == workspace_data["name"]
    assert data["slug"] == workspace_data["slug"]
    assert "id" in data

    # Verify in database
    workspace = db_session.query(Workspace).filter(
        Workspace.slug == workspace_data["slug"]
    ).first()
    assert workspace is not None
    assert workspace.name == workspace_data["name"]


@pytest.mark.api
@pytest.mark.integration
def test_create_workspace_duplicate_slug(client: TestClient, test_workspace: Workspace):
    """Test creating workspace with duplicate slug fails"""
    workspace_data = {
        "name": "Duplicate Workspace",
        "slug": test_workspace.slug,  # Use existing slug
        "description": "Should fail",
        "workspace_type": "general",
    }

    response = client.post("/workspaces/create", json=workspace_data)
    assert response.status_code == 400


@pytest.mark.api
@pytest.mark.integration
def test_update_workspace(client: TestClient, test_workspace: Workspace):
    """Test updating workspace"""
    update_data = {
        "name": "Updated Workspace Name",
        "description": "Updated description",
    }

    response = client.patch(f"/workspaces/{test_workspace.id}", json=update_data)
    assert response.status_code == 200
    data = response.json()

    assert data["name"] == update_data["name"]
    assert data["description"] == update_data["description"]
    assert data["id"] == str(test_workspace.id)


@pytest.mark.api
@pytest.mark.integration
def test_workspace_stats(client: TestClient, test_workspace: Workspace):
    """Test workspace statistics endpoint"""
    response = client.get("/workspaces/stats")
    assert response.status_code == 200
    data = response.json()

    assert "total_workspaces" in data
    assert "active_workspaces" in data
    assert "archived_workspaces" in data
    assert data["total_workspaces"] >= 1


@pytest.mark.api
@pytest.mark.integration
def test_list_workspaces_active_only(client: TestClient, test_workspace: Workspace):
    """Test listing only active workspaces"""
    response = client.get("/workspaces/list?active_only=true")
    assert response.status_code == 200
    data = response.json()

    # All returned workspaces should be active
    for workspace in data:
        assert workspace["is_active"] is True


@pytest.mark.api
@pytest.mark.integration
def test_delete_workspace(client: TestClient, db_session: Session, test_user: User):
    """Test deleting workspace"""
    from uuid import uuid4

    # Create workspace to delete
    workspace = Workspace(
        id=uuid4(),
        name="To Delete",
        slug="to-delete",
        owner_id=test_user.id,
        is_active=True,
    )
    db_session.add(workspace)
    db_session.commit()
    workspace_id = workspace.id

    # Delete it
    response = client.delete(f"/workspaces/{workspace_id}")
    assert response.status_code == 204

    # Verify deleted
    deleted = db_session.query(Workspace).filter(Workspace.id == workspace_id).first()
    assert deleted is None
