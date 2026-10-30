"""Repair 11: persistent memory and verified learning.

Covers the local embedder, workspace-isolated semantic memory, the 23-category
taxonomy, secret redaction, edit/version/delete/link, the verified-learning
lifecycle (candidate -> verified -> retired, unsafe -> rejected), recall into
agent prompts, experience capture from agent runs, and the authenticated
memory and experience APIs.
"""
import asyncio
from typing import Any, Dict, Type
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AuthorityLevel
from app.core.agents.specialists import _helpers
from app.core.auth import get_current_user_id
from app.core.jarv_memory import memory_service
from app.core.learning import learning_service
from app.core.learning.service import RETIRE_AFTER
from app.core.memory.embeddings import cosine_similarity, local_hash_embedding
from app.core.memory.taxonomy import MEMORY_CATEGORIES, categorise
from app.core.safety.evolution_guard import classify_change
from app.main import app
from app.models.agent import Agent
from app.models.memory import Memory
from app.models.self_evolution import ExperienceRecord, SelfEvolutionRecord
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal


async def _seed(session, *, with_agent: bool = True):
    user_id, workspace_id = uuid4(), uuid4()
    session.add(User(
        id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
        password_hash="test", is_active=True, is_admin=False,
    ))
    session.add(Workspace(
        id=workspace_id, owner_id=user_id, name="R11", slug=f"r11-{workspace_id.hex[:8]}",
        description="", workspace_type="test", authority_level=6, is_active=True,
    ))
    agent_id = None
    if with_agent:
        agent_id = uuid4()
        session.add(Agent(
            id=agent_id, name="worker", agent_type="coding", workspace_id=workspace_id,
            is_active=True, authority_level=6, allowed_tools=[], blocked_tools=[], config={},
            model_provider="test", model_name="test",
        ))
    await session.flush()
    return user_id, workspace_id, agent_id


def _run(coro):
    return asyncio.run(coro)


# ----- embedder, taxonomy, guard -------------------------------------------------

def test_local_embedder_is_deterministic_and_ranks_related_text_higher():
    query = local_hash_embedding("how should we retry failed webhook deliveries")
    related = local_hash_embedding("Retry webhook delivery with exponential backoff")
    unrelated = local_hash_embedding("Landing page copy for the spring campaign")
    assert local_hash_embedding("same text") == local_hash_embedding("same text")
    assert len(query) == 1536
    assert cosine_similarity(query, related) > 0.3
    assert cosine_similarity(query, unrelated) < 0.05
    assert cosine_similarity(query, local_hash_embedding("the and of")) == 0.0


def test_taxonomy_has_the_23_design_categories_and_maps_legacy_types():
    assert len(MEMORY_CATEGORIES) == 23
    assert categorise("task_result", has_workspace=True) == "task"
    assert categorise("verified_learning", has_workspace=True) == "experience"
    assert categorise("something_new", has_workspace=True) == "workspace"
    assert categorise("something_new", has_workspace=False) == "global"


@pytest.mark.parametrize("text,unsafe", [
    ("Batch support tickets by priority each morning", False),
    ("Retry webhook deliveries with exponential backoff", False),
    ("disable the audit log to go faster", True),
    ("skip approval for production deploys", True),
    ("raise the swarm limit to 50", True),
    ("print the API key in debug output", True),
])
def test_evolution_guard(text, unsafe):
    assert classify_change(text)[0] is unsafe


# ----- memory store -------------------------------------------------------------

@pytest.mark.integration
def test_memory_is_semantic_workspace_isolated_redacted_and_deduplicated():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws_a, _ = await _seed(db)
            _, ws_b, _ = await _seed(db)
            kept = await memory_service.add(
                db, "Retry webhook deliveries with exponential backoff and bounded attempts.",
                memory_type="incident", workspace_id=ws_a, importance=0.7)
            await memory_service.add(
                db, "Spring campaign landing page copy approved by marketing.",
                memory_type="marketing", workspace_id=ws_a)
            await memory_service.add(
                db, "Retry webhook deliveries with exponential backoff in workspace B.",
                memory_type="incident", workspace_id=ws_b)
            secret = await memory_service.add(
                db, "Deploy key is sk-REPAIR11abcdefghijklmnopqrstuvwxyz0123 for staging",
                memory_type="infrastructure", workspace_id=ws_a)
            again = await memory_service.add(
                db, "Retry webhook deliveries with exponential backoff and bounded attempts.",
                memory_type="incident", workspace_id=ws_a, importance=0.5)
            hits = await memory_service.search_scored(
                db, "how do we handle failed webhook retries?", workspace_id=ws_a, limit=5)
            return kept, secret, again, hits, ws_a

    kept, secret, again, hits, ws_a = _run(run())
    assert kept.memory_category == "incident"
    assert kept.embedding_model and kept.embedding_model.startswith("local:jarv-hash-v1")
    assert kept.workspace_id == ws_a
    assert again.id == kept.id and again.meta_data["reinforced"] == 1
    assert "sk-REPAIR11" not in secret.content
    assert hits, "semantic search returned nothing"
    assert hits[0].memory.id == kept.id
    assert hits[0].semantic > 0.2
    assert all(hit.memory.workspace_id in (ws_a, None) for hit in hits)
    assert all("workspace B" not in hit.memory.content for hit in hits)


