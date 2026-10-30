"""Repair 13: every agent carries a library of expert knowledge in its field.

Real: the catalogue (core brief plus library topics for all 31 agents, each
attributed to a source that was read), ingestion and versioning, relevance
ranking, the consult_specialist_knowledge tool through the registry and
through an agent's toolbox, and knowledge attached to an agent's run.
"""
import asyncio
from collections import Counter
from uuid import uuid4

import pytest

from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.agents.registry import get_registry as agent_registry
from app.core.knowledge.catalog import specialist_knowledge
from app.core.knowledge.library.sources import SOURCES
from app.core.knowledge.service import knowledge_service, relevance
from app.core.tools.base import ToolConfig, ToolContext
from app.core.tools.registry import create_tool, get_registry
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal


def _run(coro):
    return asyncio.run(coro)


async def _seed(db):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="MYCO", slug=f"myco-{ws_id.hex[:8]}", description="",
                     workspace_type="project", authority_level=9, is_active=True, config={}))
    await db.commit()
    return user_id, ws_id


def test_every_agent_has_a_sourced_library_of_its_field():
    entries = specialist_knowledge()
    agents = set(agent_registry().REQUIRED_AGENTS)
    per_agent = Counter(e["agent_name"] for e in entries)
    assert set(per_agent) == agents
    assert min(per_agent.values()) >= 6, per_agent
    keys = Counter((e["agent_name"], e["knowledge_key"]) for e in entries)
    assert max(keys.values()) == 1
    library = [e for e in entries if e["knowledge_key"] != "specialist-core"]
    used = {e["url"] for e in library}
    for entry in library:
        assert entry["url"].startswith("https://"), entry["knowledge_key"]
        assert len(entry["content"].split()) >= 35, (entry["agent_name"], entry["knowledge_key"])
        assert len(entry["keywords"]) >= 3 and entry["source_title"] and entry["publisher"]
    assert used <= {s["url"] for s in SOURCES.values()}
    assert {s["url"] for s in SOURCES.values()} <= used | {e["url"] for e in entries}  # no unused sources
    assert len({e["publisher"] for e in library}) >= 25  # many independent authorities, not one


@pytest.mark.parametrize("agent,query,expected", [
    ("devops", "harden the github actions workflow and its secrets", "ci-security"),
    ("finance", "calculate MRR and churn rate for this month", "saas-metrics"),
    ("marketing", "can we email our newsletter to these contacts without consent", "email-consent"),
    ("infrastructure", "lock down ssh access to the vps", "ssh-hardening"),
    ("memory", "which pgvector index should we use hnsw or ivfflat", "vector-search"),
    ("legal", "cookie banner consent for analytics", "storage-access"),
    ("self_healing", "overloaded servers failing one after another as load shifts", "overload"),
    ("growth", "is the a/b test significant yet, can we stop it", "ab-testing"),
    ("creation", "which image format for the logo and photos", "image-formats"),
    ("research", "who published this source and is it credible", "sift"),
])
def test_relevance_ranks_the_matching_topic_first(agent, query, expected):
    ranked = sorted(((relevance(query, e["title"], e["content"], e["keywords"], e["source_title"], e["publisher"]),
                      e["knowledge_key"]) for e in specialist_knowledge() if e["agent_name"] == agent), reverse=True)
    assert ranked[0][1] == expected, ranked[:3]


@pytest.mark.integration
def test_library_is_installed_versioned_and_consultable():
    catalogue = specialist_knowledge()

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            first = await knowledge_service.ingest(db, catalogue)
            again = await knowledge_service.ingest(db, catalogue)
            await db.commit()
            ctx = ToolContext(workspace_id=ws_id, db_session=db, metadata={"agent": "security"})
            tool = create_tool("consult_specialist_knowledge", ToolConfig(authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))
            own = await tool.execute({"query": "a leaked api key was committed to git"}, ctx)
            other = await tool.execute({"query": "corporation tax payment deadline", "field": "finance"}, ctx)
            unknown = await tool.execute({"query": "anything", "field": "astrology"}, ctx)
            nothing = await tool.execute({"query": "zzqx unrelated xyzzy"}, ctx)
            no_field = await tool.execute({"query": "secrets"}, ToolContext(workspace_id=ws_id, db_session=db))
            return first, again, own, other, unknown, nothing, no_field

    first, again, own, other, unknown, nothing, no_field = _run(run())
    assert first["inserted"] + first["updated"] + first["unchanged"] == len(catalogue)
    assert again == {"inserted": 0, "updated": 0, "unchanged": len(catalogue)}
    assert get_registry().get_metadata("consult_specialist_knowledge").category == "knowledge"
    assert own.success and own.result_data["field"] == "security"
    top = own.result_data["topics"][0]
    assert top["title"] == "Handling secrets" and top["url"].startswith("https://cheatsheetseries.owasp.org")
    assert "revoke" in top["guidance"].lower()
    assert other.success and other.result_data["topics"][0]["title"] in (
        "UK company tax obligations", "Directors' financial responsibilities")
    assert "9 months and 1 day" in " ".join(t["guidance"] for t in other.result_data["topics"])
    assert unknown.success is False and "astrology" in unknown.error_message
    assert nothing.success and nothing.result_data["topics"] == []
    assert no_field.success is False


@pytest.mark.integration
def test_every_agent_toolbox_offers_its_knowledge_and_runs_carry_it():
    from app.core.agents.specialists.finance import FinanceAgent
    from app.core.agents.toolbox import AgentToolbox

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            await knowledge_service.ingest(db, specialist_knowledge())
            await db.commit()
            agent = FinanceAgent(AgentConfig(workspace_id=ws_id, user_id=owner,
                                             authority_level=AuthorityLevel.LEVEL_8_FINANCIAL))
            ctx = AgentContext(workspace_id=ws_id, user_id=owner, db_session=db)
            toolbox = AgentToolbox(agent, ctx)
            await toolbox.prepare()
            consulted = await toolbox.call("consult_specialist_knowledge", {"query": "how do we respond to a chargeback"})
            result = await agent.execute({"operation": "reporting", "time_period": "30d",
                                          "category": "MRR churn and ARPU"}, ctx)
            return toolbox.available, consulted, result

    available, consulted, result = _run(run())
    assert "consult_specialist_knowledge" in available
    assert consulted["success"], consulted
    assert consulted["data"]["field"] == "finance"
    assert consulted["data"]["topics"][0]["title"] == "Handling payment disputes"
    knowledge = result.metadata["specialist_knowledge"]
    assert 1 <= len(knowledge) <= 4
    assert any(k["title"] == "Calculating subscription metrics correctly" for k in knowledge)
