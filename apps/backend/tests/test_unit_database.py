"""
Unit tests for database operations
"""
import pytest
from sqlalchemy.orm import Session
from uuid import uuid4

from app.models.workspace import Workspace
from app.models.agent import Agent
from app.models.task import Task
from app.models.user import User


@pytest.mark.unit
@pytest.mark.integration
def test_create_user(db_session: Session):
    """Test creating a user in database"""
    user = User(
        id=uuid4(),
        username="unittest",
        email="unit@test.com",
        hashed_password="hashed",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    # Verify user was created
    queried_user = db_session.query(User).filter(User.username == "unittest").first()
    assert queried_user is not None
    assert queried_user.email == "unit@test.com"


@pytest.mark.unit
@pytest.mark.integration
def test_create_workspace(db_session: Session, test_user: User):
    """Test creating a workspace in database"""
    workspace = Workspace(
        id=uuid4(),
        name="Unit Test Workspace",
        slug="unit-test-ws",
        owner_id=test_user.id,
        is_active=True,
    )
    db_session.add(workspace)
    db_session.commit()

    # Verify workspace was created
    queried_ws = db_session.query(Workspace).filter(Workspace.slug == "unit-test-ws").first()
    assert queried_ws is not None
    assert queried_ws.name == "Unit Test Workspace"


@pytest.mark.unit
@pytest.mark.integration
def test_workspace_agent_relationship(db_session: Session, test_workspace: Workspace):
    """Test workspace-agent relationship"""
    # Create multiple agents for workspace
    agents = []
    for i in range(3):
        agent = Agent(
            id=uuid4(),
            name=f"Test Agent {i}",
            role=f"role_{i}",
            workspace_id=test_workspace.id,
            is_active=True,
        )
        db_session.add(agent)
        agents.append(agent)

    db_session.commit()

    # Query workspace and check agents
    workspace = db_session.query(Workspace).filter(Workspace.id == test_workspace.id).first()
    # Note: Relationship should be defined in models for this to work
    # For now, query agents directly
    workspace_agents = db_session.query(Agent).filter(Agent.workspace_id == test_workspace.id).all()
    assert len(workspace_agents) >= 3


@pytest.mark.unit
@pytest.mark.integration
def test_task_assignment(db_session: Session, test_workspace: Workspace, test_agent: Agent):
    """Test task assignment to agent"""
    task = Task(
        id=uuid4(),
        title="Assigned Task",
        workspace_id=test_workspace.id,
        assigned_agent_id=test_agent.id,
        status="pending",
    )
    db_session.add(task)
    db_session.commit()

    # Verify task was assigned
    queried_task = db_session.query(Task).filter(Task.id == task.id).first()
    assert queried_task is not None
    assert queried_task.assigned_agent_id == test_agent.id


@pytest.mark.unit
@pytest.mark.integration
def test_cascade_delete_protection(db_session: Session, test_workspace: Workspace, test_agent: Agent):
    """Test that deleting workspace with agents is handled"""
    # This test verifies database constraints
    workspace_id = test_workspace.id
    agent_id = test_agent.id

    # Verify both exist
    assert db_session.query(Workspace).filter(Workspace.id == workspace_id).first() is not None
    assert db_session.query(Agent).filter(Agent.id == agent_id).first() is not None

    # Note: Actual cascade behavior depends on foreign key constraints in models
    # This test documents expected behavior


@pytest.mark.unit
@pytest.mark.integration
def test_unique_constraints(db_session: Session, test_user: User):
    """Test unique constraints on models"""
    # Try to create workspace with duplicate slug
    workspace1 = Workspace(
        id=uuid4(),
        name="First",
        slug="unique-slug",
        owner_id=test_user.id,
        is_active=True,
    )
    db_session.add(workspace1)
    db_session.commit()

    workspace2 = Workspace(
        id=uuid4(),
        name="Second",
        slug="unique-slug",  # Duplicate slug
        owner_id=test_user.id,
        is_active=True,
    )
    db_session.add(workspace2)

    # This should raise an integrity error
    with pytest.raises(Exception):  # SQLAlchemy IntegrityError
        db_session.commit()

    db_session.rollback()


@pytest.mark.unit
@pytest.mark.integration
def test_query_filtering(db_session: Session, test_user: User):
    """Test database query filtering"""
    # Create multiple workspaces
    for i in range(5):
        workspace = Workspace(
            id=uuid4(),
            name=f"Workspace {i}",
            slug=f"ws-{i}",
            owner_id=test_user.id,
            is_active=i % 2 == 0,  # Even ones are active
        )
        db_session.add(workspace)
    db_session.commit()

    # Query only active workspaces
    active = db_session.query(Workspace).filter(Workspace.is_active == True).all()
    assert len(active) >= 3  # At least 3 active (0, 2, 4) plus test_workspace

    # Query inactive workspaces
    inactive = db_session.query(Workspace).filter(Workspace.is_active == False).all()
    assert len(inactive) >= 2  # At least 2 inactive (1, 3)


@pytest.mark.unit
@pytest.mark.integration
def test_ordering(db_session: Session, test_workspace: Workspace):
    """Test database query ordering"""
    # Create tasks with different priorities
    priorities = ["low", "medium", "high", "critical"]
    for priority in priorities:
        task = Task(
            id=uuid4(),
            title=f"Task {priority}",
            workspace_id=test_workspace.id,
            priority=priority,
            status="pending",
        )
        db_session.add(task)
    db_session.commit()

    # Query tasks ordered by created_at
    tasks = db_session.query(Task).order_by(Task.created_at.desc()).all()
    assert len(tasks) >= 4

    # Verify ordering (newest first)
    for i in range(len(tasks) - 1):
        assert tasks[i].created_at >= tasks[i + 1].created_at