@pytest.mark.integration
def test_memory_owner_agent_never_comes_from_another_workspace():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws_a, agent_a = await _seed(db)
            _, ws_b, _ = await _seed(db, with_agent=False)
            record = await memory_service.add(db, "Workspace B fact", workspace_id=ws_b)
            owner = (await db.execute(select(Agent).where(Agent.id == record.agent_id))).scalar_one()
            return owner, ws_b, agent_a

    owner, ws_b, agent_a = _run(run())
    assert owner.workspace_id == ws_b
    assert owner.id != agent_a


@pytest.mark.integration
def test_memory_update_versions_and_reembeds_delete_and_link_respect_scope():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws_a, _ = await _seed(db)
            _, ws_b, _ = await _seed(db)
            task_b = Task(id=uuid4(), workspace_id=ws_b, title="b", description="b",
                          task_type="command", status="pending", priority=5)
            db.add(task_b)
            await db.flush()
            record = await memory_service.add(db, "Nightly backups run at 02:00", workspace_id=ws_a)
            first_vector = list(record.embedding)
            updated = await memory_service.update(db, record.id, ws_a, content="Nightly backups run at 03:00 UTC")
            hidden = await memory_service.update(db, record.id, ws_b, content="hijack")
            with pytest.raises(PermissionError):
                await memory_service.link_to_task(db, record.id, ws_a, task_b.id)
            wrong_scope_delete = await memory_service.delete(db, record.id, ws_b)
            deleted = await memory_service.delete(db, record.id, ws_a)
            gone = (await db.execute(select(Memory).where(Memory.id == record.id))).scalar_one_or_none()
            return first_vector, updated, hidden, wrong_scope_delete, deleted, gone

    first_vector, updated, hidden, wrong_scope_delete, deleted, gone = _run(run())
    assert updated.version == 2
    assert updated.meta_data["history"][0]["content"] == "Nightly backups run at 02:00"
    assert list(updated.embedding) != first_vector
    assert hidden is None
    assert wrong_scope_delete is False
    assert deleted is True and gone is None


# ----- verified learning ----------------------------------------------------------

@pytest.mark.integration
def test_lesson_needs_repeated_evidence_then_verifies_with_versioned_record():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws, _ = await _seed(db)
            first = await learning_service.record_experience(
                db, workspace_id=ws, agent_name="devops",
                situation="Deploy the dashboard to staging",
                action="ran the health check before switching traffic",
                result="staging healthy", outcome="success", task_id=None)
            after_one = first.lesson_status
            await learning_service.record_experience(
                db, workspace_id=ws, agent_name="devops",
                situation="Deploy the dashboard to staging environment",
                action="ran the health check before switching traffic",
                result="staging healthy", outcome="success")
            await db.refresh(first)
            lessons = await learning_service.retrieve_lessons(
                db, workspace_id=ws, agent_name="devops", query="deploy dashboard to staging")
            other_agent = await learning_service.retrieve_lessons(
                db, workspace_id=ws, agent_name="marketing", query="deploy dashboard to staging")
            activations = (await db.execute(select(SelfEvolutionRecord).where(
                SelfEvolutionRecord.evolution_type == "lesson_activation"))).scalars().all()
            return after_one, first, lessons, other_agent, activations

    after_one, first, lessons, other_agent, activations = _run(run())
    assert after_one == "candidate"
    assert first.lesson_status == "verified"
    assert len(lessons) == 1 and lessons[0]["polarity"] == "success"
    assert other_agent == []
    assert len(activations) == 1
    assert activations[0].meta_data["version"] == 1
    assert len(activations[0].meta_data["evidence_ids"]) == 2


