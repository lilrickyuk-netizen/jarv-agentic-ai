"""
Upgrade 4: the Synthesizer. A mission's report is built from numbered evidence; a claim citing a failed command
or nothing at all is not shown as done; hard-check failures always appear; a stored report renders the same text
again without a model call.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil

import pytest

from app.core.synthesis.report import build_ledger, check, render

CALLS = [
    {"tool": "write_file", "inputs": {"path": "src/app.py"}, "success": True, "summary": "wrote 80 bytes (updated)"},
    {"tool": "run_command", "inputs": {"command": "pytest -q"}, "success": False, "summary": "exit=1",
     "output": {"exit_code": 1}},
    {"tool": "run_command", "inputs": {"command": "python3 -m py_compile src/app.py"}, "success": True,
     "summary": "exit=0", "output": {"exit_code": 0}},
    {"tool": "run_command", "inputs": {"command": "git push"}, "success": False,
     "summary": "paused for approval: git push needs Richard", "output": {}},
]
CHECK_CALLS = [{"tool": "read_file", "inputs": {"path": "src/app.py"}, "success": True, "summary": "read 80 bytes"}]
REQS = [
    {"id": "R1", "text": "sub(a, b) in src/app.py", "source": "mission", "status": "done", "evidence": "edited src/app.py"},
    {"id": "R2", "text": "the tests pass", "source": "mission", "status": "done", "evidence": "pytest -q"},
    {"id": "R3", "text": "README mentions sub", "source": "mission", "status": "open", "evidence": ""},
    {"id": "R4", "text": "pushed to GitHub", "source": "mission", "status": "waiting", "evidence": ""},
]


def _ledger():
    return build_ledger(CALLS, CHECK_CALLS)


def test_the_ledger_numbers_the_mission_and_the_check():
    ledger = _ledger()
    assert [e["id"] for e in ledger] == ["E1", "E2", "E3", "E4", "E5"]
    assert ledger[1] == {"id": "E2", "by": "mission", "tool": "run_command", "target": "pytest -q", "success": False,
                         "exit_code": 1, "summary": "exit=1"}
    assert ledger[4]["by"] == "check" and ledger[4]["target"] == "src/app.py"


def test_claims_need_evidence_that_succeeded():
    draft = {"overall": "All requirements are complete.", "items": [
        {"requirement": "R1", "status": "done", "statement": "sub added", "evidence": ["E1", "E5", "E99"]},
        {"requirement": "R2", "status": "done", "statement": "tests pass", "evidence": ["E2"]},
        {"requirement": "R3", "status": "done", "statement": "README updated", "evidence": []},
        {"requirement": "R4", "status": "done", "statement": "pushed", "evidence": ["E4"]},
    ]}
    report = check(draft, REQS, _ledger(), {"verified": False, "unmet": []}, None)
    items = {i["id"]: i for i in report["items"]}
    assert items["R1"]["status"] == "done" and items["R1"]["evidence"] == ["E1", "E5"]  # E99 does not exist
    assert items["R2"]["status"] == "not shown" and "exit 1" in items["R2"]["note"]  # a failing command proves nothing
    assert items["R3"]["status"] == "not shown" and items["R3"]["statement"] == ""  # no citation: removed
    assert items["R4"]["status"] == "waiting"  # a paused push is not done
    assert report["overall"] == "1 of 4 requirements shown done with evidence."  # "All ... complete" was untrue
    assert report["waiting"] and "git push" in report["waiting"][0]


def test_hard_check_failures_and_unmet_findings_win_over_the_draft():
    draft = {"overall": "Phase 0 conforms.", "items": [
        {"requirement": "R1", "status": "done", "statement": "done", "evidence": ["E3"]}]}
    hard = {"findings": [{"check": "spec_pins", "file": ".python-version",
                          "detail": "python is '3.12.8' but MYCO_V3_SPEC.md locks 3.14.7"}]}
    report = check(draft, REQS[:1], _ledger(), {"unmet": ["R1 (sub): the independent check gave no evidence"]}, hard)
    assert report["items"][0]["status"] == "open"
    text = render(report)
    assert "Hard checks still failing" in text and ".python-version" in text and "3.14.7" in text


def test_a_report_without_a_draft_is_built_from_the_evidence():
    verification = {"checks": [{"requirement": "R1 sub", "met": True, "evidence": "read src/app.py"}], "unmet": []}
    report = check({}, REQS[:3], _ledger(), verification, None)
    items = {i["id"]: i for i in report["items"]}
    assert items["R1"]["status"] == "done" and "E1" in items["R1"]["evidence"]
    assert items["R2"]["status"] == "not shown"  # its only evidence, pytest -q, failed
    assert items["R3"]["status"] == "not shown"


def test_a_stored_report_renders_the_same_text_again():
    draft = {"overall": "Sub is in.", "items": [
        {"requirement": "R1", "status": "done", "statement": "sub(a, b) added", "evidence": ["E1", "E3"]}]}
    report = check(draft, REQS[:1], _ledger(), {"unmet": []}, None)
    stored = json.loads(json.dumps(report))
    assert render(stored) == render(report)
    text = render(report)
    assert "| R1 sub(a, b) in src/app.py | done | sub(a, b) added | E1, E3 |" in text
    assert "- E3 (mission): run_command python3 -m py_compile src/app.py → exit 0" in text


@pytest.mark.integration
def test_the_mission_answer_is_the_cited_report(monkeypatch):
    from app.core.command import agent_executor
    from app.core.command.agent_executor import AgentExecutor
    from app.core.providers import CompletionResponse
    from tests.conftest import AsyncTestingSessionLocal
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    def call(name, args, i=0):
        return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}

    class Router:
        def __init__(self):
            self.turns = [[("run_command", {"command": "python3 -m py_compile src/app.py"})],
                          [("finish", {"summary": "Everything is done and pushed.", "success": True})]]

        async def complete(self, request):
            system = request.system or ""
            if system.startswith("You are JARV's requirements analyst"):
                calls = [call("record_requirements", {"requirements": [
                    {"text": "src/app.py compiles", "source": "mission"},
                    {"text": "pushed to GitHub", "source": "mission"}]})]
            elif system.startswith("You are JARV's Verifier Agent"):
                calls = [call("verdict", {"verified": True, "unmet": [], "checks": [
                    {"requirement": "R1", "met": True, "evidence": "python3 -m py_compile src/app.py exit 0"},
                    {"requirement": "R2", "met": True, "evidence": "git log shows it"}]})]
            elif system.startswith("You are JARV's report writer"):
                found = re.search(r"(E\d+) \(mission\): run_command python3 -m py_compile", request.messages[0].content)
                self.cited = found.group(1)
                calls = [call("write_report", {"overall": "All done.", "items": [
                    {"requirement": "R1", "status": "done", "statement": "It compiles.", "evidence": [self.cited]},
                    {"requirement": "R2", "status": "done", "statement": "Pushed.", "evidence": []}]})]
            else:
                turn = self.turns.pop(0) if self.turns else [("finish", {"summary": "x", "success": True})]
                calls = [call(n, a, i) for i, (n, a) in enumerate(turn)]
            return CompletionResponse(id="r", model="t", content="", usage={"total_tokens": 2}, tool_calls=calls)

    host, folder = _mission_folder()
    router = Router()
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            return await AgentExecutor(rt, "test-model", host).run("Make src/app.py compile and push it.",
                                                                   max_continuations=0)

    try:
        result = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert result["agent_summary"] == "Everything is done and pushed."
    assert "Everything is done and pushed" not in result["answer"]  # an uncited claim never reaches Richard
    assert f"| R1 src/app.py compiles | done | It compiles. | {router.cited} |" in result["answer"]
    assert "| R2 pushed to GitHub | not shown |" in result["answer"]
    assert result["report"]["overall"] == "1 of 2 requirements shown done with evidence."
    assert render(result["report"]) == result["answer"]
