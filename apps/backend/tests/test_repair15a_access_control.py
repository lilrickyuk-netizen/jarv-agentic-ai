"""Repair 15a: every API route requires sign-in, and an operator only ever sees their own records.

Real: the whole route table of the app is walked, so a route added later
without authentication fails this test; workspaces, tasks, the live
operations feed, standups, company roles and the audit trail are seeded for
two operators and read through the API as each of them; a workspace is
archived by a plain delete and only removed with its slug confirmed.
"""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute

from app.core.auth import get_current_user_id
from app.main import app
from app.models.company import CompanyRole
from app.models.company_operations import LiveOperationsFeedItem
from app.models.operations import AuditLog
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal

# Reachable without signing in, each for a stated reason.
PUBLIC = {
    ("POST", "/auth/login"), ("POST", "/auth/refresh"),            # how a session starts
    ("GET", "/health"), ("GET", "/ready"), ("GET", "/version"), ("GET", "/"),  # liveness: no private data
    ("GET", "/metrics"),                                            # METRICS_TOKEN or private network
    ("POST", "/api/observability/alerts"),                          # ALERT_WEBHOOK_TOKEN or private network
    ("POST", "/api/revenue/{workspace_id}/stripe-webhook"),         # Stripe signature
    ("GET", "/api/calendar/feed/{workspace_id}/{token}.ics"),       # secret link for calendar apps (404 if wrong)
}


def _run(coro):
    return asyncio.run(coro)


def test_every_route_outside_the_public_list_refuses_an_anonymous_caller(client):
    app.dependency_overrides.pop(get_current_user_id, None)
    open_routes = []
    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if (method, route.path) in PUBLIC:
                continue
            path = route.path
            for name in route.param_convertors:
                path = path.replace("{" + name + "}", str(uuid4()))
            for segment in [s for s in path.split("/") if s.startswith("{") and s.endswith("}")]:
                path = path.replace(segment, str(uuid4()))
            response = client.request(method, path, json={})
            checked += 1
            if response.status_code != 401:
                open_routes.append(f"{method} {route.path} -> {response.status_code}")
    assert checked > 200
    assert open_routes == [], "Routes reachable without signing in:\n" + "\n".join(open_routes)


async def _operator(db, name):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"{name}{user_id.hex[:6]}", email=f"{name}{user_id.hex[:6]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name=f"{name} co", slug=f"{name}-{ws_id.hex[:8]}", description="",
                     workspace_type="project", authority_level=5, is_active=True, config={}))
    await db.flush()
    task_id = uuid4()
    db.add(Task(id=task_id, workspace_id=ws_id, title=f"{name} private mission", description="d", task_type="command",
                status="completed", priority=5))
    db.add(LiveOperationsFeedItem(id=uuid4(), workspace_id=ws_id, item_type="mission", severity="info",
                                  title=f"{name} private feed item", message="m"))
    db.add(CompanyRole(id=uuid4(), workspace_id=ws_id, role_name=f"{name} private role", role_type="executive",
                       level=1, responsibilities=[], authority_level=3, config={}, skills_required=[]))
    db.add(AuditLog(id=uuid4(), workspace_id=ws_id, user_id=user_id, actor_type="user", action=f"{name}.private",
                    action_category="system", description=f"{name} private audit entry", success=True))
    await db.commit()
    return user_id, ws_id, task_id


@pytest.mark.api
def test_an_operator_sees_and_changes_only_their_own_records(client):
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return await _operator(db, "ana"), await _operator(db, "ben")

    (ana, ana_ws, ana_task), (ben, ben_ws, ben_task) = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(ben)
    try:
        seen = {
            "workspaces": [w["id"] for w in client.get("/api/workspaces/list").json()],
            "tasks": [t["title"] for t in client.get("/api/tasks/list").json()],
            "feed": [f["title"] for f in client.get("/api/operations-feed/list").json()],
            "roles": [r["role_name"] for r in client.get("/api/company/roles/list").json()],
            "audit": [a["description"] for a in client.get("/api/audit/list?limit=500").json()],
        }
        stats = client.get("/api/workspaces/stats").json()
        ana_workspace = client.get(f"/api/workspaces/{ana_ws}")
        ana_mission = client.get(f"/api/tasks/{ana_task}")
        rename = client.patch(f"/api/workspaces/{ana_ws}", json={"name": "taken over"})
        delete = client.delete(f"/api/workspaces/{ana_ws}", params={"permanent": "true", "confirm": "x"})
        own_mission = client.get(f"/api/tasks/{ben_task}")
        created = client.post("/api/workspaces/create", json={"name": "Ben Two", "slug": f"ben-two-{uuid4().hex[:6]}",
                                                              "workspace_type": "general"})
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    async def after():
        async with AsyncTestingSessionLocal() as db:
            row = await db.get(Workspace, ana_ws)
            return row.name, row.is_archived

    assert str(ben_ws) in seen["workspaces"] and str(ana_ws) not in seen["workspaces"]
    assert "ben private mission" in seen["tasks"] and "ana private mission" not in seen["tasks"]
    assert "ben private feed item" in seen["feed"] and "ana private feed item" not in seen["feed"]
    assert "ben private role" in seen["roles"] and "ana private role" not in seen["roles"]
    assert "ben private audit entry" in seen["audit"] and "ana private audit entry" not in seen["audit"]
    assert stats["total_workspaces"] == 1 and stats["total_tasks_across_all"] == 1
    assert ana_workspace.status_code == ana_mission.status_code == rename.status_code == delete.status_code == 404
    assert own_mission.status_code == 200
    assert created.status_code == 201 and created.json()["owner_id"] == str(ben)  # the creator owns it
    assert _run(after()) == ("ana co", False)


@pytest.mark.api
def test_deleting_a_workspace_archives_it_unless_confirmed_by_slug(client):
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return await _operator(db, "cara")

    owner, ws_id, task_id = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        archived = client.delete(f"/api/workspaces/{ws_id}")
        wrong = client.delete(f"/api/workspaces/{ws_id}", params={"permanent": "true", "confirm": "not-the-slug"})
        restored = client.patch(f"/api/workspaces/{ws_id}", json={"is_archived": False, "is_active": True})
        slug = restored.json()["slug"]
        gone = client.delete(f"/api/workspaces/{ws_id}", params={"permanent": "true", "confirm": slug})
        after = client.get(f"/api/workspaces/{ws_id}")
        audit = [a["action"] for a in client.get("/api/audit/list?limit=500").json()]
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert archived.status_code == 200 and archived.json() == {
        "id": str(ws_id), "archived": True, "deleted": False,
        "note": "Archived. Restore it with is_archived=false; nothing was deleted."}
    assert wrong.status_code == 400 and slug in wrong.json()["detail"]
    assert restored.status_code == 200 and restored.json()["is_archived"] is False
    assert gone.status_code == 200 and gone.json()["deleted"] is True and after.status_code == 404
    assert "workspace.deleted_permanently" in audit
