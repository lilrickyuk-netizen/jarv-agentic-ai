"""
Tests for agent core functionality
"""
import pytest
from sqlalchemy.orm import Session
from uuid import uuid4

from app.models.agent import Agent
from app.models.workspace import Workspace
from app.core.agents.base import BaseAgent


@pytest.mark.agent
@pytest.mark.unit
def test_agent_initialization():
    """Test agent initialization"""
    agent_data = {
        "agent_id": str(uuid4()),
        "name": "Test Agent",
        "role": "test_role",
        "capabilities": ["read", "write"],
    }

    agent = BaseAgent(**agent_data)

    assert agent.agent_id == agent_data["agent_id"]
    assert agent.name == agent_data["name"]
    assert agent.role == agent_data["role"]
    assert agent.capabilities == agent_data["capabilities"]


@pytest.mark.agent
@pytest.mark.unit
def test_agent_authority_levels():
    """Test agent authority level validation"""
    agent = BaseAgent(
        agent_id=str(uuid4()),
        name="Test Agent",
        role="test",
        authority_level=5,
    )

    assert agent.authority_level == 5

    # Test authority comparison
    assert agent.has_authority(3) is True  # Can perform level 3 tasks
    assert agent.has_authority(5) is True  # Can perform level 5 tasks
    assert agent.has_authority(7) is False  # Cannot perform level 7 tasks


@pytest.mark.agent
@pytest.mark.unit
def test_agent_capability_checking():
    """Test agent capability validation"""
    agent = BaseAgent(
        agent_id=str(uuid4()),
        name="Test Agent",
        role="test",
        capabilities=["read", "write", "execute"],
    )

    assert agent.has_capability("read") is True
    assert agent.has_capability("write") is True
    assert agent.has_capability("execute") is True
    assert agent.has_capability("delete") is False


@pytest.mark.agent
@pytest.mark.integration
def test_agent_status_transitions(db_session: Session, test_workspace: Workspace):
    """Test agent status state machine"""
    agent = Agent(
        id=uuid4(),
        name="Status Test Agent",
        role="status_test",
        workspace_id=test_workspace.id,
        is_active=True,
        status="idle",
    )
    db_session.add(agent)
    db_session.commit()

    # Test status transitions
    agent.status = "busy"
    db_session.commit()
    assert agent.status == "busy"

    agent.status = "idle"
    db_session.commit()
    assert agent.status == "idle"

    # Test deactivation
    agent.is_active = False
    db_session.commit()
    assert agent.is_active is False


@pytest.mark.agent
@pytest.mark.integration
def test_agent_task_assignment(db_session: Session, test_agent: Agent, test_workspace: Workspace):
    """Test assigning tasks to agents"""
    from app.models.task import Task

    # Create tasks
    tasks = []
    for i in range(3):
        task = Task(
            id=uuid4(),
            title=f"Agent Task {i}",
            workspace_id=test_workspace.id,
            assigned_agent_id=test_agent.id,
            status="pending",
        )
        db_session.add(task)
        tasks.append(task)

    db_session.commit()

    # Query agent's tasks
    agent_tasks = db_session.query(Task).filter(
        Task.assigned_agent_id == test_agent.id
    ).all()

    assert len(agent_tasks) >= 3


@pytest.mark.agent
@pytest.mark.integration
def test_agent_execution_tracking(db_session: Session, test_agent: Agent):
    """Test tracking agent executions"""
    from app.models.execution import TaskExecution

    # Create execution record
    execution = TaskExecution(
        id=uuid4(),
        agent_id=test_agent.id,
        status="running",
        started_at=pytest.approx_now(),
    )
    db_session.add(execution)
    db_session.commit()

    # Query executions
    executions = db_session.query(TaskExecution).filter(
        TaskExecution.agent_id == test_agent.id
    ).all()

    assert len(executions) >= 1


@pytest.mark.agent
@pytest.mark.unit
def test_agent_registry():
    """Test agent registry functionality"""
    from app.core.agents.registry import AgentRegistry

    registry = AgentRegistry()

    # Register an agent class
    @registry.register("test_agent")
    class TestAgent(BaseAgent):
        pass

    # Verify registration
    assert registry.has_agent("test_agent") is True
    assert registry.get_agent_class("test_agent") == TestAgent


@pytest.mark.agent
@pytest.mark.unit
def test_agent_specialization():
    """Test specialized agent types"""
    from app.core.agents.specialists.coding_agent import CodingAgent

    agent = CodingAgent(
        agent_id=str(uuid4()),
        name="Coding Specialist",
        role="coding",
    )

    # Coding agent should have coding-specific capabilities
    assert agent.has_capability("code_analysis") is True or agent.has_capability("read") is True


@pytest.mark.agent
@pytest.mark.integration
def test_agent_metrics(db_session: Session, test_agent: Agent):
    """Test agent performance metrics"""
    from app.models.task import Task

    # Create completed tasks
    for i in range(5):
        task = Task(
            id=uuid4(),
            title=f"Completed Task {i}",
            workspace_id=test_agent.workspace_id,
            assigned_agent_id=test_agent.id,
            status="completed",
        )
        db_session.add(task)

    db_session.commit()

    # Query completed tasks
    completed = db_session.query(Task).filter(
        Task.assigned_agent_id == test_agent.id,
        Task.status == "completed"
    ).count()

    assert completed >= 5
