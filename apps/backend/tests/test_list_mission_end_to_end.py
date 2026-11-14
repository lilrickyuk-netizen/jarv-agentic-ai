"""
A whole list mission, end to end, the way it runs on Richard's machine (13 November: a mission failed when a binary
file was read as text and its NUL bytes reached PostgreSQL, and ChatGPT's review rightly said the workbook reader had
been tested on its own, not through a real Verifier). Real: the mission team, the routing to the Marketing Lead, the
role's toolbox and permission gate on a real folder, the spreadsheet tool, the independent Verifier's own toolbox,
the requirements ledger and the PostgreSQL test database (the session is committed at the end, as the service
does). Stood in: the models' replies, scripted.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time

import pytest

from app.core.command import agent_executor, mission_org
from app.core.command.mission_org import MissionTeam
from app.core.config import settings
from app.core.providers import CompletionResponse
from app.core.workspaces import fs_inspector
from tests.conftest import _SQLITE, AsyncTestingSessionLocal
from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

needs_postgres = pytest.mark.skipif(_SQLITE, reason="PostgreSQL is what refuses NUL bytes")
BINARY = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 4


def _calls(*pairs):
    return [{"id": f"c{i}-{time.monotonic_ns()}", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(pairs)]


class Models:
    """The requirements analyst, the Marketing Lead and the Verifier, scripted."""

    def __init__(self):
        self.lead = [
            [("read_file", {"path": "logo.png"})],
            [("write_spreadsheet", {"path": "growth/free-places.xlsx", "sheets": [
                {"name": "Creators", "rows": [["Name", "Contact", "Still to check"],
                                              ["Ruby Granger", "hello@rubygranger.com", "audience size"]]}]})],
            [("requirement_status", {"id": "R1", "status": "done", "evidence": "wrote growth/free-places.xlsx"})],
            [("finish", {"summary": "growth/free-places.xlsx lists the creators.", "success": True})]]
        self.checker = [[("read_file", {"path": "growth/free-places.xlsx"}), ("read_file", {"path": "logo.png"})]]
        self.lead_tools, self.seen_by_checker = [], ""

    async def complete(self, request):
        system = request.system or ""
        if system.startswith("You are JAI's requirements analyst"):
            calls = [("record_requirements", {"requirements": [
                {"text": "growth/free-places.xlsx lists creators with a published contact", "source": "mission"}]})]
        elif system.startswith("You are JAI's Marketing"):
            self.lead_tools = self.lead_tools or sorted(t["name"] for t in request.tools or [])
            calls = self.lead.pop(0) if self.lead else [("finish", {"summary": "done", "success": True})]
        elif system.startswith("You are JAI's Verifier Agent"):
            self.seen_by_checker += " ".join(m.content if isinstance(m.content, str) else json.dumps(m.content)
                                             for m in request.messages)
            calls = self.checker.pop(0) if self.checker else [("verdict", {"verified": True, "unmet": [], "checks": [
                {"requirement": "R1", "met": True, "evidence": "read growth/free-places.xlsx: Ruby Granger"}]})]
        else:
            calls = []
        return CompletionResponse(id="r", model="test", content="", usage={"total_tokens": 5},
                                  tool_calls=_calls(*calls))


@pytest.mark.integration
@needs_postgres
def test_a_list_mission_runs_on_its_role_agent_and_the_checker_reads_the_workbook(monkeypatch):
    models = Models()
    monkeypatch.setattr(settings, "MISSION_TEAM_ENABLED", True)
    monkeypatch.setattr(agent_executor, "get_router", lambda: models)
    monkeypatch.setattr(mission_org, "get_router", lambda: models)
    host, folder = _mission_folder()
    (folder / "logo.png").write_bytes(BINARY)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            team = MissionTeam(rt, "test-model", host, session_factory=AsyncTestingSessionLocal)
            result = await team.run("Find free places to market Plexecute", max_continuations=1)
            await session.commit()  # a NUL anywhere in the mission's records would fail here
            return result

    try:
        result = asyncio.run(run())
        saved = (folder / "growth" / "free-places.xlsx").exists()
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    assert saved and result["role"]["specialist"] == "marketing"
    assert "write_spreadsheet" in models.lead_tools and "run_command" not in models.lead_tools
    assert "Ruby Granger" in models.seen_by_checker          # the Verifier read the workbook's rows
    assert "is a binary file" in models.seen_by_checker      # and a binary file came back as a note, not bytes
    assert "\x00" not in models.seen_by_checker
    assert result["verification"]["verified"] is True and result["success"] is True


def test_a_binary_file_is_never_read_as_text(tmp_path, monkeypatch):
    image = tmp_path / "logo.png"
    image.write_bytes(BINARY)
    monkeypatch.setattr(fs_inspector, "path_exists", lambda host: fs_inspector.FsResult(
        accessible=True, host_path=host, container_path=str(image), exists=True, is_dir=False))
    read = fs_inspector.read_file("C:\\P\\logo.png")
    assert read.data["binary"] is True and "\x00" not in read.data["content"]
    assert "Use read_document" in read.data["content"]
    assert fs_inspector.no_nul({"a": ["x\x00y", {"b": "\x00"}], "n": 3}) == {"a": ["xy", {"b": ""}], "n": 3}
