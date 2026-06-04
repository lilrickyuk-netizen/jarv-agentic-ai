"""
JARV Backend Test Configuration and Fixtures
"""
import os
import pytest
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.models.workspace import Workspace
from app.models.agent import Agent
from app.models.task import Task
from app.models.tool_system import Tool
from app.models.user import User

# Test database URL
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite:///./test.db"
)

# Create test engine
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in TEST_DATABASE_URL else {},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session")
def db_engine():
    """Create test database engine"""
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """Create a fresh database session for each test"""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Create a test client with database session override"""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    """Create authentication headers for testing"""
    return {"Authorization": "Bearer test_token"}


@pytest.fixture
def test_user(db_session: Session) -> User:
    """Create a test user"""
    from uuid import uuid4
    user = User(
        id=uuid4(),
        username="testuser",
        email="test@example.com",
        password_hash="$2b$12$test_hashed_password",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_workspace(db_session: Session, test_user: User) -> Workspace:
    """Create a test workspace"""
    from uuid import uuid4
    workspace = Workspace(
        id=uuid4(),
        name="Test Workspace",
        slug="test-workspace",
        description="A test workspace",
        owner_id=test_user.id,
        is_active=True,
        workspace_type="test",
        authority_level=5,
    )
    db_session.add(workspace)
    db_session.commit()
    db_session.refresh(workspace)
    return workspace


@pytest.fixture
def test_agent(db_session: Session, test_workspace: Workspace) -> Agent:
    """Create a test agent"""
    from uuid import uuid4
    agent = Agent(
        id=uuid4(),
        name="Test Agent",
        agent_type="test_agent",
        workspace_id=test_workspace.id,
        is_active=True,
        authority_level=3,
        allowed_tools=["test", "execute"],
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)
    return agent


@pytest.fixture
def test_task(db_session: Session, test_workspace: Workspace, test_agent: Agent) -> Task:
    """Create a test task"""
    from uuid import uuid4
    task = Task(
        id=uuid4(),
        title="Test Task",
        description="A test task",
        workspace_id=test_workspace.id,
        assigned_agent_id=test_agent.id,
        status="pending",
        priority=5,
        task_type="test",
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


@pytest.fixture
def test_tool(db_session: Session) -> Tool:
    """Create a test tool"""
    from uuid import uuid4
    tool = Tool(
        id=uuid4(),
        name="test_tool",
        category="testing",
        description="A test tool",
        is_active=True,
        requires_approval=False,
        risk_level="low",
    )
    db_session.add(tool)
    db_session.commit()
    db_session.refresh(tool)
    return tool


@pytest.fixture
def sample_test_data():
    """Provide sample test data for various tests"""
    return {
        "workspace": {
            "name": "Sample Workspace",
            "slug": "sample-workspace",
            "description": "Sample description",
            "workspace_type": "general",
            "authority_level": 5,
        },
        "agent": {
            "name": "Sample Agent",
            "agent_type": "sample_role",
            "authority_level": 3,
            "allowed_tools": ["read", "write"],
        },
        "task": {
            "title": "Sample Task",
            "description": "Sample task description",
            "priority": "high",
            "task_type": "coding",
        },
    }
