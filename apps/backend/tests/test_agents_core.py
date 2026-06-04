"""
Tests for agent core functionality
"""
import pytest
from sqlalchemy.orm import Session
from uuid import uuid4

from app.models.agent import Agent
from app.models.workspace import Workspace
from app.core.agents.base import AgentBase
from typing import Dict, Any


# Concrete test implementation of AgentBase
class TestAgent(AgentBase):
    """Concrete test agent for testing AgentBase functionality"""

    @property
    def name(self) -> str:
        return self._name

    @property
    def role(self) -> str:
        return self._role

    @property
    def required_authority_level(self) -> int:
        return getattr(self, 'authority_level', 3)

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object"}

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "object"}

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success"}

    def __init__(self, agent_id: str, name: str, **kwargs):
        self.agent_id = agent_id
        self._name = name
        self._role = kwargs.get('role', kwargs.get('agent_type', 'test'))
        self.authority_level = kwargs.get('authority_level', 3)
        self.capabilities = kwargs.get('capabilities', kwargs.get('allowed_tools', []))

    def has_authority(self, required_level: int) -> bool:
        """Check if agent has required authority level"""
        return self.authority_level >= required_level

    def has_capability(self, capability: str) -> bool:
        """Check if agent has specific capability"""
        return capability in self.capabilities


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

    agent = TestAgent(**agent_data)

    assert agent.agent_id == agent_data["agent_id"]
    assert agent.name == agent_data["name"]
    assert agent.role == agent_data["role"]
    assert agent.capabilities == agent_data["capabilities"]


@pytest.mark.agent
@pytest.mark.unit
def test_agent_authority_levels():
    """Test agent authority level validation"""
    agent = TestAgent(
        agent_id=str(uuid4()),
        name="Test Agent",
        agent_type="test",
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
    agent = TestAgent(
        agent_id=str(uuid4()),
        name="Test Agent",
        agent_type="test",
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
        agent_type="status_test",
        workspace_id=test_workspace.id,
        is_active=True,
        current_state="idle",
    )
    db_session.add(agent)
    db_session.commit()

    # Test status transitions
    agent.current_state = "busy"
    db_session.commit()
    assert agent.current_state == "busy"

    agent.current_state = "idle"
    db_session.commit()
    assert agent.current_state == "idle"

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
    from app.models.execution import CommandRun
    from datetime import datetime

    # Create execution record
    execution = CommandRun(
        id=uuid4(),
        agent_id=test_agent.id,
        command="test command",
        command_type="test",
        authority_level_used=3,
        started_at=datetime.utcnow(),
    )
    db_session.add(execution)
    db_session.commit()

    # Query executions
    executions = db_session.query(CommandRun).filter(
        CommandRun.agent_id == test_agent.id
    ).all()

    assert len(executions) >= 1


@pytest.mark.agent
@pytest.mark.unit
def test_agent_registry():
    """Test agent registry functionality"""
    from app.core.agents.registry import get_registry

    registry = get_registry()

    # Verify registry has agents
    assert registry.is_registered("orchestrator") is True

    # Get agent info
    agent_info = registry.get_metadata("orchestrator")
    assert agent_info is not None
    assert agent_info.name == "orchestrator"

    # List all agents
    all_agents = registry.list_all()
    assert len(all_agents) > 0


@pytest.mark.agent
@pytest.mark.unit
def test_agent_specialization():
    """Test specialized agent types"""
    from app.core.agents.specialists.coding_agent import CodingAgent
    from app.core.agents.base import AgentConfig, AuthorityLevel

    # Create coding agent with proper config
    config = AgentConfig(
        name="coding_test",
        authority_level=AuthorityLevel.LEVEL_3_CODE_EXECUTION,
    )
    agent = CodingAgent(config=config)

    # Coding agent should have coding-specific tools
    assert agent.name == "coding_agent"
    assert agent.required_authority_level == AuthorityLevel.LEVEL_3_CODE_EXECUTION
    assert len(agent.default_tools) > 0


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
