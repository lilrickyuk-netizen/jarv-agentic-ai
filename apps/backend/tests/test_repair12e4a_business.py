"""Repair 12e-4a: grounded business drafts and persisted support, community,
partnership, sales and onboarding work.

Drafts are written from a real sandbox project (README, git history, code
routes, pages, scripts); every tool runs through the registry against real
rows. Only the outgoing SMTP connection is replaced, by a recorder.
"""
import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.auth import get_current_user_id
from app.core.business import mailer
from app.core.business.community import community_service
from app.core.tools.base import ToolConfig, ToolContext
from app.core.tools.registry import create_tool, get_registry
from app.main import app
from app.models.company_crm import CRMDeal
from app.models.content import CommunityItem, ContentItem, OnboardingFlow
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.business import BUSINESS_TOOLS
from tests.conftest import AsyncTestingSessionLocal

SANDBOX = Path("/tmp/jarv_sandbox")


def _run(coro):
    return asyncio.run(coro)


async def _call(name, data, ctx):
    return await create_tool(name, ToolConfig(authority_level=AuthorityLevel.LEVEL_6_DATABASE_WRITE)).execute(data, ctx)


@pytest.fixture
def project():
    name = f"r12e4a-{uuid4().hex[:8]}"
    root = SANDBOX / name
    (root / "app" / "pricing").mkdir(parents=True)
    (root / "api").mkdir()
    (root / "README.md").write_text("# Shopfront\n\nOnline store builder for makers.\n\n## Features\n\n"
                                    "- Drag and drop product pages\n- Stripe checkout\n- Inventory sync\n")
    (root / "package.json").write_text(json.dumps({"name": "shopfront", "scripts": {"build": "next build",
                                                                                  "test": "jest", "dev": "next dev"},
                                                   "dependencies": {"next": "14.2.0", "react": "18.3.0"}}))
    (root / "app" / "page.tsx").write_text("export default function Home() { return null }\n")
    (root / "app" / "pricing" / "page.tsx").write_text("export default function Pricing() { return null }\n")
    (root / "api" / "server.py").write_text("from fastapi import APIRouter\nrouter = APIRouter()\n\n"
                                            "@router.get('/products')\ndef products():\n    return []\n\n"
                                            "@router.post('/orders')\ndef orders():\n    return {}\n")
    git = ["git", "-c", "user.email=jarv@test", "-c", "user.name=JARV", "-c", f"safe.directory={root}"]
    subprocess.run(git + ["init", "-q"], cwd=root, check=True)
    subprocess.run(git + ["add", "-A"], cwd=root, check=True)
    subprocess.run(git + ["commit", "-qm", "Add Stripe checkout"], cwd=root, check=True)
    (root / "CHANGELOG.txt").write_text("x")
    subprocess.run(git + ["add", "-A"], cwd=root, check=True)
    subprocess.run(git + ["commit", "-qm", "Fix inventory sync race"], cwd=root, check=True)
    yield f"/test_workspaces/{name}", root
    shutil.rmtree(root, ignore_errors=True)


async def _seed(db, host=None):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="Shopfront", slug=f"sf-{ws_id.hex[:8]}",
                     description="Online store builder for makers", workspace_type="project", authority_level=5,
                     is_active=True, config={"root_path": host} if host else {}))
    await db.commit()
    return user_id, ws_id


def test_all_business_tools_are_registered():
    registry = get_registry()
    names = [t._name for t in BUSINESS_TOOLS]
    assert len(names) == len(set(names)) == 58  # support 7, marketing 7, content 10, onboarding 9, community 9, partnership 10, sales 6
    for name in names:
        assert registry.is_implemented(name), name
    send = create_tool("send_standard_reply_with_rules", ToolConfig())
    assert send.required_authority_level == AuthorityLevel.LEVEL_5_NETWORK_ACCESS


