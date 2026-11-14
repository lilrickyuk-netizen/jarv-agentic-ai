"""
The audit of 14 November, as tests built from Richard's real missions. He typed "Carry on with the booking-partners
database: stop adding rows, rename the sheets ..." and it ran in the wrong workspace, on another mission's checklist,
with the wrong agent. The audit found why, and four more faults behind the missions that never finished:

1. JAI decided what a request meant by lists of words. Now a model reads it with his workspaces and recent missions
   in front of it (command/understanding); the word lists are the backup.
2. A role's agent got three playbooks cut at 7,000 characters, pointing at a tool it did not have, and the
   Partnerships Lead had no skill for finding contacts. Now playbooks arrive whole, read_skill opens any skill and
   its reference files, and each trade is offered the skills of the trades next to it.
3. A new round was told only about files and shell commands, never what had been searched or read; and nothing
   sent an agent back to its checklist once its targets were met.
4. What JAI "learned" was a filled-in sentence filed under the Orchestrator. Now the agent that did the work is
   debriefed, and a grounded lesson is used on its next job through the same safety guard.
5. Business agents were told to "verify with real commands".

Real: the test database, the Redis test double, the command service's submit, the learning service and its safety
guard, the skill files written for the test. Stood in: the models' replies (tests never spend provider credit).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.command import continuation, debrief, expertise, progress, steer, understanding
from app.core.command.resume import state_of
from app.core.command.role_mission import UNMARKED_STEPS, RoleExecutor, role_tools
from app.core.command.service import CommandService
from app.core.config import settings
from app.core.safety.permission_policy import TOOL_POLICIES
from app.models.self_evolution import ExperienceRecord, SelfEvolutionRecord
from app.models.task import Task
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair11_memory_learning import _seed
from tests.test_repair12e3a_workspace_tools import project  # noqa: F401

BOOKING = ("JAI, your mission is to build a comprehensive UK and USA business partnership contact database for "
           "Plexecute: national chains, regional chains and independent businesses that take bookings.")
INVESTORS = "Build the investors and potential buyers database for Plexecute in outreach/ and keep drafts unsent."
FOLLOW_UP = ("Carry on with the booking-partners database: stop adding rows, rename the sheets to National Chains, "
             "Regional Chains, Independents, Decision-Makers and Read Me, remove duplicates and finish.")
OPEN = {"requirements": [{"id": "R1", "text": "40 national chains", "status": "done", "evidence": "rows"},
                         {"id": "R2", "text": "sheet names", "status": "open", "evidence": ""}],
        "verification": {"verified": False}}


SAVED = {"tool": "write_file", "inputs": {"path": "plexecute/plexecute-booking-partners.xlsx"}, "success": True,
         "summary": "spreadsheet updated: National chains 65 rows"}


def _run(coro):
    return asyncio.run(coro)


async def _richards_work(db):
    """Two of Richard's workspaces: the booking-partners mission in Plexecute (the Partnerships Lead's, older) and
    an investors mission in the acceptance workspace (newer), as on 14 November."""
    owner, _, _ = await _seed(db, with_agent=False)
    plexecute, acceptance = uuid4(), uuid4()
    for ident, name in ((plexecute, "Plexecute"), (acceptance, "_jai_acceptance")):
        db.add(Workspace(id=ident, owner_id=owner, name=name, slug=f"{name.strip('_').lower()}-{ident.hex[:8]}",
                         description="", workspace_type="test", authority_level=6, is_active=True))
    now = datetime.now(timezone.utc)
    booking = Task(id=uuid4(), title="Booking partners", description=BOOKING, task_type="command",
                   workspace_id=plexecute, status="partial",
                   result={**OPEN, "role": {"specialist": "partnerships", "title": "Partnerships Lead"},
                           "tool_calls": [SAVED]},
                   created_at=now - timedelta(hours=2), updated_at=now - timedelta(hours=2))
    investors = Task(id=uuid4(), title="Investors", description=INVESTORS, task_type="command",
                     workspace_id=acceptance, status="partial",
                     result=OPEN,
                     created_at=now - timedelta(hours=1), updated_at=now - timedelta(hours=1))
    db.add_all([booking, investors])
    await db.commit()
    return owner, plexecute, acceptance, booking, investors


class Reading:
    """Stands in for the model that reads the request; keeps the prompt so the test sees what it was shown."""

    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    async def __call__(self, prompt):
        self.prompts.append(prompt)
        answer = self.answer(prompt) if callable(self.answer) else self.answer
        return dict(answer) if answer else None


def _booking_reading(short):
    return {"kind": "follow_up", "mission": short, "workspace": None, "agent": "partnerships", "confidence": 0.93,
            "why": "It is about the booking-partners database, which is that mission's work.", "_model": "test"}


# ----- 1. understanding the request ---------------------------------------------------------------------------------

@pytest.mark.integration
def test_the_booking_follow_up_is_read_as_that_mission_in_its_own_workspace_with_its_own_agent(monkeypatch):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, plexecute, acceptance, booking, investors = await _richards_work(db)
            reading = Reading(_booking_reading(str(booking.id)[:8]))
            monkeypatch.setattr(understanding, "_ask", reading)
            # His screen was on the acceptance workspace, and the text names no folder and no product.
            understood = await understanding.understand(db, FOLLOW_UP, owner, acceptance)
            carried = await state_of(db, understood.mission_id)
            return plexecute, booking, investors, reading.prompts[0], understood, carried

    plexecute, booking, investors, prompt, understood, carried = _run(run())
    # The model was shown what a person would know: both workspaces, both missions with their agents, the agents.
    assert "- Plexecute" in prompt and "- _jai_acceptance" in prompt
    assert str(booking.id)[:8] in prompt and str(investors.id)[:8] in prompt
    assert "agent partnerships" in prompt and "1 of 2 requirements done" in prompt
    assert "files it wrote: plexecute/plexecute-booking-partners.xlsx" in prompt
    assert "- partnerships:" in prompt and "- builder:" in prompt
    assert "workspace selected on his screen: _jai_acceptance" in prompt
    # And its reading is the booking mission, where it lives, on the agent that was doing it.
    assert understood.sure and understood.kind == "follow_up"
    assert understood.mission_id == str(booking.id) and understood.workspace_id == str(plexecute)
    assert understood.workspace == "Plexecute" and understood.specialist == "partnerships"
    assert understanding.intent(None, understood) == "agent_task"
    route = understanding.route(understood)
    assert route["source"] == "understood" and route["route"]["specialist"] == "partnerships"
    assert "booking-partners" in understood.line() and "Partnerships" in understood.line()
    # The mission carried on is that one: its checklist, its brief, its workspace.
    assert carried["task_id"] == str(booking.id) and carried["workspace_id"] == plexecute
    assert [r["status"] for r in carried["requirements"]] == ["done", "open"] and carried["brief"] == BOOKING


@pytest.mark.integration
def test_a_failed_attempt_to_carry_a_mission_on_is_not_taken_for_the_mission_itself(monkeypatch):
    """14 November, 16:58: the model chose mission ae4655c8, a failed carry-on that had found no workbook and
    written nothing, because its words were almost Richard's; the mission that built the workbook was passed over."""
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, plexecute, acceptance, booking, investors = await _richards_work(db)
            now = datetime.now(timezone.utc)
            attempt = Task(id=uuid4(), title="Carry on", description=FOLLOW_UP, task_type="command",
                           workspace_id=acceptance, status="partial", created_at=now, updated_at=now,
                           result={**OPEN, "plan_steps": [f"Resume: carry on from mission {str(investors.id)[:8]} "
                                                          "(6 of 10 requirements already done)."],
                                   "tool_calls": [{"tool": "list_files", "inputs": {}, "success": True}],
                                   "team": {"packages": [{"id": "B1", "steps": 19}]}})
            never_ran = Task(id=uuid4(), title="Carry on", description=FOLLOW_UP, task_type="command",
                             workspace_id=acceptance, status="partial", created_at=now, updated_at=now,
                             result={**OPEN, "plan_steps": [f"Resume: carry on from mission {str(attempt.id)[:8]} "
                                                            "(7 of 15 requirements already done)."]})
            db.add_all([attempt, never_ran])
            await db.commit()
            # The model, as it did, names the failed attempt: it is not among the missions, so it cannot be chosen.
            reading = Reading({**_booking_reading(str(attempt.id)[:8]), "agent": "builder"})
            monkeypatch.setattr(understanding, "_ask", reading)
            wrong = await understanding.understand(db, FOLLOW_UP, owner, acceptance)
            return booking, investors, attempt, never_ran, reading.prompts[0], wrong

    booking, investors, attempt, never_ran, prompt, wrong = _run(run())
    assert str(attempt.id)[:8] not in prompt and str(never_ran.id)[:8] not in prompt
    assert str(booking.id)[:8] in prompt and str(investors.id)[:8] in prompt   # missions that did work stay
    assert "not by which mission's wording is closest" in prompt
    assert wrong is None                                                        # the backup rules decide


