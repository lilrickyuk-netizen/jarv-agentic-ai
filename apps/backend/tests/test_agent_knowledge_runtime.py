"""Persistent source knowledge and individual 31-agent runtime verification."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.agents.registry import get_registry
from app.core.agents.runner import AgentRunner
from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.config import settings
from app.core.knowledge.catalog import SPECIALIST_KNOWLEDGE, specialist_knowledge
from app.core.knowledge.context import set_knowledge_context
from app.core.knowledge.service import knowledge_service
from app.core.agents.specialists import _helpers
from app.models.agent import Agent
from app.models.agent_knowledge import AgentKnowledge
from app.models.memory import Memory
from app.models.user import User
from app.models.workspace import Workspace
from app.core.agents.specialists.security import SecurityAgent
from app.core.agents.specialists.research import ResearchAgent
from app.core.auth import get_current_user_id
from app.main import app
from tests.conftest import AsyncTestingSessionLocal


@pytest.mark.integration
def test_knowledge_ingestion_is_idempotent_retrievable_and_versioned():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            installed = await knowledge_service.ingest(session, specialist_knowledge())
            await session.commit()
            assert installed == {"inserted": len(specialist_knowledge()), "updated": 0, "unchanged": 0}

            repeated = await knowledge_service.ingest(session, specialist_knowledge())
            assert repeated == {"inserted": 0, "updated": 0, "unchanged": len(specialist_knowledge())}

            record = (await session.execute(select(AgentKnowledge).where(
                AgentKnowledge.agent_name == "security",
                AgentKnowledge.knowledge_key == "specialist-core",
                AgentKnowledge.is_active.is_(True),
            ))).scalar_one()
            retrieved = await knowledge_service.retrieve(
                session, agent_name="security",
                query="Review object-level authorization and SSRF risks",
            )
            assert retrieved
            assert retrieved[0]["id"] == str(record.id)
            assert retrieved[0]["source_url"].startswith("https://")
            assert "OWASP Top 10 API Security Risks" in retrieved[0]["source_title"]
            assert "object-level authorization" in retrieved[0]["content"]

            revised = await knowledge_service.revise(
                session, agent_name="security", knowledge_key=record.knowledge_key,
                title=record.title, content=record.content + "\nReview limits too.",
                keywords=list(record.keywords) + ["rate limit"],
                source_url=record.source_url, source_title=record.source_title,
                source_publisher=record.source_publisher,
                verified_at=datetime.now(timezone.utc),
            )
            versions = await knowledge_service.list_versions(
                session, agent_name="security", knowledge_key=record.knowledge_key,
            )
            return record, revised, versions

    previous, revised, versions = asyncio.run(run())
    assert len(versions) == 2
    assert previous.is_active is False
    assert revised.is_active is True
    assert revised.version == previous.version + 1
    assert revised.previous_version_id == previous.id
    assert revised.content_sha256 != previous.content_sha256


def test_shared_model_prompt_receives_retrieved_source_material(monkeypatch):
    captured = {}

    class FakeRouter:
        async def complete(self, request):
            captured["prompt"] = request.messages[0].content
            return type("Response", (), {
                "content": "I used the provided source material.",
                "provider": "test-provider", "model": "test-model", "usage": {},
            })()

    monkeypatch.setattr("app.core.providers.get_router", lambda: FakeRouter())
    reference = {
        "title": "Specialist security brief",
        "content": "Check object-level authorization for caller-supplied identifiers.",
        "source_url": "https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/",
    }
    token = set_knowledge_context([reference])

    async def run():
        return await _helpers.llm_complete("test-model", "Review this API handler")

    try:
        result = asyncio.run(run())
    finally:
        set_knowledge_context((), reset_token=token)

    assert result is not None
    assert "object-level authorization" in captured["prompt"]
    assert reference["source_url"] in captured["prompt"]
    assert "Review this API handler" in captured["prompt"]


@pytest.mark.integration
def test_direct_agent_execute_retrieves_and_attaches_verified_knowledge(
    monkeypatch, test_user, test_workspace,
):
    monkeypatch.setattr(settings, "TESTING", False)
    async def run():
        async with AsyncTestingSessionLocal() as session:
            await knowledge_service.ingest(session, specialist_knowledge())
            await session.commit()
            config = AgentConfig(
                agent_id=uuid4(), workspace_id=test_workspace.id,
                user_id=test_user.id,
                authority_level=AuthorityLevel.LEVEL_9_SWARM_CREATION,
            )
            agent = SecurityAgent(config)
            context = AgentContext(
                workspace_id=test_workspace.id, user_id=test_user.id,
                db_session=session,
            )
            return await agent.execute({
                "scan_type": "code",
                "targets": [],
            }, context)

    result = asyncio.run(run())
    references = result.metadata["specialist_knowledge"]
    assert result.success is True
    assert references
    assert references[0]["source_url"].startswith("https://")


@pytest.mark.integration
def test_authenticated_knowledge_api_installs_retrieves_and_revises(
    client, db_session, test_user,
):
    app.dependency_overrides[get_current_user_id] = lambda: str(test_user.id)

    denied = client.post("/api/knowledge/catalog/install")
    assert denied.status_code == 403

    test_user.is_admin = True
    db_session.commit()
    installed = client.post("/api/knowledge/catalog/install")
    assert installed.status_code == 200, installed.text
    assert installed.json()["inserted"] == len(specialist_knowledge())

    retrieved = client.get(
        "/api/knowledge/agents/security",
        params={"query": "object-level authorization SSRF"},
    )
    assert retrieved.status_code == 200, retrieved.text
    record = retrieved.json()["records"][0]
    assert record["source_url"].startswith("https://")
    assert record["source_title"] == "OWASP Top 10 API Security Risks - 2023"

    revised = client.put(
        "/api/knowledge/agents/security/specialist-core",
        json={
            "title": "Security review guidance",
            "content": record["content"] + "\nVerify updated behavior with regression tests.",
            "keywords": record["keywords"] + ["regression tests"],
            "source_url": record["source_url"],
            "source_title": record["source_title"],
            "source_publisher": record["source_publisher"],
            "source_license": record["source_license"],
            "source_author": record["source_author"],
            "source_author_url": record["source_author_url"],
            "verified_at": "2026-10-21T00:00:00Z",
        },
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["version"] == 2
    assert revised.json()["active"] is True

    updated = client.get(
        "/api/knowledge/agents/security",
        params={"query": "regression tests object authorization"},
    )
    assert updated.status_code == 200
    assert updated.json()["records"][0]["version"] == 2
    assert "regression tests" in updated.json()["records"][0]["content"]


@pytest.mark.integration
def test_research_agent_persists_live_source_license_and_author(monkeypatch):
    from app.core.config import settings

    source = {
        "title": "API authorization guidance",
        "url": "https://stackoverflow.com/questions/321/api-authorization",
        "publisher": "Stack Overflow",
        "content": "Object-level authorization must be checked per identifier.",
        "license": "CC BY-SA 4.0",
        "author": "Test author",
        "author_url": "https://stackoverflow.com/users/7/test-author",
        "page_created_at": "2026-10-20T00:00:00+00:00",
        "retrieved_at": "2026-10-21T00:00:00+00:00",
    }

    async def fake_search(query, limit=3):
        return [source]

    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(ResearchAgent, "_provider_configured", staticmethod(lambda: False))
    monkeypatch.setattr(
        "app.core.research.public_search.search_public_sources", fake_search,
    )

    async def run():
        async with AsyncTestingSessionLocal() as session:
            agent = ResearchAgent(AgentConfig(
                agent_id=uuid4(), authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS,
            ))
            context = AgentContext(db_session=session)
            result = await agent.run({
                "query": "API authorization", "sources": [], "depth": "shallow",
            }, context)
            await session.flush()
            record = (await session.execute(select(AgentKnowledge).where(
                AgentKnowledge.agent_name == "research",
                AgentKnowledge.knowledge_key.startswith("public-source-"),
            ))).scalar_one()
            return result, record

    result, record = asyncio.run(run())
    assert result.result_data["external_search_used"] is True
    public_finding = result.result_data["findings"][0]
    assert public_finding["source_license"] == "CC BY-SA 4.0"
    assert public_finding["source_author_url"] == source["author_url"]
    assert record.source_license == "CC BY-SA 4.0"
    assert record.source_author == "Test author"
    assert record.source_author_url == source["author_url"]


@pytest.mark.integration
def test_research_records_api_authenticates_and_scopes_private_memory(
    client, db_session, test_user, test_workspace,
):
    owner_agent_id = uuid4()
    other_user_id, other_workspace_id, other_agent_id = uuid4(), uuid4(), uuid4()
    db_session.add(Agent(
        id=owner_agent_id, name="research owner", agent_type="research",
        workspace_id=test_workspace.id, is_active=True, authority_level=5,
        allowed_tools=[], blocked_tools=[], config={}, model_provider="test",
        model_name="test",
    ))
    db_session.add(User(
        id=other_user_id, username=f"u{other_user_id.hex[:8]}",
        email=f"{other_user_id.hex[:8]}@t.io", password_hash="test",
        is_active=True, is_admin=False,
    ))
    db_session.add(Workspace(
        id=other_workspace_id, owner_id=other_user_id, name="Other", 
        slug=f"other-{other_workspace_id.hex[:8]}", description="",
        workspace_type="test", authority_level=5, is_active=True,
    ))
    db_session.add(Agent(
        id=other_agent_id, name="other research", agent_type="research",
        workspace_id=other_workspace_id, is_active=True, authority_level=5,
        allowed_tools=[], blocked_tools=[], config={}, model_provider="test",
        model_name="test",
    ))
    db_session.add_all([
        Memory(id=uuid4(), agent_id=owner_agent_id, memory_type="research",
               content="private owner finding", importance_score=0.5,
               access_count=0, context={}, meta_data={}),
        Memory(id=uuid4(), agent_id=other_agent_id, memory_type="research",
               content="private other owner finding", importance_score=0.5,
               access_count=0, context={}, meta_data={}),
    ])
    db_session.commit()

    unauthenticated = client.get("/api/research/records")
    assert unauthenticated.status_code == 401

    app.dependency_overrides[get_current_user_id] = lambda: str(test_user.id)
    response = client.get("/api/research/records")
    assert response.status_code == 200, response.text
    content = [record["content"] for record in response.json()]
    assert "private owner finding" in content
    assert "private other owner finding" not in content


@pytest.mark.agent
@pytest.mark.integration
@pytest.mark.parametrize(
    "agent_name",
    sorted(get_registry().REQUIRED_AGENTS),
)
def test_each_agent_retrieves_and_receives_its_verified_knowledge(
    agent_name, monkeypatch, test_user, test_workspace
):
    for key in ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setattr(settings, key, None, raising=False)

    catalog_entry = next(item for item in SPECIALIST_KNOWLEDGE
                         if item["agent_name"] == agent_name)
    task = (
        f"Apply this specialist guidance to a task: "
        f"{', '.join(catalog_entry['keywords'])}. Explain the operational considerations."
    )

    async def run():
        async with AsyncTestingSessionLocal() as session:
            await knowledge_service.ingest(session, specialist_knowledge())
            await session.commit()
            result = await AgentRunner().run_agent(
                agent_name=agent_name,
                task=task,
                workspace_id=test_workspace.id,
                user_id=test_user.id,
                db=session,
            )
            attached_agent = (await session.execute(select(Agent).where(
                Agent.workspace_id == test_workspace.id,
                Agent.agent_type == agent_name,
            ))).scalar_one_or_none()
            return result, attached_agent

    result, attached_agent = asyncio.run(run())
    assert attached_agent is not None, f"{agent_name}: no persisted runtime agent"
    assert result["agent"] == agent_name
    assert result["success"] is True, result.get("error")
    assert result["output_text"].strip()
    evidence = result.get("specialist_knowledge") or []
    assert evidence, f"{agent_name}: retrieved knowledge was not attached to execution"
    assert evidence[0]["source_url"].startswith("https://")
    assert evidence[0]["id"]
    assert evidence[0]["version"] >= 1