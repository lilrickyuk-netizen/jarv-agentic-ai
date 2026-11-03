"""
Upgrade 3: the Artifact Intelligence Graph. A mission's writes and commands, its requirements and the Verifier's
evidence become linked records, so "what proves R1?" and "why is this file the way it is?" are a query. Hard-check
failures contradict the file or decision that disagrees with the specification. Workspaces never see each other's
records, and the backfill can be run twice without adding anything.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.providers import CompletionResponse
from tests.conftest import AsyncTestingSessionLocal


def _call(name, args, i=0):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class _Router:
    """Requirements R1; the mission writes src/app.py, compiles it and finishes; the Verifier cites both."""

    def __init__(self):
        self.mission_turns = [
            [("write_file", {"path": "src/app.py", "content": "def add(a, b):\n    return a + b\n\n\n"
                                                              "def sub(a, b):\n    return a - b\n"})],
            [("run_command", {"command": "python3 -m py_compile src/app.py"})],
            [("requirement_status", {"id": "R1", "status": "done", "evidence": "src/app.py compiles"})],
            [("finish", {"summary": "Added sub.", "success": True})]]

    async def complete(self, request):
        system = request.system or ""
        if system.startswith("You are JAI's requirements analyst"):
            calls = [_call("record_requirements", {"requirements": [
                {"text": "sub(a, b) in src/app.py", "source": "mission"},
                {"text": "src/app.py compiles", "source": "mission"}]})]
        elif system.startswith("You are JAI's Verifier Agent"):
            calls = [_call("verdict", {"verified": True, "unmet": [], "checks": [
                {"requirement": "R1 sub in src/app.py", "met": True, "evidence": "read src/app.py: def sub is there"},
                {"requirement": "R2 compiles", "met": True,
                 "evidence": "ran python3 -m py_compile src/app.py: exit 0"}]})]
        else:
            turn = self.mission_turns.pop(0) if self.mission_turns else [("finish", {"summary": "x", "success": True})]
            calls = [_call(name, args, i) for i, (name, args) in enumerate(turn)]
        return CompletionResponse(id="r", model="test", content="", usage={"total_tokens": 3}, tool_calls=calls)


def _pg(db) -> bool:
    return db.get_bind().dialect.name == "postgresql"


@pytest.mark.integration
def test_a_mission_leaves_a_traceable_chain_from_requirement_to_files_and_checks(monkeypatch):
    from app.core.command import agent_executor
    from app.core.command.agent_executor import AgentExecutor
    from app.core.graph import graph_service
    from app.models.artifact_graph import ArtifactEdge, ArtifactNode
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    host, folder = _mission_folder()
    monkeypatch.setattr(agent_executor, "get_router", lambda: _Router())

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            result = await AgentExecutor(rt, "test-model", host).run("Add sub(a, b) to src/app.py.",
                                                                     max_continuations=0)
            await session.commit()
            nodes = (await session.execute(select(ArtifactNode).where(
                ArtifactNode.workspace_id == rt.workspace_id))).scalars().all()
            edges = (await session.execute(select(ArtifactEdge).where(
                ArtifactEdge.workspace_id == rt.workspace_id))).scalars().all()
            trace = await graph_service.trace(session, rt.workspace_id, "R1")
            file_trace = await graph_service.trace(session, rt.workspace_id, "src/app.py")
            elsewhere = await graph_service.trace(session, uuid4(), "R1")
            first = await graph_service.backfill(session, rt.workspace_id)
            count_after_first = (await session.execute(select(func.count(ArtifactEdge.id)).where(
                ArtifactEdge.workspace_id == rt.workspace_id))).scalar_one()
            await graph_service.backfill(session, rt.workspace_id)
            count_after_second = (await session.execute(select(func.count(ArtifactEdge.id)).where(
                ArtifactEdge.workspace_id == rt.workspace_id))).scalar_one()
            return (result, nodes, edges, trace, file_trace, elsewhere, first, count_after_first,
                    count_after_second, len(edges))

    try:
        (result, nodes, edges, trace, file_trace, elsewhere, first, after_first, after_second,
         before) = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert result["verification"]["verified"] is True
    kinds = {(n.kind, n.key) for n in nodes}
    assert ("file", "src/app.py") in kinds
    assert ("command", "python3 -m py_compile src/app.py") in kinds
    assert any(k == "requirement" and key.endswith(":R1") for k, key in kinds)
    relations = {e.relation for e in edges}
    assert {"changed_by", "run_in", "required_by", "verifies", "implements"} <= relations
    described = "\n".join(graph_service.describe(trace).splitlines())
    assert "check Independent check of R1 —verifies→ requirement R1" in described
    assert "file src/app.py —implements→ requirement R1" in described
    assert any(n["key"] == "src/app.py" for n in file_trace["nodes"])
    assert elsewhere == {"nodes": [], "edges": []}
    assert first["files"] >= 1 and first["commands"] >= 1
    assert after_first == before and after_second == after_first  # backfill adds nothing twice


@pytest.mark.integration
def test_hard_check_failures_contradict_the_decision_that_disagrees():
    from app.core.graph import graph_service
    from app.models.artifact_graph import ArtifactEdge, ArtifactNode
    from app.models.user import User
    from app.models.workspace import Workspace

    async def run():
        async with AsyncTestingSessionLocal() as db:
            uid, wid = uuid4(), uuid4()
            db.add(User(id=uid, username=f"u{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.io", password_hash="$2b$12$x",
                        is_active=True, is_admin=False))
            db.add(Workspace(id=wid, name="MYCO", slug=f"m-{wid.hex[:8]}", description="d", owner_id=uid,
                             is_active=True, workspace_type="software", authority_level=4,
                             config={"root_path": "/test_workspaces/myco"}))
            await db.commit()
            counts = await graph_service.record_verification(db, wid, None, [], [], [
                {"check": "document_claims", "file": "docs/adr/0004-python.md",
                 "detail": "says python is 3.14.7 but the files pin 3.12.8"},
                {"check": "spec_pins", "file": ".python-version", "detail": "python is 3.12.8, spec locks 3.14.7"}])
            again = await graph_service.record_verification(db, wid, None, [], [], [
                {"check": "spec_pins", "file": ".python-version", "detail": "python is 3.12.8, spec locks 3.14.7"}])
            await db.commit()
            key = await graph_service.file_key(db, wid, "/test_workspaces/myco/apps/web/package.json")
            decision = (await db.execute(select(ArtifactNode).where(
                ArtifactNode.workspace_id == wid, ArtifactNode.key == "docs/adr/0004-python.md"))).scalar_one()
            edges = (await db.execute(select(ArtifactEdge).where(ArtifactEdge.workspace_id == wid))).scalars().all()
            trace = await graph_service.trace(db, wid, "0004-python.md")
            return counts, again, key, decision, edges, trace

    counts, again, key, decision, edges, trace = asyncio.run(run())
    assert counts["contradicts"] == 2 and again["contradicts"] == 1
    assert key == "apps/web/package.json"
    assert decision.kind == "decision"
    assert len(edges) == 2 and all(e.relation == "contradicts" for e in edges)  # the repeat added no edge
    assert "contradicts" in graph_service.describe(trace) and "3.12.8" in json.dumps(trace["edges"])


def test_every_agent_and_the_verifier_can_trace():
    from app.core.agents.toolbox import TRACE_TOOL
    from app.core.command.agent_executor import VERIFIER_TOOLS
    from app.core.tools.registry import get_registry

    meta = get_registry().get_metadata(TRACE_TOOL)
    assert meta is not None and meta.is_implemented
    assert TRACE_TOOL in VERIFIER_TOOLS