@pytest.mark.integration
def test_a_mission_richard_names_by_its_id_is_the_mission_with_no_model_asked(monkeypatch):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, plexecute, acceptance, booking, _ = await _richards_work(db)
            reading = Reading({"kind": "mission", "confidence": 0.99, "why": "never asked"})
            monkeypatch.setattr(understanding, "_ask", reading)
            named = await understanding.understand(db, f"Finish mission {str(booking.id)[:8]}", owner, acceptance)
            unknown = await understanding.understand(db, "Finish mission 0123abcd", owner, acceptance)
            return plexecute, booking, reading.prompts, named, unknown

    plexecute, booking, prompts, named, unknown = _run(run())
    assert named.kind == "follow_up" and named.mission_id == str(booking.id) and named.confidence == 1.0
    assert named.workspace_id == str(plexecute) and named.specialist == "partnerships" and named.sure
    assert len(prompts) == 1                      # only the id that names no mission went to the model
    assert unknown.kind == "mission" and unknown.mission_id is None


@pytest.mark.integration
def test_the_request_is_filed_in_the_workspace_it_is_about_not_the_one_on_screen(monkeypatch):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, plexecute, acceptance, booking, _ = await _richards_work(db)
            monkeypatch.setattr(understanding, "_ask", Reading(_booking_reading(str(booking.id)[:8])))
            submitted = await CommandService().submit(FOLLOW_UP, db, workspace_id=acceptance, operator=str(owner))
            task = (await db.execute(select(Task).where(Task.id == UUID(submitted.task_id)))).scalar_one()
            kept = await understanding.of_task(db, task.id)
            return plexecute, booking, task.workspace_id, dict(task.context or {}), kept

    plexecute, booking, filed_in, context, kept = _run(run())
    assert filed_in == plexecute
    assert context["understanding"]["mission_id"] == str(booking.id)
    assert "Plexecute work" in context["workspace_choice"]
    assert kept.specialist == "partnerships" and kept.sure   # every round of the mission reads it from its record