@pytest.mark.integration
def test_drafts_are_grounded_in_the_real_project(project):
    host, root = project

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db, host)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            changelog = await _call("create_changelog", {}, ctx)
            api = await _call("create_api_example", {}, ctx)
            landing = await _call("create_landing_copy", {"topic": "Launch week"}, ctx)
            press = await _call("create_press_release", {"topic": "Shopfront 1.0 is out", "save_to_workspace": True}, ctx)
            checklist = await _call("create_setup_checklist", {"audience": "new developers"}, ctx)
            tour = await _call("create_product_tour", {}, ctx)
            sequence = await _call("create_email_sequence", {"count": 3, "audience": "makers"}, ctx)
            campaign = await _call("create_campaign", {"topic": "Launch", "channels": ["email", "x"]}, ctx)
            flows = (await db.execute(select(OnboardingFlow).where(OnboardingFlow.workspace_id == ws_id))).scalars().all()
            items = (await db.execute(select(ContentItem).where(ContentItem.workspace_id == ws_id))).scalars().all()
            return changelog, api, landing, press, checklist, tour, sequence, campaign, flows, items

    changelog, api, landing, press, checklist, tour, sequence, campaign, flows, items = _run(run())
    assert changelog.success, changelog.error_message
    assert "Fix inventory sync race" in changelog.result_data["body"] and "Add Stripe checkout" in changelog.result_data["body"]
    assert changelog.result_data["generated_by"] == "workspace facts"
    assert "curl -X GET http://localhost:8000/products" in api.result_data["body"]
    assert "POST /orders" in api.result_data["body"]
    assert "Stripe checkout" in landing.result_data["body"]
    assert "[confirm: a quote from the founder]" in press.result_data["body"]
    assert "a quote from the founder" in press.result_data["needs_confirmation"]
    assert press.result_data["file"] and Path(root, "docs", "marketing").is_dir()
    steps = next(f for f in flows if f.flow_type == "setup_checklist").steps
    assert any("npm run build" in s["title"] for s in steps)
    assert "/pricing" in tour.result_data["body"]
    assert sequence.result_data["body"].count("## Email") == 3
    assert campaign.result_data["record_type"] == "marketing_campaign"
    assert all(i.status == "draft" and i.is_published is False for i in items)


@pytest.mark.integration
def test_support_inbox_escalation_faq_replies_and_send_rules(monkeypatch):
    sent = []

    async def record_send(to, subject, body, reply_to_id=None):
        sent.append({"to": to, "subject": subject, "body": body})
        return {"to": to, "subject": subject, "message_id": "<recorded@test>"}

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            approved = ToolContext(workspace_id=ws_id, db_session=db, approval_granted=True)
            bug = await _call("create_ticket", {"subject": "Checkout is down in production",
                                                "description": "Every order fails with error 500 since this morning",
                                                "customer_email": "ana@example.com", "customer_name": "Ana"}, ctx)
            await _call("update_faq", {"question": "How do I reset my password?",
                                       "answer": "Use 'Forgot password' on the sign-in page; the link lasts 30 minutes."}, ctx)
            account = await _call("create_ticket", {"subject": "Forgot my password",
                                                    "description": "How do I reset my password? I cannot sign in.",
                                                    "customer_email": "ben@example.com", "customer_name": "Ben Lee"}, ctx)
            draft = await _call("draft_reply", {"ticket_id": account.result_data["number"]}, ctx)
            unconfigured = await _call("send_standard_reply_with_rules", {"ticket_id": account.result_data["id"]},
                                       approved)
            monkeypatch.setattr(mailer, "send_email", record_send)
            paused = await _call("send_standard_reply_with_rules", {"ticket_id": account.result_data["id"]}, ctx)
            await _call("update_workspace_rules", {"change_summary": "allow account replies", "rules": [
                {"name": "auto account replies", "type": "support_reply",
                 "content": {"auto_send_categories": ["account"], "min_confidence": 0.2}}]}, ctx)
            by_rule = await _call("send_standard_reply_with_rules", {"ticket_id": account.result_data["id"]}, ctx)
            listed = await _call("read_support_messages", {}, ctx)
            summary = await _call("summarise_feedback", {}, ctx)
            task = (await db.execute(select(Task).where(Task.workspace_id == ws_id))).scalar_one()
            return bug, account, draft, unconfigured, paused, by_rule, listed, summary, task

    bug, account, draft, unconfigured, paused, by_rule, listed, summary, task = _run(run())
    assert bug.result_data["category"] == "bug" and bug.result_data["severity"] == "high"
    assert bug.result_data["status"] == "escalated" and task.context["agent"] == "debugging_agent"
    assert account.result_data["category"] == "account"
    assert draft.success and "Forgot password" in draft.result_data["body"] and draft.result_data["confidence"] > 0.2
    assert "Hi Ben" in draft.result_data["body"]
    assert unconfigured.success is False and "not configured" in unconfigured.error_message
    assert paused.success is False and paused.result_data["requires_approval"] is True
    assert by_rule.success and by_rule.result_data["authorised_by"] == "rule"
    assert sent and sent[0]["to"] == "ben@example.com" and "[" in sent[0]["subject"]
    assert len(listed.result_data["tickets"]) == 2 and listed.result_data["email"]["sending"] is False
    assert summary.result_data["by_category"] == {"bug": 1, "account": 1}


