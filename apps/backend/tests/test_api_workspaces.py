"""
Tests for workspace API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.workspace import Workspace
from app.models.user import User

# Every API route requires sign-in (Repair 15a); these tests run as test_user, the owner of test_workspace.
pytestmark = pytest.mark.usefixtures("signed_in")


@pytest.mark.api
@pytest.mark.integration
def test_list_workspaces(client: TestClient, test_workspace: Workspace):
    """Test listing workspaces"""
    response = client.get("/api/workspaces/list")
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
    response = client.get(f"/api/workspaces/{test_workspace.id}")
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
    response = client.get(f"/api/workspaces/{fake_id}")
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

    response = client.post("/api/workspaces/create", json=workspace_data)
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

    response = client.post("/api/workspaces/create", json=workspace_data)
    assert response.status_code == 400


@pytest.mark.api
@pytest.mark.integration
def test_update_workspace(client: TestClient, test_workspace: Workspace):
    """Test updating workspace"""
    update_data = {
        "name": "Updated Workspace Name",
        "description": "Updated description",
    }

    response = client.patch(f"/api/workspaces/{test_workspace.id}", json=update_data)
    assert response.status_code == 200
    data = response.json()

    assert data["name"] == update_data["name"]
    assert data["description"] == update_data["description"]
    assert data["id"] == str(test_workspace.id)


@pytest.mark.api
@pytest.mark.integration
def test_workspace_stats(client: TestClient, test_workspace: Workspace):
    """Test workspace statistics endpoint"""
    response = client.get("/api/workspaces/stats")
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
    response = client.get("/api/workspaces/list?active_only=true")
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

    # A plain delete archives (reversible); nothing is removed
    archived = client.delete(f"/api/workspaces/{workspace_id}")
    assert archived.status_code == 200 and archived.json()["archived"] is True
    db_session.expire_all()
    kept = db_session.query(Workspace).filter(Workspace.id == workspace_id).first()
    assert kept is not None and kept.is_archived is True

    # Permanent deletion must be confirmed with the workspace's slug
    unconfirmed = client.delete(f"/api/workspaces/{workspace_id}", params={"permanent": "true"})
    assert unconfirmed.status_code == 400 and "confirm=to-delete" in unconfirmed.json()["detail"]
    response = client.delete(f"/api/workspaces/{workspace_id}", params={"permanent": "true", "confirm": "to-delete"})
    assert response.status_code == 200 and response.json()["deleted"] is True

    # Verify deleted
    db_session.expire_all()
    deleted = db_session.query(Workspace).filter(Workspace.id == workspace_id).first()
    assert deleted is None


@pytest.mark.api
@pytest.mark.integration
def test_move_workspace_folder(client: TestClient, db_session: Session, test_user: User):
    """A workspace can be pointed at a folder it was moved to; its history stays with it."""
    from pathlib import Path
    from uuid import uuid4
    from app.core.workspaces.fs_inspector import SANDBOX_CONTAINER_ROOT
    from app.models.operations import AuditLog

    tag = uuid4().hex[:8]
    for name in (f"old-{tag}", f"new-{tag}", f"taken-{tag}"):
        (Path(SANDBOX_CONTAINER_ROOT) / name).mkdir(parents=True, exist_ok=True)
    moving = Workspace(id=uuid4(), name="Moving", slug=f"moving-{tag}", owner_id=test_user.id, is_active=True,
                       config={"root_path": f"/test_workspaces/old-{tag}", "registered_via": "command_center"})
    taken = Workspace(id=uuid4(), name="Taken", slug=f"taken-{tag}", owner_id=test_user.id, is_active=True,
                      config={"root_path": f"/test_workspaces/taken-{tag}"})
    db_session.add_all([moving, taken])
    db_session.commit()

    shown = client.get(f"/api/workspaces/{moving.id}").json()
    assert shown["folder"] == f"/test_workspaces/old-{tag}"

    missing = client.patch(f"/api/workspaces/{moving.id}", json={"folder": f"/test_workspaces/gone-{tag}"})
    assert missing.status_code == 400 and "not an existing folder" in missing.json()["detail"]
    outside = client.patch(f"/api/workspaces/{moving.id}", json={"folder": "/etc"})
    assert outside.status_code == 400 and "outside the approved workspace root" in outside.json()["detail"]
    clash = client.patch(f"/api/workspaces/{moving.id}", json={"folder": f"/test_workspaces/taken-{tag}"})
    assert clash.status_code == 409 and "Taken" in clash.json()["detail"]

    moved = client.patch(f"/api/workspaces/{moving.id}", json={"folder": f"/test_workspaces/new-{tag}"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["folder"] == f"/test_workspaces/new-{tag}"
    db_session.expire_all()
    row = db_session.query(Workspace).filter(Workspace.id == moving.id).one()
    assert row.config["root_path"] == f"/test_workspaces/new-{tag}"
    assert row.config["container_path"].endswith(f"new-{tag}")
    assert row.config["registered_via"] == "command_center"
    audit = db_session.query(AuditLog).filter(AuditLog.action == "workspace.folder_moved").all()
    assert any(a.target_id == str(moving.id) and a.meta_data["to"] == f"/test_workspaces/new-{tag}" for a in audit)