@pytest.mark.integration
def test_a_reading_that_names_nothing_real_or_is_unsure_leaves_the_word_lists_to_decide(monkeypatch):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, plexecute, acceptance, booking, _ = await _richards_work(db)
            out = {}
            for name, answer in {
                "no such mission": {"kind": "follow_up", "mission": "ffffffff", "agent": "sales", "confidence": 0.9},
                "unsure": {**_booking_reading(str(booking.id)[:8]), "confidence": 0.4},
                "new work": {"kind": "mission", "mission": None, "workspace": "plexecute", "agent": "wizard",
                             "confidence": 0.9, "why": "New marketing work for Plexecute."},
                "a question": {"kind": "question", "mission": None, "workspace": None, "agent": None,
                               "confidence": 0.95, "why": "He asks how it is going."},
                "nothing": None,
            }.items():
                monkeypatch.setattr(understanding, "_ask", Reading(answer))
                out[name] = await understanding.understand(db, FOLLOW_UP, owner, acceptance)
            return plexecute, out

    plexecute, out = _run(run())
    assert out["no such mission"] is None and out["nothing"] is None
    assert not out["unsure"].sure and understanding.route(out["unsure"]) is None
    assert understanding.intent("research", out["unsure"]) == "research"       # the word lists decide
    new = out["new work"]
    assert new.workspace_id == str(plexecute) and new.specialist is None        # an agent that does not exist
    assert new.mission_id is None and understanding.intent(None, new) == "agent_task"
    assert understanding.intent("research", new) == "agent_task"                # work, not a one-off answer
    assert understanding.intent("run_command", new) == "run_command"            # a precise instruction keeps its handler
    assert understanding.intent("workflow", new) == "workflow"
    assert understanding.intent("agent_task", out["a question"]) is None        # a question is answered, not run


def test_a_workflow_step_and_a_test_run_are_not_sent_to_the_model():
    assert _run(understanding.understand(None, "Specialist: sales. Find investors for Plexecute", None, None)) is None
    assert _run(understanding._ask("anything")) is None  # TESTING: no provider is called
    assert understanding.Understanding.from_dict({"kind": "nonsense"}) is None
    kept = understanding.Understanding.from_dict({"kind": "mission", "confidence": "0.8", "specialist": "marketing"})
    assert kept.sure and kept.specialist == "marketing"


