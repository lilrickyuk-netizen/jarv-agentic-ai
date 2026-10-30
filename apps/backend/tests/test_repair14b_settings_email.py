"""Repair 14b: Settings on live data, one email configuration, real email tools and notifications.

Real: the service catalogue and its configured / example-value detection, the
settings overview and service checks through the API (outgoing requests go
to an httpx MockTransport, never to a provider), the audit record of each
check, the mailer's settings, the agents' email tools sending, reading and
searching through the mailer (its SMTP and IMAP calls are replaced, so no
mail server is contacted), and live notifications to the operator.
"""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.core.agents.base import AuthorityLevel
from app.core.auth import get_current_user_id
from app.core.business import mailer
import app.core.integrations as integrations_module
from app.core.integrations import integrations
from app.core.ops import connections
from app.core.tools.base import ToolConfig, ToolContext
from app.main import app
from app.models.agent import Agent
from app.models.integrations import OutboundMessageDraft
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.company.email import EmailReadTool, EmailSearchTool, EmailSendTool
from tests.conftest import AsyncTestingSessionLocal

SANDBOX = Path("/tmp/jarv_sandbox")
SECRET = "sk-DRAFTSECRET123456789012345678"
SMTP = {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "richard@example.com", "SMTP_PASSWORD": "app-pass-123",
        "SMTP_FROM": "richard@example.com"}
IMAP = {"IMAP_HOST": "imap.example.com", "IMAP_USER": "richard@example.com", "IMAP_PASSWORD": "app-pass-456"}


def _run(coro):
    return asyncio.run(coro)


async def _seed(db, host=None):
    user_id, ws_id, agent_id = uuid4(), uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"richard-{user_id.hex[:6]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="MYCO", slug=f"myco-{ws_id.hex[:8]}", description="",
                     workspace_type="project", authority_level=5, is_active=True,
                     config={"root_path": host} if host else {}))
    db.add(Agent(id=agent_id, name="sales agent", agent_type="sales", workspace_id=ws_id, is_active=True,
                 authority_level=5, allowed_tools=[], blocked_tools=[], config={}, model_provider="test",
                 model_name="test"))
    await db.commit()
    return user_id, ws_id, agent_id


def _ctx(db, user_id, ws_id, agent_id, approved=True):
    return ToolContext(user_id=user_id, workspace_id=ws_id, agent_id=agent_id, db_session=db,
                       approval_granted=approved)


def _tool(cls):
    return cls(ToolConfig(authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS))


@pytest.fixture
def as_user():
    def login(user_id):
        app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    yield login
    app.dependency_overrides.pop(get_current_user_id, None)


@pytest.fixture
def env(monkeypatch):
    def set_many(values):
        for k, v in values.items():
            monkeypatch.setenv(k, v)
    return set_many