@pytest.mark.integration
def test_community_moderation_replies_partners_and_sales():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            approved = ToolContext(workspace_id=ws_id, db_session=db, approval_granted=True)
            spam = await community_service.ingest(db, ws_id, owner, author_name="bot", channel="forum",
                                                  content="Buy now! http://a.io http://b.io http://c.io free money")
            idea = await community_service.ingest(db, ws_id, owner, author_name="Maya", channel="discord",
                                                  title="Dark mode please",
                                                  content="Would be great to have dark mode for the editor")
            await db.commit()
            hidden = await _call("moderate_community_item_with_rules", {"item_id": str(spam.id)}, ctx)
            ok = await _call("moderate_community_item_with_rules", {"item_id": str(idea.id)}, ctx)
            reply = await _call("draft_community_reply", {"reply_to": str(idea.id), "message": idea.content}, ctx)
            inbox = await _call("read_community_messages", {}, ctx)
            community = await _call("summarise_community_feedback", {}, ctx)
            shortlist = await _call("create_partner_shortlist", {
                "partner_type": "integration",
                "candidates": [{"name": "Printful", "notes": "print on demand for makers"},
                               {"name": "Acme Payroll", "notes": "payroll for enterprises"}],
                "criteria": {"makers": 2, "print": 1}}, ctx)
            top = shortlist.result_data["shortlist"][0]
            contacted = await _call("update_partner_pipeline", {"partner_id": top["id"], "status": "contacted",
                                                                "notes": "intro sent"}, ctx)
            signed = await _call("update_partner_pipeline", {"partner_id": top["id"], "status": "active"}, ctx)
            signed_ok = await _call("update_partner_pipeline", {"partner_id": top["id"], "status": "active"}, approved)
            outreach = await _call("create_partner_outreach", {"partner_id": top["id"], "topic": "Joint launch"}, ctx)
            deal = await _call("update_sales_pipeline", {"title": "Craft Co annual", "value": 1200, "stage": "qualified",
                                                         "contact_name": "Ola", "contact_email": "ola@craft.co",
                                                         "company": "Craft Co"}, ctx)
            won = await _call("update_sales_pipeline", {"deal_id": deal.result_data["deal"]["id"], "stage": "closed_won"},
                              ctx)
            summary = await _call("create_sales_summary", {}, ctx)
            brief = await _call("create_prospect_brief", {"deal_id": deal.result_data["deal"]["id"]}, ctx)
            replies = (await db.execute(select(CommunityItem).where(CommunityItem.is_reply.is_(True)))).scalars().all()
            deals = (await db.execute(select(CRMDeal).where(CRMDeal.workspace_id == ws_id))).scalars().all()
            return (hidden, ok, reply, inbox, community, shortlist, contacted, signed, signed_ok, outreach, won, summary,
                    brief, replies, deals)

    (hidden, ok, reply, inbox, community, shortlist, contacted, signed, signed_ok, outreach, won, summary, brief,
     replies, deals) = _run(run())
    assert hidden.result_data["decision"] == "hidden" and ok.result_data["decision"] == "approved"
    assert reply.success and reply.result_data["record_type"] == "community_item" and len(replies) == 1
    assert len(inbox.result_data["messages"]) == 2
    assert "Dark mode please" in community.result_data["requests"]
    assert shortlist.result_data["shortlist"][0]["name"] == "Printful"
    assert contacted.result_data["status"] == "contacted"
    assert signed.success is False and signed.result_data["requires_approval"] is True
    assert signed_ok.success and signed_ok.result_data["status"] == "active"
    assert "Printful" in outreach.result_data["body"]
    assert won.result_data["deal"]["stage"] == "closed_won" and won.result_data["win_rate"] == 1.0
    assert "Craft Co annual" in summary.result_data["body"]
    assert "Ola" in brief.result_data["body"] and len(deals) == 1


