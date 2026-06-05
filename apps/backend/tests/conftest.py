"""
JARV Backend Test Configuration and Fixtures
"""
import os

# Enable test mode BEFORE importing the app/config so the settings singleton
# (app.core.config.settings = Settings()) reads TESTING=1. In test mode the
# Redis client uses an in-memory fakeredis double, so the suite runs without a
# real Redis server. This affects test mode only; production/dev are unchanged.
os.environ.setdefault("TESTING", "1")

import pytest
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool, NullPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.core.database import Base, get_db
# Register ALL models on Base.metadata for create_all. Imported via an alias so
# it does NOT rebind the local name `app` (which is the FastAPI instance above).
import app.models as _all_models  # noqa: F401
from app.models.workspace import Workspace
from app.models.agent import Agent
from app.models.task import Task
from app.models.tool_system import Tool
from app.models.user import User

# Async DB test harness (Repair 4)
# -----------------------------------------------------------------------------
# Production uses an async SQLAlchemy engine (AsyncSession) and API endpoints do
# `await db.execute(...)`. The previous test harness injected a SYNC Session
# into the async get_db override, so awaiting a sync Result raised
# "ChunkedIteratorResult can't be used in 'await' expression" -> 500.
#
# Fix WITHOUT touching production: back BOTH a sync engine (for the existing
# sync fixtures/integration tests that use Session.query/.add/.commit) AND an
# async engine (for the get_db override the async API needs) with the SAME
# file-based SQLite database. The sync engine runs in AUTOCOMMIT isolation so
# its reads always see rows the async API just committed (and vice-versa), which
# the API tests require (create-then-verify, duplicate-slug, delete-then-verify).
# Isolation between tests is by clearing all tables (see _clean_db), not by
# transaction rollback. Test-scoped only; production/dev unchanged.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite:///./test_jarv.db")
_ASYNC_TEST_URL = TEST_DATABASE_URL.replace("sqlite://", "sqlite+aiosqlite://", 1)
_SQLITE = "sqlite" in TEST_DATABASE_URL

# Sync engine: AUTOCOMMIT so each statement commits immediately and every read
# starts a fresh snapshot (no stale long-lived transaction hiding async writes).
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _SQLITE else {},
    poolclass=StaticPool if _SQLITE else NullPool,
    isolation_level="AUTOCOMMIT",
)

# Async engine over the SAME database file. NullPool = short-lived connections
# that commit-and-close per request, releasing SQLite locks promptly.
async_engine = create_async_engine(
    _ASYNC_TEST_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _SQLITE else {},
    poolclass=NullPool,
)

TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
)
AsyncTestingSessionLocal = async_sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False,
    autocommit=False, autoflush=False,
)


@pytest.fixture(scope="session")
def db_engine():
    """Create the test database schema (shared by the sync + async engines)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_db(db_engine):
    """Isolate tests by clearing all tables before each test.

    Replaces the old rollback-based isolation: because the async API session and
    the sync fixture session are different connections to the same file, data
    must be COMMITTED to be visible across them, so per-test rollback can't be
    used. Clearing every table at setup gives each test a clean, deterministic
    starting state.
    """
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """A sync Session (AUTOCOMMIT engine) for fixtures and sync integration tests.

    Keeps the existing Session API (.query/.add/.commit/.refresh) so no test or
    fixture needs rewriting. Commits are real (visible to the async API session).
    """
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_redis_singleton():
    """Give each test a fresh in-memory fakeredis instance.

    init_redis() caches a module-global client; resetting it between tests
    prevents key state from one test leaking into another. Test-scoped only.
    """
    import app.core.redis as _redis_mod

    _redis_mod._redis_client = None
    _redis_mod._redis_pool = None
    yield
    _redis_mod._redis_client = None
    _redis_mod._redis_pool = None


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Test client whose get_db override yields a real AsyncSession.

    The async API endpoints do `await db.execute(...)`, so the override must
    provide an AsyncSession (mirroring production get_db). It is backed by the
    same file DB as the sync `db_session`, so data created by sync fixtures is
    visible to the API and vice-versa. (db_session is requested so the DB/schema
    is ready and so tests can verify via the sync session.)
    """
    async def override_get_db():
        async with AsyncTestingSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

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