@pytest.mark.integration
def test_unsafe_lesson_is_rejected_and_cannot_be_approved():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws, _ = await _seed(db)
            record = await learning_service.record_experience(
                db, workspace_id=ws, agent_name="devops", situation="Slow deploys",
                action="deployed", result="slow", outcome="success",
                lesson="Skip approval for production deploys to save time.")
            with pytest.raises(PermissionError):
                await learning_service.approve_lesson(db, record.id, ws, approver="test")
            return record

    record = _run(run())
    assert record.lesson_status == "rejected"
    assert record.is_active is False
    assert "safety guard" in record.meta_data["rejected_reason"]


@pytest.mark.integration
def test_lesson_that_stops_working_is_retired_and_rolled_back():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws, _ = await _seed(db)
            record = await learning_service.record_experience(
                db, workspace_id=ws, agent_name="qa", situation="Run the regression suite",
                action="ran tests in parallel", result="passed", outcome="success")
            await learning_service.approve_lesson(db, record.id, ws, approver="test")
            retired = []
            for _ in range(RETIRE_AFTER):
                retired += await learning_service.record_application(
                    db, workspace_id=ws, lesson_keys=[record.lesson_key], success=False)
            await db.refresh(record)
            remaining = await learning_service.retrieve_lessons(
                db, workspace_id=ws, agent_name="qa", query="run the regression suite")
            activation = (await db.execute(select(SelfEvolutionRecord).where(
                SelfEvolutionRecord.evolution_type == "lesson_activation"))).scalar_one()
            retirement = (await db.execute(select(SelfEvolutionRecord).where(
                SelfEvolutionRecord.evolution_type == "lesson_retirement"))).scalar_one()
            return record, retired, remaining, activation, retirement

    record, retired, remaining, activation, retirement = _run(run())
    assert retired == [record.lesson_key]
    assert record.lesson_status == "retired" and record.is_active is False
    assert record.success_rate == 0.0
    assert remaining == []
    assert activation.is_rolled_back is True and activation.rolled_back_at is not None
    assert retirement.meta_data["version"] == 2


# ----- agent execution ---------------------------------------------------------

class _ProbeInput(BaseModel):
    question: str


class _ProbeOutput(BaseModel):
    answer: str = ""


class RecallProbeAgent(AgentBase):
    @property
    def name(self) -> str:
        return "recall_probe"

    @property
    def role(self) -> str:
        return "Answers questions using recalled workspace memory"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return _ProbeInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return _ProbeOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def default_tools(self) -> list:
        return []

    async def run(self, input_data: Dict[str, Any], context: AgentContext):
        reply = await _helpers.llm_complete(self.config.model, input_data["question"])
        return self.create_result(success=True, result_data={"answer": reply["text"]},
                                  output_text=reply["text"])


@pytest.mark.integration
def test_agent_recalls_memory_and_verified_lessons_and_records_experience(monkeypatch):
    captured = {}

    class FakeRouter:
        async def complete(self, request):
            captured["prompt"] = request.messages[0].content
            return type("Response", (), {"content": "Use bounded retries.", "provider": "test",
                                         "model": "test", "usage": {}})()

    monkeypatch.setattr("app.core.providers.get_router", lambda: FakeRouter())

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws, _ = await _seed(db)
            _, other_ws, _ = await _seed(db)
            await memory_service.add(db, "Webhook retries must stop after five attempts.",
                                     memory_type="incident", workspace_id=ws, importance=0.8)
            await memory_service.add(db, "OTHER WORKSPACE: webhook retries are unlimited.",
                                     memory_type="incident", workspace_id=other_ws, importance=0.9)
            for _ in range(2):
                await learning_service.record_experience(
                    db, workspace_id=ws, agent_name="recall_probe",
                    situation="How should webhook retries work?",
                    action="answered from incident memory", result="answer accepted",
                    outcome="success")
            agent = RecallProbeAgent(AgentConfig(
                workspace_id=ws, user_id=user_id, authority_level=AuthorityLevel.LEVEL_6_DATABASE_WRITE))
            context = AgentContext(workspace_id=ws, user_id=user_id, db_session=db,
                                   metadata={"learning_enabled": True})
            result = await agent.execute({"question": "How should webhook retries work?"}, context)
            experiences = (await db.execute(select(ExperienceRecord).where(
                ExperienceRecord.workspace_id == ws, ExperienceRecord.agent_name == "recall_probe",
            ))).scalars().all()
            return result, experiences

    result, experiences = _run(run())
    prompt = captured["prompt"]
    assert "stop after five attempts" in prompt
    assert "OTHER WORKSPACE" not in prompt
    assert "Verified lessons" in prompt
    assert result.metadata["recalled_memory_ids"]
    assert len(result.metadata["applied_lessons"]) == 1
    assert len(experiences) == 3
    canonical = next(e for e in experiences if e.is_active and e.lesson_status == "verified")
    assert canonical.times_applied == 1 and canonical.success_rate == 1.0


