"""
Upgrade 2: knowledge-enhanced reasoning. Requirements first (a numbered list from the mission and the
specification, worked from, and checked with evidence for each); the workspace's specification as searchable
knowledge, rebuilt when it changes; one ranking over every kind of knowledge; harder thinking for the checks.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.command.requirements import derive, render, unmet_without_evidence, update
from app.core.providers import CompletionResponse
from tests.conftest import AsyncTestingSessionLocal


def _call(name, args, i=0):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class _Analyst:
    def __init__(self, items=None, fail=False):
        self.items, self.fail, self.requests = items or [], fail, []

    async def complete(self, request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("provider down")
        return CompletionResponse(id="r", model="m", content="", usage={"total_tokens": 7},
                                  tool_calls=[_call("record_requirements", {"requirements": self.items})])


def test_requirements_are_numbered_with_their_source_and_hard_findings_are_their_own():
    analyst = _Analyst([{"text": "Python pinned to 3.14.7 in .python-version and both pyproject.toml files",
                         "source": "spec §40.1"},
                        {"text": "TypeScript 7.0.2 in every package", "source": "spec §40.2"}])
    out = asyncio.run(derive(analyst, "m", "Bring Phase 0 into conformance.", spec="| Python | 3.14.7 |",
                             findings=["[open_blockers] docs/adr/0006.md: status is Open"]))
    reqs = out["requirements"]
    assert [r["id"] for r in reqs] == ["R1", "R2", "R3"] and out["tokens"] == 7
    assert reqs[0]["source"] == "spec §40.1" and reqs[0]["status"] == "open"
    assert reqs[2]["source"] == "hard check" and "0006" in reqs[2]["text"]
    request = analyst.requests[0]
    assert request.reasoning_effort == "high" and request.tools[0]["name"] == "record_requirements"
    assert "| Python | 3.14.7 |" in request.messages[0].content
    assert "R1 [open] Python pinned" in render(reqs)


def test_a_failed_requirements_step_falls_back_to_the_mission():
    out = asyncio.run(derive(_Analyst(fail=True), "m", "Add sub(a, b) to src/app.py."))
    assert [(r["id"], r["source"]) for r in out["requirements"]] == [("R1", "mission")]


def test_status_updates_need_evidence_and_a_known_id():
    reqs = [{"id": "R1", "text": "a", "source": "mission", "status": "open", "evidence": ""},
            {"id": "R2", "text": "b", "source": "mission", "status": "open", "evidence": ""}]
    assert update(reqs, {"id": "R1", "status": "done", "evidence": ""})["success"] is False
    ok = update(reqs, {"id": "r1", "status": "done", "evidence": "pytest: 3 passed"})
    assert ok["success"] and ok["still_open"] == ["R2"] and reqs[0]["evidence"] == "pytest: 3 passed"
    assert update(reqs, {"id": "R9", "status": "done", "evidence": "x"})["success"] is False
    assert update(reqs, {"id": "R2", "status": "finished", "evidence": "x"})["success"] is False


def test_a_requirement_without_evidence_is_unmet():
    reqs = [{"id": "R1", "text": "Python 3.14.7", "source": "spec", "status": "done", "evidence": "x"},
            {"id": "R2", "text": "TypeScript 7.0.2", "source": "spec", "status": "done", "evidence": "x"},
            {"id": "R3", "text": "ADR-0006 resolved", "source": "spec", "status": "done", "evidence": "x"}]
    checks = [{"requirement": "R1 Python pin", "met": True, "evidence": "read .python-version: 3.14.7"},
              {"requirement": "R2", "met": True, "evidence": ""},
              {"requirement": "R3", "met": False, "evidence": "status still Open"}]
    unmet = unmet_without_evidence(reqs, checks)
    assert [u.split(" ")[0] for u in unmet] == ["R2", "R3"]


def test_the_checks_think_harder_than_the_work():
    from app.core.providers.base import CompletionRequest, Message
    from app.core.providers.openai import OpenAIProvider

    provider = object.__new__(OpenAIProvider)
    tools = [{"name": "read_file", "description": "d", "input_schema": {"type": "object"}}]
    base = dict(model="gpt-6-luna", messages=[Message(role="user", content="x")], tools=tools)
    assert provider._responses_request(CompletionRequest(**base))["reasoning"] == {"effort": "medium"}
    assert provider._responses_request(CompletionRequest(**base, reasoning_effort="high"))["reasoning"] == {
        "effort": "high"}
    assert provider._responses_request(CompletionRequest(**base, reasoning_effort="lots"))["reasoning"] == {
        "effort": "medium"}


class _Router:
    """Analyst lists two requirements; the mission marks R1 done and finishes; the Verifier checks R1 only."""

    def __init__(self):
        self.first, self.mission_turns = {}, [
            [("requirement_status", {"id": "R1", "status": "done", "evidence": "edited src/app.py"})],
            [("finish", {"summary": "Added sub.", "success": True})]]

    async def complete(self, request):
        system = request.system or ""
        who = ("analyst" if system.startswith("You are JAI's requirements analyst") else
               "verifier" if system.startswith("You are JAI's Verifier Agent") else "mission")
        self.first.setdefault(who, request.messages[0].content)
        if who == "analyst":
            calls = [_call("record_requirements", {"requirements": [
                {"text": "sub(a, b) in src/app.py", "source": "mission"},
                {"text": "a test for sub in tests/test_app.py", "source": "mission"}]})]
        elif who == "mission":
            turn = self.mission_turns.pop(0) if self.mission_turns else [("finish", {"summary": "x", "success": True})]
            calls = [_call(name, args, i) for i, (name, args) in enumerate(turn)]
        else:
            calls = [_call("verdict", {"verified": True, "unmet": [], "checks": [
                {"requirement": "R1 sub in src/app.py", "met": True, "evidence": "read src/app.py"}]})]
        return CompletionResponse(id="r", model="test", content="", usage={"total_tokens": 3}, tool_calls=calls)


@pytest.mark.integration
def test_missions_work_from_the_list_and_every_requirement_needs_evidence(monkeypatch):
    from app.core.command import agent_executor
    from app.core.command.agent_executor import AgentExecutor
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    host, folder = _mission_folder()
    router = _Router()
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            return await AgentExecutor(rt, "test-model", host).run("Add sub(a, b) to src/app.py with a test.",
                                                                   max_continuations=0)

    try:
        result = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert "R1 [open] sub(a, b) in src/app.py" in router.first["mission"]
    assert "R2 [open] a test for sub" in router.first["mission"]
    assert "THE MISSION'S REQUIREMENTS" in router.first["verifier"]
    reqs = result["requirements"]
    assert reqs[0]["status"] == "done" and reqs[0]["evidence"] == "edited src/app.py" and reqs[1]["status"] == "open"
    verification = result["verification"]
    assert verification["verified"] is False and result["success"] is False and result["needs_continuation"]
    assert any(item.startswith("R2 ") for item in verification["unmet"])


@pytest.mark.integration
def test_a_carried_over_list_is_reused_not_derived_again(monkeypatch):
    from app.core.command import agent_executor
    from app.core.command.agent_executor import AgentExecutor
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    host, folder = _mission_folder()
    router = _Router()
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)
    carried = [{"id": "R1", "text": "sub(a, b) in src/app.py", "source": "mission", "status": "done",
                "evidence": "edited"},
               {"id": "R2", "text": "a test for sub", "source": "mission", "status": "open", "evidence": ""}]

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            return await AgentExecutor(rt, "test-model", host).run("Add sub.", max_continuations=0,
                                                                   requirements=carried)

    try:
        result = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert "analyst" not in router.first
    assert "R1 [done] sub(a, b) in src/app.py" in router.first["mission"]
    assert carried[1]["status"] == "open"  # the caller's copy is not changed in place
    assert result["requirements"][0]["status"] == "done"


@pytest.mark.integration
def test_the_specification_is_searchable_knowledge_rebuilt_when_it_changes():
    from sqlalchemy import select

    from app.core.knowledge.ingest import KnowledgeIngestor
    from app.core.knowledge.search import search_everything, search_passages
    from app.core.workspaces.fs_inspector import SANDBOX_CONTAINER_ROOT
    from app.models.company_operations import LiveOperationsFeedItem
    from app.models.user import User
    from app.models.workspace import Workspace

    folder = Path(SANDBOX_CONTAINER_ROOT) / f"spec-{uuid4().hex[:8]}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    tag = uuid4().hex[:8]
    (folder / "SPEC.md").write_text(f"# Spec\n\n## 40.1 Runtime\n\nPython is locked at 3.14.7. pin{tag}\n\n"
                                    "## 41 Provenance\n\nEvery artifact has a digest.\n")
    ingestor = KnowledgeIngestor()

    async def run():
        async with AsyncTestingSessionLocal() as db:
            if db.get_bind().dialect.name != "postgresql":
                return None
            uid, wid, other = uuid4(), uuid4(), uuid4()
            db.add(User(id=uid, username=f"u{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.io", password_hash="$2b$12$x",
                        is_active=True, is_admin=False))
            for w in (wid, other):
                db.add(Workspace(id=w, name=f"W{w.hex[:4]}", slug=f"w-{w.hex[:8]}", description="d", owner_id=uid,
                                 is_active=True, workspace_type="software", authority_level=4, config={}))
            await db.commit()
            first = await ingestor.ingest_workspace_document(db, wid, folder, "SPEC.md")
            again = await ingestor.ingest_workspace_document(db, wid, folder, "SPEC.md")
            escape = await ingestor.ingest_workspace_document(db, wid, folder, "../etc/passwd")
            hits = await search_passages(db, f"python locked pin{tag}", workspace_id=wid, workspace_only=True)
            unseen = await search_passages(db, f"pin{tag}", workspace_id=other, workspace_only=True)
            everything = await search_everything(db, f"pin{tag}", agent="verifier", workspace_id=wid)
            (folder / "SPEC.md").write_text(f"# Spec\n\n## 40.1 Runtime\n\nPython is locked at 3.15.0. pin{tag}\n")
            changed = await ingestor.ingest_workspace_document(db, wid, folder, "SPEC.md")
            await db.commit()
            feed = (await db.execute(select(LiveOperationsFeedItem).where(
                LiveOperationsFeedItem.workspace_id == wid, LiveOperationsFeedItem.title == "Specification changed"))
                    ).scalars().all()
            after = await search_passages(db, f"pin{tag}", workspace_id=wid, workspace_only=True)
            return first, again, escape, hits, unseen, everything, changed, feed, after

    try:
        out = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if out is None:
        pytest.skip("passage search needs PostgreSQL")
    first, again, escape, hits, unseen, everything, changed, feed, after = out
    assert first["status"] == "updated" and first["passages"] == 2 and again["status"] == "unchanged"
    assert escape["status"] == "error"
    assert hits and "40.1 Runtime" in hits[0]["heading_path"] and hits[0]["url"].startswith("workspace://")
    assert unseen == []
    assert everything and everything[0]["kind"] == "specification"
    assert changed["version"] == 2 and len(feed) == 1
    assert "3.15.0" in after[0]["content"]
