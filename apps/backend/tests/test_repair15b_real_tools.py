"""Repair 15b: tools that only refused now work; legacy in-memory APIs are gone.

Real: the resource tools against the local deployment-server stand-in used by
the deploy tests (real shell commands, every compose call logged), the budget
rules shared with scale_service_with_budget_boundary, resource records in the
database; the calendar feed generated from stored events and served on its
secret link; the removed legacy routes answer 404.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.calendar_feed import _fold, to_ics
from app.core.agents.base import AuthorityLevel
from app.core.auth import get_current_user_id
from app.core.config import settings
from app.core.tools.base import ToolConfig, ToolContext
from app.main import app
from app.models.agent import Agent
from app.models.integrations import CalendarEvent
from app.models.operations import InfrastructureResource
from app.models.workspace import Workspace
from app.tools.deploy import DeployStagingTool
from app.tools.infrastructure.resources import (ResourceHealthCheckTool, ResourceProvisionTool, ResourceScaleTool,
                                                 ResourceTerminateTool)
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12e_deploy import _workspace as _deploy_workspace
from tests.test_repair12e_deploy import server  # noqa: F401 - the deployment server fixture


def _run(coro):
    return asyncio.run(coro)


def _tool(cls):
    return cls(ToolConfig(authority_level=AuthorityLevel.LEVEL_7_DEPLOYMENT))


@pytest.mark.api
def test_legacy_in_memory_routes_are_gone(client):
    app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
    try:
        paths = [("get", "/api/business/metrics/summary"), ("post", "/api/business/workflows/marketing-campaign"),
                 ("get", "/api/workflows/coding-loop/status"), ("post", "/api/workflows/coding-loop"),
                 ("post", "/api/content-community/workflows/content-strategy"), ("get", "/api/assets/templates/")]
        answers = {p: getattr(client, m)(p, **({"json": {}} if m == "post" else {})).status_code for m, p in paths}
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert set(answers.values()) <= {404, 405}, answers


@pytest.mark.integration
def test_resources_are_services_on_the_deployment_server_under_the_budget(server, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "INFRA_FIXED_COSTS", json.dumps({"vps": 20}))
    monkeypatch.setattr(settings, "INFRA_REPLICA_MONTHLY_COST", 10.0)
    monkeypatch.setattr(settings, "INFRA_MAX_REPLICAS", 4)
    monkeypatch.setattr(settings, "INFRA_MONTHLY_BUDGET", 1_000_000.0)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            ws_id = await _deploy_workspace(db, server["host"])
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            approved = ToolContext(workspace_id=ws_id, db_session=db, approval_granted=True)
            deployed = await _tool(DeployStagingTool).execute({}, ctx)
            cloud = await _tool(ResourceProvisionTool).execute(
                {"resource_name": "big-vm", "resource_type": "vm", "provider": "aws"}, ctx)
            prod = await _tool(ResourceProvisionTool).execute(
                {"resource_name": "worker", "provider": "vps", "config": {"environment": "production"}}, ctx)
            started = await _tool(ResourceProvisionTool).execute(
                {"resource_name": "worker", "provider": "vps", "config": {"service": "web", "monthly_cost": 5}}, ctx)
            external = await _tool(ResourceProvisionTool).execute(
                {"resource_name": "myco.app domain", "resource_type": "domain", "provider": "external",
                 "config": {"monthly_cost": 1.25, "registrar": "Namecheap"}}, ctx)
            rid = started.result_data.get("resource_id")
            scaled = await _tool(ResourceScaleTool).execute({"resource_id": rid, "target_config": {"replicas": 3}}, ctx)
            health = await _tool(ResourceHealthCheckTool).execute({"resource_id": rid}, ctx)
            monkeypatch.setattr(settings, "INFRA_MONTHLY_BUDGET", 0.01)
            over = await _tool(ResourceScaleTool).execute({"resource_id": rid, "scale_action": "up"}, ctx)
            unapproved_stop = await _tool(ResourceTerminateTool).execute({"resource_id": rid}, ctx)
            wipe = await _tool(ResourceTerminateTool).execute({"resource_id": rid, "delete_data": True}, approved)
            stopped = await _tool(ResourceTerminateTool).execute({"resource_id": rid}, approved)
            ended = await _tool(ResourceTerminateTool).execute(
                {"resource_id": external.result_data["resource_id"]}, approved)
            await db.commit()
            rows = {r.resource_name: r for r in (await db.execute(select(InfrastructureResource).where(
                InfrastructureResource.workspace_id == ws_id))).scalars().all()}
            return (deployed, cloud, prod, started, external, scaled, health, over, unapproved_stop, wipe, stopped,
                    ended, rows)

    (deployed, cloud, prod, started, external, scaled, health, over, unapproved_stop, wipe, stopped, ended,
     rows) = _run(run())
    log = server["compose_log"].read_text()
    assert deployed.success, deployed.error_message
    assert cloud.success is False and "hard boundaries" in cloud.error_message and "big-vm" not in rows
    assert prod.success is False and prod.result_data["requires_approval"] is True
    assert started.success, started.error_message
    assert started.result_data["provider_resource_id"] == "vps:myco-staging:web" and "--scale web=1" in log
    assert external.success and external.result_data["status"] == "recorded"
    assert scaled.success, scaled.error_message
    assert scaled.result_data["new_config"] == {"replicas": 3} and "--scale web=3" in log
    # The stand-in server's compose reports no running containers: counted, not assumed
    assert health.success and health.result_data["checks"] == {"running_replicas": 0, "expected_replicas": 3}
    assert health.result_data["health_status"] == "unhealthy"
    assert over.success is False and over.result_data["requires_approval"] is True and "web=4" not in log
    assert unapproved_stop.success is False and unapproved_stop.result_data["requires_approval"] is True
    assert wipe.success is False and wipe.result_data["requires_approval"] is False  # never on this path
    assert stopped.success and stopped.result_data["data_kept"] is True and "--scale web=0" in log
    assert ended.success and ended.result_data["status"] == "ended"
    worker, domain = rows["worker"], rows["myco.app domain"]
    assert worker.is_active is False and worker.status == "stopped" and worker.capacity == {"replicas": 0}
    assert float(worker.monthly_cost) == 5.0 and worker.provider == "vps"
    assert domain.is_active is False and float(domain.monthly_cost) == 1.25 and domain.provider == "external"


def test_calendar_feed_is_valid_icalendar():
    ws = Workspace(id=uuid4(), owner_id=uuid4(), name="MYCO; launch, team", slug="myco", config={})
    start = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)
    event = CalendarEvent(id=uuid4(), owner_id=ws.owner_id, workspace_id=ws.id, agent_id=uuid4(),
                          title="Launch review, final", description="Line one\nLine two; done", location="Zoom",
                          start_time=start, end_time=start + timedelta(hours=1), attendees=["ana@example.com"],
                          reminders=[15, 60], is_active=True, updated_at=start)
    text = to_ics(ws, [event])
    lines = text.split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR" and text.endswith("\r\n")
    assert "X-WR-CALNAME:JARV - MYCO\\; launch\\, team" in lines
    assert "SUMMARY:Launch review\\, final" in lines and "DESCRIPTION:Line one\\nLine two\\; done" in lines
    assert "DTSTART:20261102T093000Z" in lines and "DTEND:20261102T103000Z" in lines
    assert "TRIGGER:-PT15M" in lines and "TRIGGER:-PT60M" in lines
    assert "ATTENDEE;RSVP=FALSE:mailto:ana@example.com" in lines
    folded = _fold("DESCRIPTION:" + "é" * 80)
    assert all(len(part.encode()) <= 75 for part in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == "DESCRIPTION:" + "é" * 80


@pytest.mark.api
def test_calendar_feed_link_serves_the_workspace_events_and_rotates(client):
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            from app.models.user import User

            owner, ws_id, agent_id = uuid4(), uuid4(), uuid4()
            db.add(User(id=owner, username=f"u{owner.hex[:8]}", email=f"{owner.hex[:8]}@t.io", password_hash="x",
                        is_active=True, is_admin=False))
            db.add(Workspace(id=ws_id, owner_id=owner, name="MYCO", slug=f"myco-{ws_id.hex[:6]}", description="",
                             workspace_type="project", authority_level=5, is_active=True, config={}))
            db.add(Agent(id=agent_id, name="ops", agent_type="business", workspace_id=ws_id, is_active=True,
                         authority_level=5, allowed_tools=[], blocked_tools=[], config={}, model_provider="t",
                         model_name="t"))
            await db.flush()
            now = datetime.now(timezone.utc)
            for title, active in (("Investor call", True), ("Cancelled sync", False)):
                db.add(CalendarEvent(id=uuid4(), owner_id=owner, workspace_id=ws_id, agent_id=agent_id, title=title,
                                     start_time=now + timedelta(days=1), end_time=now + timedelta(days=1, hours=1),
                                     attendees=[], reminders=[], is_active=active))
            await db.commit()
            return owner, ws_id

    owner, ws_id = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        link = client.get(f"/api/calendar/{ws_id}/feed", headers={"x-forwarded-proto": "https",
                                                                  "x-forwarded-host": "jarv.example.com"}).json()
        again = client.get(f"/api/calendar/{ws_id}/feed").json()
        app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
        stranger = client.get(f"/api/calendar/{ws_id}/feed")
        app.dependency_overrides[get_current_user_id] = lambda: str(owner)
        path = link["url"].split("jarv.example.com", 1)[1]
        app.dependency_overrides.pop(get_current_user_id, None)
        feed = client.get(path)  # a calendar app: no sign-in, only the secret link
        forged = client.get(path.replace(path.rsplit("/", 1)[1], "0" * 40 + ".ics"))
        app.dependency_overrides[get_current_user_id] = lambda: str(owner)
        rotated = client.post(f"/api/calendar/{ws_id}/feed/rotate").json()
        app.dependency_overrides.pop(get_current_user_id, None)
        old_after_rotate = client.get(path)
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert link["url"].startswith(f"https://jarv.example.com/api/calendar/feed/{ws_id}/")
    assert link["webcal_url"].startswith("webcal://jarv.example.com/") and len(link["how_to_add"]) == 3
    assert again["url"].split("/")[-1] == link["url"].split("/")[-1]  # stable until rotated
    assert stranger.status_code == 404
    assert feed.status_code == 200 and feed.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:Investor call" in feed.text and "Cancelled sync" not in feed.text
    assert forged.status_code == 404
    assert rotated["url"] != link["url"] and old_after_rotate.status_code == 404