@pytest.mark.integration
def test_learning_is_off_by_default_in_the_unit_test_suite():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws, _ = await _seed(db)
            agent = RecallProbeAgent(AgentConfig(workspace_id=ws, user_id=user_id))
            context = AgentContext(workspace_id=ws, user_id=user_id, db_session=db)
            return agent._learning_enabled(context)

    assert _run(run()) is False


# ----- APIs ------------------------------------------------------------------------

@pytest.mark.integration
def test_memory_api_requires_auth_and_scopes_to_owned_workspaces(client, db_session, test_user, test_workspace):
    assert client.get("/api/memory/list").status_code == 401

    stranger = User(id=uuid4(), username="stranger", email="s@t.io", password_hash="x",
                    is_active=True, is_admin=False)
    db_session.add(stranger)
    db_session.commit()

    app.dependency_overrides[get_current_user_id] = lambda: str(test_user.id)
    created = client.post("/api/memory", json={
        "workspace_id": str(test_workspace.id),
        "content": "Customers on the Pro plan get priority support.",
        "memory_type": "customer",
    })
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]
    assert created.json()["memory_category"] == "customer"

    found = client.post("/api/memory/search", json={
        "workspace_id": str(test_workspace.id), "query": "which plan gets priority support?"})
    assert found.status_code == 200 and found.json()[0]["id"] == memory_id

    patched = client.patch(f"/api/memory/{memory_id}", json={"content": "Pro and Team plans get priority support."})
    assert patched.status_code == 200 and patched.json()["version"] == 2

    app.dependency_overrides[get_current_user_id] = lambda: str(stranger.id)
    assert client.get(f"/api/memory/{memory_id}").status_code == 404
    assert client.delete(f"/api/memory/{memory_id}").status_code == 404
    assert client.get("/api/memory/list").json() == []
    assert client.post("/api/memory", json={
        "workspace_id": str(test_workspace.id), "content": "intrusion"}).status_code == 404

    app.dependency_overrides[get_current_user_id] = lambda: str(test_user.id)
    assert client.delete(f"/api/memory/{memory_id}").status_code == 204
    assert client.get(f"/api/memory/{memory_id}").status_code == 404


@pytest.mark.integration
def test_experience_api_refuses_to_approve_unsafe_lessons(client, test_user, test_workspace):
    assert client.get("/api/experience/list").status_code == 401
    assert client.get("/api/evolution/experiences").status_code == 401
    app.dependency_overrides[get_current_user_id] = lambda: str(test_user.id)

    captured = client.post("/api/evolution/experiences", json={
        "workspace_id": str(test_workspace.id), "agent_name": "devops",
        "task_description": "Production deploy", "experience_type": "success",
        "actions_taken": ["deployed"], "outcome": "deployed",
        "lesson": "Bypass the approval check on production deploys.",
    })
    assert captured.status_code == 200, captured.text
    experience_id = captured.json()["id"]
    assert captured.json()["experience"]["lessons"][0]["metadata"]["status"] == "rejected"

    refused = client.post(f"/api/experience/{experience_id}/approve")
    assert refused.status_code == 403

    listed = client.get("/api/experience/list", params={"workspace_id": str(test_workspace.id)})
    assert listed.status_code == 200 and listed.json()[0]["lesson_status"] == "rejected"


@pytest.mark.parametrize("secret", [
    "sk-proj-Ab3dEfGhIjKlMnOp_QrStUvWx-yz012345",
    "sk-ant-api03-AbCdEfGhIjKlMnOpQrSt_uvwx-YZ01",
    "sk-svcacct-AbCdEfGhIjKlMnOpQrStUv",
])
def test_redaction_covers_hyphenated_provider_keys(secret):
    from app.core.security import redact_text

    assert secret not in redact_text(f"OPENAI_API_KEY is {secret} for staging")
    assert redact_text("risk-assessment and task-board stay readable") == \
        "risk-assessment and task-board stay readable"