@pytest.mark.integration
def test_onboarding_friction_copy_versions_and_knowledge_base():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            for n in range(3):
                await _call("create_ticket", {"subject": f"Cannot log in after sign up ({n})",
                                              "description": "I signed up but the login page says invalid"}, ctx)
            friction = await _call("analyse_activation_friction", {}, ctx)
            flow = await _call("create_onboarding_flow", {"topic": "first store", "audience": "makers"}, ctx)
            edited = await _call("update_onboarding_copy", {"flow_id": flow.result_data["id"], "step": 1,
                                                            "copy_text": "Name your store"}, ctx)
            kb1 = await _call("update_knowledge_base", {"title": "Connecting Stripe",
                                                        "body": "Go to Settings, then Payments."}, ctx)
            kb2 = await _call("update_knowledge_base", {"title": "Connecting Stripe",
                                                        "body": "Go to Settings, then Payments, then Connect."}, ctx)
            return friction, edited, kb1, kb2

    friction, edited, kb1, kb2 = _run(run())
    sources = [f["source"] for f in friction.result_data["findings"]]
    assert "support tickets" in sources
    assert edited.success and edited.result_data["version"] == 2
    assert edited.result_data["steps"][0]["copy"] == "Name your store"
    assert kb1.result_data["version"] == 1 and kb2.result_data["version"] == 2 and kb1.result_data["id"] == kb2.result_data["id"]


@pytest.mark.integration
def test_business_agents_use_their_tools(project):
    from app.core.agents.specialists.community import CommunityAgent
    from app.core.agents.specialists.customer_support import CustomerSupportAgent
    from app.core.agents.specialists.marketing import MarketingAgent

    host, _root = project

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db, host)
            ctx = AgentContext(workspace_id=ws_id, user_id=owner, db_session=db, metadata={"business_enabled": True})
            marketing = await MarketingAgent(AgentConfig(workspace_id=ws_id, user_id=owner,
                                                         authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).execute(
                {"campaign_type": "email", "target_audience": "makers", "message": "Launch week", "channels": ["email"]},
                ctx)
            await community_service.ingest(db, ws_id, owner, author_name="bot", content="casino click here http://x.io "
                                                                                        "http://y.io http://z.io")
            await db.commit()
            community = await CommunityAgent(AgentConfig(workspace_id=ws_id, user_id=owner,
                                                         authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).execute(
                {"action": "moderate", "platform": "forum"}, ctx)
            tool_ctx = ToolContext(workspace_id=ws_id, db_session=db)
            ticket = await _call("create_ticket", {"subject": "Where is my invoice?",
                                                   "description": "I need the invoice for last month"}, tool_ctx)
            support = await CustomerSupportAgent(AgentConfig(workspace_id=ws_id, user_id=owner,
                                                             authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).execute(
                {"ticket_id": ticket.result_data["number"]}, ctx)
            return marketing, community, support

    marketing, community, support = _run(run())
    assert marketing.success, marketing.error_message
    assert marketing.result_data["tool"] == "create_email_sequence" and "## Email 3" in marketing.result_data["body"]
    assert community.success and community.result_data["moderation"][0]["decision"] == "hidden"
    assert support.success and support.result_data["draft_reply"].startswith("Hi")


@pytest.mark.api
def test_business_and_support_apis_are_owner_scoped(client):
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return await _seed(db)

    owner, ws_id = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        draft = client.post(f"/api/business/{ws_id}/drafts/create_post", json={"topic": "We shipped dark mode"})
        drafts = client.get(f"/api/business/{ws_id}/drafts", params={"group": "marketing"})
        ticket = client.post(f"/api/support/{ws_id}/tickets", json={"subject": "Refund please",
                                                                    "description": "I was charged twice"})
        tickets = client.get(f"/api/support/{ws_id}/tickets")
        message = client.post(f"/api/business/{ws_id}/community/messages", json={"content": "Love it!",
                                                                                  "author_name": "Sam"})
        pipeline = client.get(f"/api/business/{ws_id}/pipeline")
        app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
        stranger = client.get(f"/api/support/{ws_id}/tickets")
        stranger_draft = client.post(f"/api/business/{ws_id}/drafts/create_post", json={})
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert draft.status_code == 200 and draft.json()["status"] == "draft"
    assert drafts.status_code == 200 and drafts.json()["drafts"][0]["kind"] == "create_post"
    assert ticket.status_code == 200 and ticket.json()["category"] == "billing"
    assert tickets.status_code == 200 and len(tickets.json()) == 1
    assert message.status_code == 200 and message.json()["status"] == "new"
    assert pipeline.status_code == 200 and pipeline.json()["deals"] == []
    assert stranger.status_code == 404 and stranger_draft.status_code == 404
