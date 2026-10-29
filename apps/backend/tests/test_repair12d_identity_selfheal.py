"""Repair 12d follow-up: operator identity and the scheduled self-healing loop.

Operators log in through the login store (ids such as "admin_richard"); data is
owned by rows in the users table. These tests use real tokens, the real auth
dependencies, and the real scheduled loop; only the Docker Engine is replaced
at the HTTP transport (see test_repair12d_ops_tools.FakeDocker).
"""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

import app.core.database as database
from app.core.auth import resolve_user_id
from app.core.ops import docker_ops
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.models.company_operations import LiveOperationsFeedItem
from app.models.operations import AuditLog
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12d_ops_tools import FakeDocker


def _run(coro):
    return asyncio.run(coro)


async def _owner_with_workspace():
    async with AsyncTestingSessionLocal() as db:
        owner = User(id=uuid4(), username=f"owner{uuid4().hex[:6]}", email=f"{uuid4().hex[:8]}@t.io",
                     password_hash="x", is_active=True, is_admin=True,
                     created_at=datetime.now(timezone.utc) - timedelta(days=30))
        db.add(owner)
        ws = Workspace(id=uuid4(), owner_id=owner.id, name="Main", slug=f"main-{uuid4().hex[:6]}",
                       description="", workspace_type="general", authority_level=5, is_active=True)
        db.add(ws)
        await db.commit()
        return owner.id, ws.id


@pytest.mark.integration
def test_login_ids_resolve_to_persisted_users():
    async def run():
        owner_id, _ = await _owner_with_workspace()
        redis = await get_redis()
        await redis.set("user:admin_richard:admin", "true")
        async with AsyncTestingSessionLocal() as db:
            admin = await resolve_user_id(db, redis, "admin_richard")
            again = await resolve_user_id(db, redis, "admin_richard")
            guest = await resolve_user_id(db, redis, "guest_sam")
            passthrough = await resolve_user_id(db, redis, str(owner_id))
            guest_row = (await db.execute(select(User).where(User.id == guest))).scalar_one()
        return owner_id, admin, again, guest, passthrough, guest_row

    owner_id, admin, again, guest, passthrough, guest_row = _run(run())
    assert admin == again == owner_id == passthrough
    assert guest != owner_id and isinstance(guest, UUID)
    assert guest_row.is_admin is False and guest_row.password_hash == "!"


@pytest.mark.api
def test_dashboard_stats_work_for_a_real_operator_login(client):
    owner_id, _ = _run(_owner_with_workspace())
    _run(_mark_admin("admin_richard"))
    headers = {"Authorization": f"Bearer {create_access_token({'sub': 'admin_richard', 'username': 'richard'})}"}

    for path in ("/api/memory/stats", "/api/approvals/stats", "/api/tasks/list", "/api/command/history"):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.status_code, response.text[:300])


async def _mark_admin(subject):
    redis = await get_redis()
    await redis.set(f"user:{subject}:admin", "true")


# ----- scheduled self-healing loop --------------------------------------------------------------

@pytest.fixture
def loop_env(monkeypatch):
    fake = FakeDocker()
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", fake.project)
    monkeypatch.delenv("PROMETHEUS_URL", raising=False)
    monkeypatch.setattr(docker_ops, "get_docker_ops", fake.ops)
    monkeypatch.setattr(database, "AsyncSessionLocal", AsyncTestingSessionLocal)
    return fake


@pytest.mark.integration
def test_scheduled_loop_restarts_a_service_unhealthy_twice_and_creates_no_tasks(loop_env):
    from app.workers.tasks import _run_scheduled_loop

    loop_env.add("aaaaaaaaaaaa", "backend")
    loop_env.add("bbbbbbbbbbbb", "dashboard", state="running", health="unhealthy")
    loop_env.add("dddddddddddd", "postgres", state="exited", health=None)

    async def run():
        _, ws_id = await _owner_with_workspace()
        job = f"selfheal-{uuid4().hex[:6]}"
        first = await _run_scheduled_loop(job, "test")
        second = await _run_scheduled_loop(job, "test")
        third = await _run_scheduled_loop(job, "test")
        async with AsyncTestingSessionLocal() as db:
            tasks = (await db.execute(select(func.count(Task.id)))).scalar()
            feed = (await db.execute(select(LiveOperationsFeedItem.title).where(
                LiveOperationsFeedItem.workspace_id == ws_id))).scalars().all()
            audits = (await db.execute(select(func.count(AuditLog.id)).where(
                AuditLog.action == "scheduled_run"))).scalar()
        return first, second, third, tasks, feed, audits

    first, second, third, tasks, feed, audits = _run(run())
    assert first["repairs"] == [] and "service:dashboard" in first["failing"]
    assert [r["service"] for r in second["repairs"]] == ["dashboard"]
    assert loop_env.restarts() == ["/containers/bbbbbbbbbbbb/restart"]
    assert "service:postgres" in third["failing"] and third["repairs"] == []
    assert tasks == 0 and audits == 3
    assert "Self-healing restarted a service" in feed
    assert len(feed) == 3


@pytest.mark.integration
def test_scheduled_loop_writes_the_feed_only_when_state_changes(loop_env):
    from app.workers.tasks import _run_scheduled_loop

    loop_env.add("aaaaaaaaaaaa", "backend")

    async def run():
        _, ws_id = await _owner_with_workspace()
        job = f"steady-{uuid4().hex[:6]}"
        for _ in range(3):
            await _run_scheduled_loop(job, "test")
        async with AsyncTestingSessionLocal() as db:
            return (await db.execute(select(LiveOperationsFeedItem.title).where(
                LiveOperationsFeedItem.workspace_id == ws_id))).scalars().all()

    assert _run(run()) == ["JARV health check"]