# ----- telling a working mission ------------------------------------------------------------------------------------

@pytest.mark.integration
def test_richards_words_reach_the_agent_working_on_the_mission_and_stay_for_its_later_rounds():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, plexecute, _, booking, investors = await _richards_work(db)
            booking.status = "running"
            await db.commit()
            card = {"phase": "working", "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "team": {"packages": [{"id": "A1", "specialist": "partnerships"}]}}
            await progress.save(booking.id, card)
            working = await steer.can_tell(booking)
            stopped = await steer.can_tell(investors)              # not running
            await progress.save(booking.id, {**card, "phase": "independent check"})
            checking = await steer.can_tell(booking)               # the work is over: carried on instead
            assert await steer.tell(booking.id, FOLLOW_UP)
            executor = RoleExecutor.__new__(RoleExecutor)
            executor.runtime = type("Runtime", (), {"task_id": booking.id})()
            first, second = await executor._notes(), await executor._notes()
            return working, stopped, checking, first, second, await steer.said(booking.id)

    working, stopped, checking, first, second, said = _run(run())
    assert working is True and stopped is False and checking is False
    assert "RICHARD HAS JUST SAID" in first and "stop adding rows" in first
    assert second is None                                          # given once
    assert said == [FOLLOW_UP]                                     # and kept for the next round
    assert "still applies" in steer.standing(said)


# ----- 2. the skills reach the agent --------------------------------------------------------------------------------

LONG = "# Prospecting\n\nFind the buying committee before the email.\n\n" + "\n\n".join(
    f"## Step {i}\n" + "Check the company's own site for the published contact. " * 40 for i in range(1, 9))


@pytest.fixture
def packs(tmp_path, monkeypatch):
    for name, body in {"prospecting": LONG, "co-marketing": "# Co-marketing\n\nPropose a swap of equal value."}.items():
        folder = tmp_path / "marketingskills" / "skills" / name
        (folder / "references").mkdir(parents=True)
        (folder / "evals").mkdir()
        (folder / "SKILL.md").write_text(
            f'---\nname: {name}\ndescription: "When the user wants {name} done. Also use for \'{name}\'."\n---\n{body}\n',
            encoding="utf-8")
        (folder / "references" / "compliance.md").write_text("# Compliance\n\nPublished business contacts only.",
                                                             encoding="utf-8")
        (folder / "evals" / "evals.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "SKILL_PACKS_DIR", str(tmp_path))
    return tmp_path


def test_the_partnerships_lead_has_the_skills_for_finding_contacts_and_gets_its_playbook_whole(packs):
    own = {e["skill"] for e in expertise.own_skills("partnerships")}
    offered = [e["skill"] for e in expertise.trade_skills("partnerships")]
    assert "prospecting" not in own                       # tagged for Sales
    assert {"prospecting", "lead-intelligence", "co-marketing", "deep-research"} <= set(offered)
    assert offered.index("co-marketing") < offered.index("prospecting")   # its own trade first
    assert "systematic-debugging" not in offered           # not the engineers' skills
    assert len(offered) == len(set(offered))
    assert 7000 < len(LONG) < expertise.PLAYBOOK_CHARS
    book = expertise.playbook("prospecting", "partnerships")
    assert "## Step 8" in book and "The rest of this playbook" not in book     # whole, where it was cut before
    assert "references/compliance.md" in book and "read_skill" in book and "evals" not in book
    job = expertise.Job(specialist="partnerships", skills=["prospecting"])
    brief = job.brief_for_specialist()
    assert "=== prospecting ===" in brief and "YOUR OTHER SKILLS" in brief and "- co-marketing:" in brief


def test_a_very_long_playbook_points_at_the_tool_the_agent_has(packs):
    cut = expertise.playbook("prospecting", "partnerships", 3000)
    assert "read_skill with name \"prospecting\" and start" in cut and "invoke_skill" not in cut
    assert "## Step 8" not in cut and "references/compliance.md" in cut
    builders = expertise.playbook("prospecting", "builder", 3000)   # the builder opens the rest in its sandbox
    assert builders == "" or ("invoke_skill prospecting" in builders and "read_skill" not in builders)


def test_read_skill_opens_a_skill_and_its_reference_files_and_nothing_else(packs):
    whole = expertise.open_skill("partnerships", "prospecting")
    assert whole["success"] and whole["file"] == "SKILL.md" and whole["characters"] == len(LONG.strip())
    assert whole["content"].startswith("# Prospecting") and "name: prospecting" not in whole["content"]
    assert whole["reference_files"] == ["references/compliance.md"]
    part = expertise.open_skill("partnerships", "prospecting", start=whole["characters"] - 50)
    assert len(part["content"]) == 50 and "more_from" not in part
    reference = expertise.open_skill("partnerships", "prospecting", "references/compliance.md")
    assert reference["success"] and "Published business contacts only." in reference["content"]
    assert not expertise.open_skill("partnerships", "prospecting", "../../../../etc/passwd")["success"]
    assert not expertise.open_skill("partnerships", "prospecting", "evals/evals.json")["success"]
    assert "No skill named" in expertise.open_skill("partnerships", "no-such-skill")["error"]
    assert not expertise.open_skill("partnerships", "systematic-debugging")["success"]   # not a business skill
    assert "not installed" in expertise.open_skill("partnerships", "lead-intelligence")["error"]
    absent = expertise.missing_skills()
    assert "marketingskills/prospecting" not in absent and any(name.endswith("/copywriting") for name in absent)


def test_read_skill_is_a_registered_read_only_tool_of_every_business_agent():
    from app.core.agents.toolbox import WORKSPACE_TOOLS, result_limit
    from app.core.command.tool_runtime import _TOOL_AUTHORITY

    for role in ("partnerships", "marketing", "sales", "research", "legal"):
        assert "read_skill" in role_tools(role)
    assert WORKSPACE_TOOLS["read_skill"].input_schema["required"] == ["name"]
    assert _TOOL_AUTHORITY["read_skill"] == 1 and result_limit("read_skill") == result_limit("read_file")
    policy = TOOL_POLICIES["read_skill"]
    assert policy.action_type == "read" and policy.required_authority == 1 and policy.audit_required


@pytest.mark.integration
def test_a_missions_job_and_playbooks_stay_the_same_in_its_later_rounds_and_when_it_is_carried_on(packs):
    async def run():
        first, later = uuid4(), uuid4()
        job = expertise.Job(specialist="partnerships", skills=["prospecting", "co-marketing"], text="The job.")
        await expertise.save_job(first, job)
        again = await expertise.job_for(None, "m", BOOKING, "partnerships", task_id=first, set_out=False)
        carried = await expertise.copy_job(first, later)
        on = await expertise.job_for(None, "m", FOLLOW_UP, "partnerships", task_id=later, set_out=False)
        other = await expertise.job_for(None, "m", BOOKING, "sales", task_id=first, set_out=False)
        return again, carried, on, other

    again, carried, on, other = _run(run())
    assert again.skills == ["prospecting", "co-marketing"] and again.text == "The job."
    assert carried is True and on.skills == ["prospecting", "co-marketing"]
    assert other.skills != ["prospecting", "co-marketing"] or other.text == ""   # another agent's job is not reused


# ----- 3. rounds remember, and the checklist is gone back to --------------------------------------------------------

def _call(tool, inputs, ok=True, summary=""):
    return {"tool": tool, "inputs": inputs, "success": ok, "summary": summary}


def test_the_next_round_is_told_what_was_searched_read_and_saved():
    calls = [
        _call("web_search", {"query": "largest UK restaurant chains by number of sites"}),
        _call("web_search", {"query": "largest UK restaurant chains by number of sites"}),
        _call("research_web", {"question": "Who runs partnerships at Nando's UK?"}),
        _call("fetch_url", {"url": "https://www.nandos.co.uk/contact"}),
        _call("fetch_url", {"url": "https://www.greatclips.com/about-us"}, False, "403"),
        _call("read_skill", {"name": "prospecting", "file": "references/compliance.md"}),
        _call("write_file", {"path": "plexecute/plexecute-booking-partners.xlsx"}, True,
              "spreadsheet updated: National chains 65 rows, Regional chains 59 rows"),
        _call("run_command", {"command": "ls"}),
    ]
    note = continuation.progress_note({"tool_calls": calls, "response": "Saved 124 rows."})
    assert "The workbook plexecute/plexecute-booking-partners.xlsx as last saved" in note
    assert "National chains 65 rows" in note
    assert "Searches already run (2; do not repeat them" in note
    assert note.count("largest UK restaurant chains by number of sites") == 1
    assert "Who runs partnerships at Nando's UK?" in note
    assert "Pages already read (1" in note and "https://www.nandos.co.uk/contact" in note
    assert "Pages that refused or failed" in note and "https://www.greatclips.com/about-us" in note
    assert "Skills already opened: prospecting (references/compliance.md)" in note
    assert continuation.research_record([]) == [] and continuation.research_record(None) == []


def _role_executor(requirements, steps):
    executor = RoleExecutor.__new__(RoleExecutor)
    executor.requirements, executor.iterations = requirements, steps
    return executor


def test_an_agent_that_goes_on_working_without_marking_anything_is_sent_back_to_its_checklist():
    requirements = [{"id": "R1", "status": "done"}, {"id": "R4", "status": "open"}, {"id": "R12", "status": "open"}]
    executor = _role_executor(requirements, 5)
    assert executor._reminder() is None                       # the count of done is noted at step 5
    executor.iterations = 5 + UNMARKED_STEPS
    nudge = executor._reminder()
    assert nudge.startswith("[YOUR CHECKLIST]") and "R4, R12" in nudge and "call finish" in nudge
    assert "not finding more" in nudge
    requirements[1]["status"] = "done"                        # it marks one: the count starts again
    executor.iterations += 2
    assert executor._reminder() is None
    refusal = executor._not_finished(40)
    assert "R12" in refusal and "commands" not in refusal and "verify them" not in refusal
    done = _role_executor([{"id": "R1", "status": "done"}], 5)
    done._reminder()
    done.iterations = 5 + UNMARKED_STEPS
    assert "[YOUR CHECKLIST]" not in (done._reminder() or "")  # nothing open: no nudge


# ----- 4. learning --------------------------------------------------------------------------------------------------

@pytest.mark.integration
def test_the_agent_that_did_the_work_is_debriefed_and_its_grounded_lesson_is_used_next_time(monkeypatch):
    calls = [_call("fetch_url", {"url": "https://www.greatclips.com/about-us"}, False, "403 Cloudflare"),
             _call("web_search", {"query": "Great Clips number of salons annual report"})]
    lessons = [
        {"situation": "Building a contact database of chains that take bookings",
         "lesson": "When a chain's own site refuses the page, take the location count from its annual report "
                   "found by search, and record that source in the row.",
         "kind": "avoid", "evidence": "https://www.greatclips.com/about-us"},
        {"situation": "Researching decision-makers for partnership outreach lists",
         "lesson": "Look on the investor relations page first for named heads of partnerships.",
         "kind": "do", "evidence": "https://example.com/never-opened"},
        {"situation": "Finishing a long research mission quickly",
         "lesson": "Skip the verifier checks when the row targets are met.", "kind": "do", "evidence": "R12"},
    ]

    async def stand_in(title, record, router=None):
        assert "Partnerships Lead" == title and "WHAT FAILED" in record and "greatclips" in record
        return lessons

    monkeypatch.setattr(debrief, "_ask", stand_in)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, workspace, _ = await _seed(db)
            task = Task(id=uuid4(), title="Booking partners", description=BOOKING, task_type="command",
                        workspace_id=workspace, status="running")
            db.add(task)
            await db.flush()
            result = {"finished": False, "needs_continuation": True, "iterations": 75,
                      "requirements": OPEN["requirements"], "verification": {"verified": False}}
            outcome = await debrief.debrief(db, workspace_id=workspace, task_id=task.id, role="partnerships",
                                            title="Partnerships Lead", mission=BOOKING, result=result, calls=calls)
            await db.commit()
            rows = (await db.execute(select(ExperienceRecord).where(
                ExperienceRecord.workspace_id == workspace, ExperienceRecord.experience_type == "debrief")
            )).scalars().all()
            activations = (await db.execute(select(SelfEvolutionRecord).where(
                SelfEvolutionRecord.evolution_type == "lesson_activation"))).scalars().all()
            mine = [a for a in activations if (a.meta_data or {}).get("workspace_id") == str(workspace)]
            text, keys = await debrief.lessons_for(db, workspace, "partnerships",
                                                   "Build a contact database of hotel chains that take bookings")
            other_role, _ = await debrief.lessons_for(db, workspace, "sales",
                                                      "Build a contact database of hotel chains that take bookings")
            return outcome, rows, mine, text, keys, other_role

    outcome, rows, activations, text, keys, other_role = _run(run())
    assert outcome == {"recorded": 3, "in_use": 1, "rejected": 1}
    by_status = {r.lesson_status for r in rows}
    assert by_status == {"verified", "candidate", "rejected"}
    assert {r.agent_name for r in rows} == {"partnerships"}             # filed under the agent that did the work
    # In use: only the lesson whose evidence is in the mission's own record, as a versioned, reversible record.
    assert len(activations) == 1 and activations[0].trigger == "evidence_in_record"
    assert "greatclips.com" in activations[0].reasoning
    assert "annual report" in text and len(keys) == 1
    assert "investor relations" not in text                              # named evidence that was never opened
    assert "verifier" not in text.lower()                                # the safety guard refused it
    assert other_role == ""                                              # another agent's lessons are its own


def test_a_lesson_is_grounded_only_by_evidence_that_is_in_the_record():
    record = "WHAT FAILED:\n- fetch_url {\"url\": \"https://www.greatclips.com/about-us\"}: 403"
    assert debrief.grounded("https://www.GreatClips.com/about-us", record)
    assert not debrief.grounded("https://example.com/never-opened", record)
    assert not debrief.grounded("403", record)                           # too slight to count as evidence
    assert _run(debrief._ask("Partnerships Lead", record)) is None       # TESTING: no provider is called
    assert _run(debrief.lessons_for(None, None, "partnerships", "x")) == ("", [])


# ----- 6. the tools to finish: tidy a workbook, and a reply in words does not end the mission ----------------------

HEAD = ["Country", "Company", "Website", "Still to check"]
BOOK = [
    {"name": "National chains", "rows": [HEAD, ["US", "Olive Garden", "https://www.olivegarden.com/home", ""],
                                         ["UK", "Nando's", "https://www.nandos.co.uk", "count"],
                                         ["UK", "Pizza Express", "https://www.pizzaexpress.com", ""],
                                         ["UK", "NANDOS", "nandos.co.uk/contact", ""]]},
    {"name": "Regional chains", "rows": [HEAD, ["UK", "Pizza  Express", "", ""],
                                         ["UK", "Loungers", "https://thelounges.co.uk", ""],
                                         ["US", "Other Garden", "http://olivegarden.com", ""]]},
    {"name": "Contacts", "rows": [["Company", "Name", "Title"], ["Nando's", "A B", "Head of Partnerships"]]},
    {"name": "Decision-Makers", "rows": [["Company", "Name", "Job title", "Source"],
                                         ["Loungers", "C D", "COO", "https://x"]]},
    {"name": "Sources & notes", "rows": [["Note"], ["x"]]},
    {"name": "Read Me", "rows": [["About"], ["Plexecute"]]},
]
TIDY = [
    {"do": "rename_sheet", "sheet": "National chains", "to": "National Chains"},
    {"do": "rename_sheet", "sheet": "regional chains", "to": "Regional Chains"},
    {"do": "rename_column", "sheet": "Contacts", "column": "Title", "to": "Job title"},
    {"do": "move_rows", "sheet": "Contacts", "to": "Decision-Makers"},
    {"do": "remove_sheet", "sheet": "Sources & notes"},
    {"do": "remove_duplicates", "sheets": ["National Chains", "Regional Chains"], "by": ["Company", "Website"]},
    {"do": "fill_blank", "column": "Still to check", "value": "nothing outstanding"},
    {"do": "sort", "column": "Country", "order": ["UK", "US"]},
    {"do": "set_cells", "sheet": "National Chains", "column": "Company", "equals": "olive garden",
     "set": {"Still to check": "email"}},
    {"do": "order_sheets", "sheets": ["National Chains", "Regional Chains", "Decision-Makers", "Read Me"]},
]


def test_a_workbook_is_tidied_exactly_as_asked_and_every_other_cell_is_left_alone():
    import copy

    from app.core.agents.workspace_ops import tidy_sheets

    before = copy.deepcopy(BOOK)
    after, done = tidy_sheets(BOOK, TIDY)
    assert BOOK == before                                              # the sheets given are not changed
    assert [s["name"] for s in after] == ["National Chains", "Regional Chains", "Decision-Makers", "Read Me"]
    national, regional, people = after[0]["rows"], after[1]["rows"], after[2]["rows"]
    # Duplicates go by company name or by website (compared as a site), across the sheets, the first kept; UK first.
    assert [row[1] for row in national[1:]] == ["Nando's", "Pizza Express", "Olive Garden"]
    assert [row[1] for row in regional[1:]] == ["Loungers"]
    assert national[1][3] == "count" and national[2][3] == "nothing outstanding" and national[3][3] == "email"
    assert national[1][2] == "https://www.nandos.co.uk"                 # untouched cells stay as they were
    assert people[2][:3] == ["Nando's", "A B", "Head of Partnerships"] and len(people) == 3
    assert any("3 duplicate rows removed" in line for line in done) and len(done) == len(TIDY)
    # A change that cannot be made names what exists, and nothing is changed.
    for bad, said in (([{"do": "rename_sheet", "sheet": "Nope", "to": "X"}], "the sheets are: National chains"),
                      ([{"do": "explode"}], "must be one of"),
                      ([{"do": "rename_sheet", "sheet": "Read Me", "to": "Contacts"}], "already a sheet named"),
                      ([TIDY[0], {"do": "fill_blank", "sheet": "National Chains", "column": "Zed", "value": "x"}],
                       "change 2 (fill_blank): no column 'Zed'")):
        with pytest.raises(ValueError, match=None) as refused:
            tidy_sheets(BOOK, bad)
        assert said in str(refused.value)
    assert BOOK == before


@pytest.mark.integration
def test_the_partnerships_lead_tidies_the_booking_workbook_with_its_own_tool(project):  # noqa: F811
    from pathlib import Path

    from app.core.agents.workspace_ops import xlsx_read
    from app.core.command.tool_runtime import ToolRuntime
    from tests.test_repair12e3a_workspace_tools import _seed as seed_workspace

    host, root = project
    book = Path(root) / "plexecute" / "partners.xlsx"

    async def go():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await seed_workspace(db, host)
            runtime = ToolRuntime(db, ws_id, None, operator="agent:partnerships", authority_level=3,
                                  user_id=user_id)
            runner = RoleExecutor(runtime, "gpt-6-luna", host, role="partnerships")
            await runner._prepare_tools()
            call = runner.toolbox.call
            await call("write_spreadsheet", {"path": "plexecute/partners.xlsx", "sheets": BOOK})
            refused = await call("tidy_spreadsheet", {"path": "plexecute/partners.xlsx", "changes": [
                TIDY[0], {"do": "remove_sheet", "sheet": "No such sheet"}]})
            untouched = [s["name"] for s in xlsx_read(book.read_bytes())]
            tidied = await call("tidy_spreadsheet", {"path": "plexecute/partners.xlsx", "changes": TIDY})
            missing = await call("tidy_spreadsheet", {"path": "plexecute/none.xlsx", "changes": TIDY})
            return refused, untouched, tidied, missing, list(runtime.calls)

    refused, untouched, tidied, missing, calls = _run(go())
    saved = xlsx_read(book.read_bytes())
    assert refused["success"] is False and "Nothing was changed" in refused["error"]
    assert untouched[0] == "National chains"                            # all the changes, or none
    assert tidied["success"] and tidied["rows_per_sheet"] == {
        "National Chains": 3, "Regional Chains": 1, "Decision-Makers": 2, "Read Me": 1}
    assert "WORKBOOK FACTS" in tidied["facts"] and len(tidied["changes_made"]) == len(TIDY)
    assert [s["name"] for s in saved] == ["National Chains", "Regional Chains", "Decision-Makers", "Read Me"]
    assert list((Path(root) / ".jai" / "backups").glob("partners-*.xlsx"))   # the copy before the change is kept
    assert missing["success"] is False
    assert "tidy_spreadsheet" in role_tools("partnerships")
    last = [c for c in calls if c.get("tool") == "write_file"][-1]      # recorded as a file write, like every save
    assert last["success"] and "tidied:" in last["summary"]


def test_a_reply_in_words_sends_a_roles_agent_back_to_work_and_the_base_mission_is_unchanged():
    from app.core.command.agent_executor import MAX_WORDS_ONLY, AgentExecutor

    executor = _role_executor([{"id": "R3", "status": "open"}, {"id": "R4", "status": "open"}], 14)
    nudge = executor._words_only(61)
    assert nudge.startswith("[A REPLY IN WORDS DOES NOT DO THE WORK]") and "R3, R4" in nudge and "61 steps" in nudge
    assert "tidy_spreadsheet" in nudge
    assert executor._words_only(0) is None                              # no steps left: the round ends
    assert _role_executor([{"id": "R1", "status": "done"}], 14)._words_only(61) is None   # nothing open: it is done
    assert AgentExecutor._words_only(executor, 61) is None and MAX_WORDS_ONLY == 3
