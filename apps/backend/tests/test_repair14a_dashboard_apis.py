"""Repair 14a: the backend behind the business, revenue, analytics and permissions pages.

Every endpoint is authenticated and owner-scoped, and returns real records:
the operator's workspaces, deals and partners moved through the pipeline,
mission and tool analytics computed from Task and ToolRun rows, the cost
estimate, product traffic, and the live authority model.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.core.auth import get_current_user_id
from app.core.config import settings
from app.main import app
from app.models.agent import Agent
from app.models.task import Task
from app.models.tool_system import Tool, ToolRun
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal


def _run(coro):
    return asyncio.run(coro)


async def _seed(db, name="MYCO", company_mode=True):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name=name, slug=f"ws-{ws_id.hex[:8]}", description="",
                     workspace_type="project", authority_level=5, is_active=True, company_mode_enabled=company_mode,
                     config={}))
    await db.commit()
    return user_id, ws_id


@pytest.fixture
def as_user():
    def login(user_id):
        app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    yield login
    app.dependency_overrides.pop(get_current_user_id, None)


@pytest.mark.api
def test_new_endpoints_require_authentication(client):
    ws = uuid4()
    for method, path in (("get", "/api/workspaces/mine"), ("get", "/api/permissions/overview"),
                         ("get", f"/api/analytics/{ws}/overview"), ("get", f"/api/revenue/{ws}/analytics"),
                         ("get", "/api/operations/cost"), ("post", f"/api/business/{ws}/deals")):
        response = getattr(client, method)(path, **({"json": {}} if method == "post" else {}))
        assert response.status_code == 401, path


@pytest.mark.api
def test_workspace_picker_lists_only_the_operators_workspaces(client, as_user):
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db, "Mine")
            _other, other_ws = await _seed(db, "Someone else's")
            return owner, ws_id, other_ws

    owner, ws_id, other_ws = _run(seed())
    as_user(owner)
    mine = client.get("/api/workspaces/mine")
    assert mine.status_code == 200
    ids = [w["id"] for w in mine.json()]
    assert ids == [str(ws_id)] and str(other_ws) not in ids
    assert mine.json()[0]["company_mode"] is True and mine.json()[0]["has_folder"] is False


@pytest.mark.api
def test_deals_and_partners_move_through_the_pipeline(client, as_user):
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return await _seed(db)

    owner, ws_id = _run(seed())
    as_user(owner)
    base = f"/api/business/{ws_id}"
    created = client.post(f"{base}/deals", json={"title": "Acme annual plan", "company": "Acme", "value": 4800,
                                                 "stage": "qualified"})
    missing_title = client.post(f"{base}/deals", json={"stage": "qualified"})
    bad_stage = client.post(f"{base}/deals", json={"title": "x", "stage": "won-ish"})
    moved = client.post(f"{base}/deals", json={"deal_id": created.json()["id"], "stage": "closed_won"})
    shortlist = client.post(f"{base}/partners/shortlist", json={
        "partner_type": "integration",
        "candidates": [{"name": "Acme Payments", "url": "https://acme.example", "notes": "payments for makers"},
                       {"name": "Bolt Shipping", "notes": "shipping labels"}]})
    partner_id = shortlist.json()["partners"][0]["id"]
    active = client.post(f"{base}/partners/{partner_id}", json={"status": "active", "notes": "signed"})
    pipeline = client.get(f"{base}/pipeline").json()
    as_user(uuid4())
    stranger = client.post(f"{base}/deals", json={"title": "steal"})
    assert created.status_code == 200 and created.json()["stage"] == "qualified"
    assert missing_title.status_code == 400 and bad_stage.status_code == 400
    assert moved.status_code == 200 and moved.json()["stage"] == "closed_won"
    assert shortlist.status_code == 200 and len(shortlist.json()["partners"]) == 2
    assert active.status_code == 200 and active.json()["status"] == "active"  # Richard's dashboard action is the approval
    assert pipeline["won_value"] == 4800 and pipeline["win_rate"] == 1.0
    assert pipeline["partners_by_status"].get("active") == 1
    assert stranger.status_code == 404


@pytest.mark.api
def test_analytics_overview_is_computed_from_missions_and_tool_runs(client, as_user, monkeypatch):
    monkeypatch.setattr(settings, "INFRA_FIXED_COSTS", json.dumps({"vps": 24}))
    monkeypatch.setattr(settings, "INFRA_MONTHLY_BUDGET", 50.0)
    now = datetime.now(timezone.utc)

    async def seed():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            agent = Agent(id=uuid4(), workspace_id=ws_id, name="coding agent", agent_type="coding_agent", authority_level=3)
            db.add(agent)
            tools = {n: Tool(id=uuid4(), tool_name=f"{n}-{uuid4().hex[:6]}", tool_group="file", tool_version="1.0",
                             description=n, config_schema={}, input_schema={}, output_schema={},
                             minimum_authority_level=1) for n in ("read_file", "run_tests")}
            db.add_all(tools.values())
            for i, (status, seconds, tokens) in enumerate((("completed", 40, 1000), ("completed", 20, 500),
                                                            ("failed", 10, 200), ("queued", None, 0))):
                db.add(Task(id=uuid4(), workspace_id=ws_id, title=f"mission {i}", description="d", task_type="command",
                            status=status, priority=5, execution_duration_seconds=seconds, tokens_used=tokens,
                            created_at=now - timedelta(days=i), updated_at=now - timedelta(days=i),
                            completed_at=now - timedelta(days=i) if status in ("completed", "failed") else None))
            await db.flush()
            for tool, success, approval in ((tools["read_file"], True, False), (tools["read_file"], True, False),
                                            (tools["run_tests"], False, False), (tools["run_tests"], None, True)):
                db.add(ToolRun(id=uuid4(), tool_id=tool.id, agent_id=agent.id, input_params={}, status="completed",
                               success=success, started_at=now, duration_ms=100, authority_level_used=3,
                               required_approval=approval))
            await db.commit()
            return owner, ws_id, tools

    owner, ws_id, tools = _run(seed())
    as_user(owner)
    response = client.get(f"/api/analytics/{ws_id}/overview?days=30")
    assert response.status_code == 200, response.text
    data = response.json()
    m, t = data["missions"], data["tools"]
    assert m["total"] == 4 and m["by_status"]["completed"] == 2 and m["by_status"]["failed"] == 1
    assert m["success_rate"] == pytest.approx(2 / 3, abs=0.001)
    assert m["average_seconds"] == pytest.approx(70 / 3, abs=0.1) and m["tokens"] == 1700
    assert sum(d["completed"] for d in m["per_day"].values()) == 2
    assert t["runs"] == 4 and t["failed"] == 1 and t["approval_pauses"] == 1
    assert t["top"][0] == {"tool": tools["read_file"].tool_name, "runs": 2, "failed": 0}
    assert t["by_agent"] == {"coding_agent": 4}
    assert data["cost"]["budget"] == 50.0 and {"item": "vps", "monthly": 24.0, "source": "INFRA_FIXED_COSTS"} in data["cost"]["items"]
    as_user(uuid4())
    assert client.get(f"/api/analytics/{ws_id}/overview").status_code == 404


@pytest.mark.api
def test_cost_traffic_and_permissions_endpoints(client, as_user, monkeypatch):
    monkeypatch.setattr(settings, "INFRA_FIXED_COSTS", json.dumps({"vps": 12.5}))
    monkeypatch.setattr(settings, "PLAUSIBLE_API_KEY", None)

    async def seed():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            from app.core.company_ops.service import company_ops

            await company_ops.record_kpi(db, ws_id, name="visitors", value=900, kpi_type="growth")
            await db.commit()
            return owner, ws_id

    owner, ws_id = _run(seed())
    as_user(owner)
    cost = client.get(f"/api/operations/cost?workspace_id={ws_id}")
    traffic = client.get(f"/api/revenue/{ws_id}/analytics")
    permissions = client.get("/api/permissions/overview").json()
    as_user(uuid4())
    stranger_cost = client.get(f"/api/operations/cost?workspace_id={ws_id}")
    assert cost.status_code == 200 and cost.json()["items"][0]["monthly"] == 12.5
    assert traffic.status_code == 200 and traffic.json()["source"] == "recorded KPIs"
    assert traffic.json()["kpis"][0]["name"] == "visitors"
    assert stranger_cost.status_code == 404
    assert [l["level"] for l in permissions["levels"]] == list(range(11))
    assert len(permissions["agents"]) == 31 and permissions["agents"][0]["authority"] >= permissions["agents"][-1]["authority"]
    assert "deploy_production_with_boundary" in permissions["tools"]["always_approval"]
    assert "scale_service_with_budget_boundary" in permissions["tools"]["conditional_approval"]
    assert {"bank_details", "spend_over_budget", "private_keys"} <= {b["key"] for b in permissions["hard_boundaries"]}
    assert "deploys" in permissions["command_gates"] and "voice" in permissions["voice_rule"]
