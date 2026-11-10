"""
Every specialist brings its trade to the work, and Richard says a thing once (Richard, 10 November: "should I have to
tell my marketing employee how to market? ... I shouldn't have to send it big detailed prompts"). Real: the skill
catalogue and its tagging, the field-knowledge library, the routing and intent rules, the requirements step, the
specialist's sandbox brief and the workspace rules in the test database. Stood in: the models that set out the job
and pick out standing rules (no test spends provider credit), and the skill packs' files (written to a temporary
folder with the phrases the real skills are written for).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.command import expertise, work_type
from app.core.command.requirements import derive
from app.core.command.service import CommandService
from app.core.knowledge import skill_packs
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_rules import WorkspaceRule
from tests.conftest import AsyncTestingSessionLocal

ONE_LINE = "Find free places to market Plexecute"

SKILL_FILES = {
    "influencer-marketing": ("When the user wants to run influencer, creator, or ambassador partnerships to promote "
                             "their product. Also use when the user mentions 'influencer marketing,' 'creator "
                             "partnerships,' 'brand ambassador,' 'creator program,' or 'gifting.'",
                             "# Influencer marketing\n\nFind creators from curated lists, vet each one, then reach "
                             "out with a specific offer.\n\n## Vetting\nCheck engagement, not follower counts."),
    "link-building": ("When the user wants to earn backlinks or third-party mentions. Also use when the user "
                      "mentions 'link building,' 'resource pages,' 'guest posting,' or 'get into best-of lists.'",
                      "# Link building\n\nGuest posting: pitch an article idea, never pay for a placement."),
    "public-relations": ("When the user wants help with public relations, earned media or press coverage. Also use "
                         "when the user mentions 'PR,' 'press,' 'media list,' or 'guest article.'",
                         "# Public relations\n\nBuild a media list from outlets that cover your field."),
    "marketing-plan": ("When the user wants a marketing plan. Also use when the user mentions 'marketing plan' or "
                       "'quarterly plan.'", "# Marketing plan\n\nSet goals, channels and a calendar."),
    "copywriting": ("When the user wants marketing copy. Also use when the user mentions 'write copy' or "
                    "'headline.'", "# Copywriting\n\nLead with the reader's problem."),
}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def packs(tmp_path, monkeypatch):
    from app.core.config import settings

    for name, (description, body) in SKILL_FILES.items():
        folder = tmp_path / "marketingskills" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f'---\nname: {name}\ndescription: "{description}"\n---\n{body}\n',
                                         encoding="utf-8")
    monkeypatch.setattr(settings, "SKILL_PACKS_DIR", str(tmp_path))
    return tmp_path


class Router:
    """Stands in for the models: the job and the standing rules, recorded so the test can see what was asked."""

    def __init__(self, rules=None, job=None):
        self.asked, self.rules, self.job = [], list(rules or []), job

    async def complete(self, request):
        self.asked.append(request)
        text = request.messages[0].content
        if "STANDING rules" in text:
            content = json.dumps({"rules": self.rules.pop(0) if self.rules else []})
        else:
            content = json.dumps(self.job or {"job": "", "skills": []})
        return SimpleNamespace(content=content, usage={"total_tokens": 10}, tool_calls=[])

    def as_role(self, role):
        return self


async def _workspace():
    async with AsyncTestingSessionLocal() as db:
        user_id, ws_id = uuid4(), uuid4()
        db.add(User(id=user_id, username=f"t{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                    password_hash="x", is_active=True, is_admin=False))
        db.add(Workspace(id=ws_id, owner_id=user_id, name="Plexecute", slug=f"plexecute-{ws_id.hex[:8]}",
                         description="", workspace_type="project", authority_level=5, is_active=True, config={}))
        await db.commit()
        return ws_id


# ----- the skills of the trade reach the specialist ---------------------------------------------------------------

def test_a_specialist_is_offered_every_skill_of_its_trade():
    marketing = [p.rsplit("/", 1)[1] for p in skill_packs.sandbox_skills("marketing")]
    assert {"influencer-marketing", "link-building", "public-relations", "directory-submissions",
            "referrals"} <= set(marketing)
    assert len(marketing) == len(set(marketing))
    sales = [p.rsplit("/", 1)[1] for p in skill_packs.sandbox_skills("sales")]
    assert {"prospecting", "cold-email"} <= set(sales) and "test-driven-development" not in sales
    engineer = skill_packs.sandbox_skills("coding_agent")  # software roles are unchanged
    assert not any(p.endswith("/cold-email") or p.endswith("/influencer-marketing") for p in engineer)
    assert not any("subagent-driven" in p for p in skill_packs.sandbox_skills("marketing"))


def test_the_playbooks_are_chosen_for_the_work_not_the_job_title(packs):
    work = "Find UK creators and influencers, blogs that accept free guest posting, and partners"
    chosen = expertise.choose_skills("marketing", work, starting=("marketing-plan", "copywriting"))
    assert chosen[:2] == ["influencer-marketing", "link-building"] or set(chosen[:2]) == {
        "influencer-marketing", "link-building"}
    assert "marketing-plan" not in chosen
    # Nothing in the work matches: the specialist's usual starting skills.
    assert expertise.choose_skills("marketing", "zzz qqq", starting=("marketing-plan", "copywriting")) == [
        "marketing-plan", "copywriting"]


def test_the_playbook_is_given_in_full_and_the_field_knowledge_with_it(packs):
    job = expertise.Job(specialist="marketing", skills=["influencer-marketing", "link-building"],
                        knowledge=expertise.field_knowledge("marketing", "pay creators influencer disclosure ad"))
    text = job.brief_for_specialist()
    assert "YOUR PLAYBOOKS FOR THIS JOB" in text and "=== influencer-marketing ===" in text
    assert "Check engagement, not follower counts." in text and "never pay for a placement" in text
    assert "name: influencer-marketing" not in text  # the frontmatter is not the method
    assert "Clear advertising and influencer disclosure" in text


def test_the_sandbox_brief_carries_the_playbooks_only_for_the_specialist(packs):
    from app.core.command import sandbox_engine
    from app.core.command.mission_org import Package

    job = expertise.Job(specialist="marketing", skills=["influencer-marketing"], rules=["No podcasts."])
    team = SimpleNamespace(runtime=SimpleNamespace(task_id=uuid4()), workspace_root="/test_workspaces/x",
                           _brief=lambda p, m: "brief", job=job)
    lead = Package("B1", "t", "builder", "g", [], [], [], "", acting_as="marketing", max_steps=100)
    brief = sandbox_engine.SandboxSpecialist(team, lead, "m", None)._brief([])
    assert "=== influencer-marketing ===" in brief and "round-up, directory and 'best of' pages first" in brief
    checker = Package("VER", "t", "verifier", "g", [], [], [], "")
    assert "=== influencer-marketing ===" not in sandbox_engine.SandboxSpecialist(team, checker, "m", None)._brief([])


# ----- the job is set out, and the requirements hold the work to it ----------------------------------------------

def test_requirements_include_the_job_and_richards_rules():
    asked = []

    class Analyst:
        async def complete(self, request):
            asked.append(request)
            call = {"function": {"name": "record_requirements", "arguments": json.dumps({"requirements": [
                {"text": "Free-Blogs sheet lists 30 sites that accept free guest articles", "source": "the job"},
                {"text": "No podcasts", "source": "standing rule"}]})}}
            return SimpleNamespace(content="", usage={"total_tokens": 5}, tool_calls=[call])

    job = expertise.Job(specialist="marketing", text="Build growth/free-marketing.xlsx with three sheets.",
                        rules=["No podcasts."])
    result = _run(derive(Analyst(), "m", ONE_LINE, job=job.requirement_guidance()))
    prompt, system = asked[0].messages[0].content, asked[0].system
    assert "THE JOB AS JAI'S SPECIALIST SET IT OUT" in prompt and "- No podcasts." in prompt
    assert "professional standard" in system and "standing rule" in system
    assert [r["source"] for r in result["requirements"]] == ["the job", "standing rule"]
    # Without a job (software), the requirements step is as before.
    _run(derive(Analyst(), "m", "Fix the login page"))
    assert "professional standard" not in asked[1].system


def test_the_job_is_set_out_by_the_specialist_from_the_request(packs, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "TESTING", False)
    router = Router(rules=[[], []], job={"job": "Build growth/Plexecute-Free-Marketing.xlsx: 30 free guest-article "
                                                "sites, 30 UK creators, 20 partners.",
                                         "skills": ["link-building", "influencer-marketing", "not-a-skill"]})

    async def go():
        ws_id = await _workspace()
        async with AsyncTestingSessionLocal() as db:
            return await expertise.job_for(router, "m", ONE_LINE, "marketing", db=db, workspace_id=ws_id)

    job = _run(go())
    assert job.text.startswith("Build growth/Plexecute-Free-Marketing.xlsx")
    assert job.skills == ["link-building", "influencer-marketing"]  # only skills that exist
    setting_out = [r for r in router.asked if r.system and "senior professional" in r.system][0]
    assert "influencer-marketing:" in setting_out.messages[0].content  # it chose from its own skills
    assert "RICHARD'S REQUEST:\nFind free places to market Plexecute" in setting_out.messages[0].content


def test_in_tests_no_model_is_asked_and_the_request_still_gets_its_playbooks(packs):
    router = Router()
    job = _run(expertise.job_for(router, "m", "Find UK creators and blogs for guest posting", "marketing"))
    assert router.asked == [] and job.text == ""
    assert "influencer-marketing" in job.skills or "link-building" in job.skills


# ----- Richard says a thing once ----------------------------------------------------------------------------------

def test_standing_rules_are_learned_once_and_kept_for_the_product(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "TESTING", False)

    async def go():
        ws_id = await _workspace()
        async with AsyncTestingSessionLocal() as db:
            db.add(Task(id=uuid4(), workspace_id=ws_id, title="pitches", task_type="command", status="completed",
                        priority=5, description="Revise growth/pitches.xlsx. Plexecute has not launched, so never "
                                                "claim customers. Delete the Joe Wicks row."))
            await db.commit()
        router = Router(rules=[["Plexecute has not launched: never claim customers."], ["No podcasts."]])
        async with AsyncTestingSessionLocal() as db:
            first = await expertise.learn(router, "m", db, ws_id, "Build the list. No podcasts.")
            await db.commit()
        # The next mission: the recent briefs are not read again, and a rule already held is not added twice.
        again = Router(rules=[["no podcasts"]])
        async with AsyncTestingSessionLocal() as db:
            second = await expertise.learn(again, "m", db, ws_id, "Write the pitches. No podcasts please.")
            await db.commit()
            rules = await expertise.standing_rules(db, ws_id)
            rows = (await db.execute(select(WorkspaceRule).where(WorkspaceRule.workspace_id == ws_id))).scalars()
            kinds = {r.rule_type for r in rows}
        history_prompt = router.asked[0].messages[0].content
        return first, second, rules, kinds, history_prompt, len(again.asked)

    first, second, rules, kinds, history_prompt, asked_again = _run(go())
    assert first == ["Plexecute has not launched: never claim customers.", "No podcasts."]
    assert second == [] and asked_again == 1
    assert set(rules) == {"Plexecute has not launched: never claim customers.", "No podcasts."}
    assert kinds == {expertise.RULE_TYPE}
    assert "Delete the Joe Wicks row." in history_prompt  # the model, not a keyword, decides what is one-off


def test_without_a_model_nothing_is_learned_and_nothing_breaks():
    async def go():
        ws_id = await _workspace()
        async with AsyncTestingSessionLocal() as db:
            added = await expertise.learn(Router(), "m", db, ws_id, "No podcasts.")
            return added, await expertise.standing_rules(db, ws_id)

    assert _run(go()) == ([], [])
    assert _run(expertise.learn(Router(), "m", None, None, "No podcasts.")) == []


# ----- a one-line request is a specialist's mission ---------------------------------------------------------------

@pytest.mark.parametrize("request_text, specialist", [
    (ONE_LINE, "marketing"), ("Promote Plexecute for free", "marketing"), ("Market Plexecute to gym owners",
                                                                             "marketing"),
    ("Find investors for Plexecute", "sales"), ("Do market research on habit apps", "research")])
def test_a_one_line_request_goes_to_its_specialist(request_text, specialist):
    assert work_type.specialist_for(request_text)["specialist"] == specialist


def test_a_one_line_request_is_a_mission_and_a_question_is_not():
    assert CommandService._detect_intent(ONE_LINE) == "agent_task"
    assert CommandService._detect_intent("Find investors for Plexecute") == "agent_task"
    assert CommandService._detect_intent("Can you promote Plexecute for free") == "agent_task"
    assert CommandService._detect_intent("What are good places to market Plexecute?") != "agent_task"
    assert CommandService._detect_intent("Draft a marketing email for the Plexecute launch") == "company_workflow"
    assert CommandService._detect_intent("research the npm package left-pad") == "research"