def _transport(monkeypatch, module, handler):
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(module, "http_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(record), **kw))
    return seen


# ----- mailer settings ---------------------------------------------------------------------------

def test_mailer_reads_the_documented_names_and_still_accepts_the_old_ones(env):
    assert mailer.smtp_configured() is False and mailer.status()["missing_for_sending"] == list(mailer.SMTP_KEYS)
    env({"EMAIL_SMTP_HOST": "old.example.com", "EMAIL_SMTP_USER": "a@example.com", "EMAIL_SMTP_PASSWORD": "p"})
    assert mailer.smtp_configured() and mailer.smtp_settings()["sender"] == "a@example.com"  # sender defaults to the user
    env({"SMTP_HOST": "smtp.example.com"})
    assert mailer.smtp_settings()["host"] == "smtp.example.com"  # the documented name wins
    env(IMAP)
    assert mailer.imap_configured() and mailer.imap_settings()["folder"] == "INBOX"
    assert integrations.list()[0]["status"] == "enabled"


# ----- service catalogue and checks --------------------------------------------------------------

def test_catalogue_never_returns_values_and_treats_template_values_as_unset(env, monkeypatch):
    env({"CLAUDE_API_KEY": SECRET, "PEXELS_API_KEY": "your_pexels_api_key", "GITHUB_TOKEN": "your_github_token_here"})
    rows = {r["key"]: r for r in connections.overview()}
    assert rows["claude"]["configured"] and rows["claude"]["checkable"] and rows["claude"]["setup"] is None
    assert rows["pexels"]["configured"] is False and rows["pexels"]["example_values"] == ["PEXELS_API_KEY"]
    assert rows["github"]["configured"] is False and "fine-grained token" in rows["github"]["setup"]
    assert rows["stripe"]["missing"] == ["STRIPE_SECRET_KEY"]
    assert rows["ollama"]["configured"] is False and rows["ollama"]["flag"] == "OLLAMA_ENABLED"
    assert rows["sentry"]["check_note"] and SECRET not in json.dumps(rows)
    assert {s.check for s in connections.SERVICES if s.check} == set(connections.CHECKS)


@pytest.mark.api
def test_settings_overview_and_checks_through_the_api(client, as_user, env, monkeypatch):
    env({"CLAUDE_API_KEY": SECRET, "GITHUB_TOKEN": "ghp_realtoken123456"})

    def answer(request):
        if request.url.host == "api.anthropic.com":
            assert request.method == "GET" and request.url.path == "/v1/models"
            assert request.headers["x-api-key"] == SECRET and request.headers["anthropic-version"]
            return httpx.Response(200, json={"data": [{"id": "claude"}], "echo": SECRET})
        if request.url.host == "api.github.com":
            return httpx.Response(401, json={"message": "Bad credentials"})
        raise AssertionError(f"unexpected request to {request.url}")

    seen = _transport(monkeypatch, connections, answer)

    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return (await _seed(db))[0]

    owner = _run(seed())
    assert client.get("/api/settings/overview").status_code == 401
    assert client.post("/api/settings/services/claude/check").status_code == 401
    as_user(owner)
    ok = client.post("/api/settings/services/claude/check")
    bad = client.post("/api/settings/services/github/check")
    unknown = client.post("/api/settings/services/astrology/check")
    unset = client.post("/api/settings/services/stripe/check")
    uncheckable = client.post("/api/settings/services/sentry/check")
    overview = client.get("/api/settings/overview")
    assert ok.status_code == 200 and ok.json()["ok"] is True and SECRET not in ok.text
    assert bad.status_code == 200 and bad.json()["ok"] is False and "rejected the credentials" in bad.json()["detail"]
    assert unknown.status_code == 404 and unset.status_code == 400 and "STRIPE_SECRET_KEY" in unset.json()["detail"]
    assert uncheckable.status_code == 400
    assert len(seen) == 2  # only the two checks reached the (mock) network
    data = overview.json()
    assert overview.status_code == 200 and SECRET not in overview.text
    assert data["readiness"]["database"]["status"] == "healthy"
    assert data["routing"]["primary"] == "claude" and data["routing"]["order"][0] == {"provider": "claude", "configured": True}
    services = {s["key"]: s for s in data["services"]}
    assert services["claude"]["last_check"]["ok"] is True and services["github"]["last_check"]["ok"] is False
    assert services["stripe"]["last_check"] is None
    assert data["safety"]["audit_logging"] is True and "speech_to_text" in data["voice"]
    assert {n["name"] for n in data["notifications"]} == {"email_smtp", "webhook", "local_mock"}


def test_unreachable_service_is_reported_not_raised(env, monkeypatch):
    env({"OPENAI_API_KEY": "sk-proj-abc123def456"})

    def fail(request):
        raise httpx.ConnectError("no route", request=request)

    _transport(monkeypatch, connections, fail)
    result = _run(connections.check("openai"))
    assert result == {"service": "openai", "ok": False, "detail": "Could not reach OpenAI (ConnectError)"}


# ----- email tools -------------------------------------------------------------------------------

@pytest.mark.integration
def test_email_send_sends_each_recipient_after_approval_with_workspace_attachments(env, monkeypatch):
    env(SMTP)
    sent = []
    monkeypatch.setattr(mailer, "_send", lambda to, subject, body, reply, html, files: sent.append(
        (to, subject, body, [f.name for f in files])) or f"<{len(sent)}@example.com>")
    name = f"r14b-{uuid4().hex[:8]}"
    (SANDBOX / name / "docs").mkdir(parents=True)
    (SANDBOX / name / "docs" / "proposal.pdf").write_bytes(b"%PDF-1.4 proposal")

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id, agent_id = await _seed(db, f"/test_workspaces/{name}")
            ctx = _ctx(db, user_id, ws_id, agent_id)
            tool = _tool(EmailSendTool)
            live = await tool.execute({"to": ["ana@example.com"], "cc": ["ben@example.com"], "subject": "Proposal",
                                       "body": f"Attached. key {SECRET}", "attachments": ["docs/proposal.pdf"]}, ctx)
            unapproved = await tool.execute({"to": ["ana@example.com"], "subject": "Hi", "body": "x"},
                                            _ctx(db, user_id, ws_id, agent_id, approved=False))
            mass = await tool.execute({"to": [f"p{i}@example.com" for i in range(11)], "subject": "Hi", "body": "x"}, ctx)
            escape = await tool.execute({"to": ["ana@example.com"], "subject": "Hi", "body": "x",
                                         "attachments": ["../../etc/passwd"]}, ctx)
            await db.commit()
            records = (await db.execute(OutboundMessageDraft.__table__.select().where(
                OutboundMessageDraft.workspace_id == ws_id))).all()
            return live, unapproved, mass, escape, records

    live, unapproved, mass, escape, records = _run(run())
    assert live.success, live.error_message
    assert live.result_data["mode"] == "live" and live.result_data["status"] == "sent"
    assert [d["to"] for d in live.result_data["delivered"]] == ["ana@example.com", "ben@example.com"]
    assert [s[0] for s in sent] == ["ana@example.com", "ben@example.com"]  # one message per recipient
    assert sent[0][3] == ["proposal.pdf"] and SECRET not in sent[0][2]
    assert unapproved.success is False and len(sent) == 2
    assert mass.success is False and "mass email" in json.dumps(mass.result_data)
    assert escape.success is False and "outside the workspace" in escape.error_message
    assert [r.status for r in records] == ["sent"]


@pytest.mark.integration
def test_email_read_and_search_use_the_mailbox_read_only(env, monkeypatch):
    calls = []
    message = {"message_id": "<m1@x>", "from_name": "Ana", "from_email": "ana@example.com", "subject": "Refund?",
               "body": f"My key is {SECRET}, please refund", "date": "Thu, 29 Oct 2026", "has_attachments": False}
    monkeypatch.setattr(mailer, "_fetch", lambda criteria, limit, folder: calls.append((criteria, limit, folder)) or [message])

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id, agent_id = await _seed(db)
            ctx = _ctx(db, user_id, ws_id, agent_id)
            before = await _tool(EmailReadTool).run({"folder": "inbox", "limit": 10}, ctx)
            env(IMAP)
            inbox = await _tool(EmailReadTool).run({"folder": "inbox", "limit": 10, "unread_only": True}, ctx)
            found = await _tool(EmailSearchTool).run({"query": 'refund "now"', "from_addr": "ana@example.com",
                                                      "limit": 5}, ctx)
            drafts = await _tool(EmailSearchTool).run({"query": "refund", "folder": "drafts", "limit": 5}, ctx)
            return before, inbox, found, drafts

    before, inbox, found, drafts = _run(run())
    assert before.success is False and "IMAP_HOST" in before.error_message
    assert inbox.success and inbox.result_data["mode"] == "live" and inbox.result_data["emails"][0]["from_addr"] == "ana@example.com"
    assert SECRET not in json.dumps(inbox.result_data)
    assert found.success and found.result_data["count"] == 1
    assert calls[0] == (["UNSEEN"], 10, None)
    assert calls[1] == (["TEXT", '"refund \\"now\\""', "FROM", '"ana@example.com"'], 5, None)
    assert drafts.success and drafts.result_data["mode"] == "local_drafts" and len(calls) == 2


# ----- notifications -----------------------------------------------------------------------------

@pytest.mark.api
def test_live_notifications_reach_the_operator_or_report_why_not(client, as_user, env, monkeypatch):
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return (await _seed(db))[0]

    owner = _run(seed())
    as_user(owner)
    disabled = client.post("/api/integrations/notify", json={"target": "email_smtp", "dry_run": False, "message": "hi"})
    env(SMTP)
    mails = []

    async def record_send(to, subject, body, reply_to_id=None, **kw):
        mails.append(to)
        return {"to": to, "subject": subject, "message_id": "<n1@example.com>"}

    monkeypatch.setattr(mailer, "send_email", record_send)
    emailed = client.post("/api/integrations/notify", json={"target": "email_smtp", "dry_run": False, "message": "hi"})
    env({"NOTIFY_WEBHOOK_URL": "http://not-https.example.com/hook"})
    plain_http = client.post("/api/integrations/notify", json={"target": "webhook", "dry_run": False, "message": "hi"})
    env({"NOTIFY_WEBHOOK_URL": "https://ntfy.example.com/jarv"})
    hooks = _transport(monkeypatch, integrations_module, lambda request: httpx.Response(200))
    posted = client.post("/api/integrations/notify", json={"target": "webhook", "dry_run": False, "message": "deploy done"})
    assert disabled.json()["sent"] is False and disabled.json()["mode"] == "disabled"
    assert emailed.json()["sent"] is True and mails == [f"richard-{owner.hex[:6]}@t.io"]  # the operator's own address
    assert posted.json()["sent"] is True and json.loads(hooks[0].content)["text"] == "deploy done"
    assert plain_http.json()["sent"] is False and plain_http.json()["mode"] == "disabled"
    assert "https" in plain_http.json()["summary"]
