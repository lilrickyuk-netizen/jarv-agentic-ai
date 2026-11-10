"""
JAI picks the specialist for the work itself (Richard, 9 November: "I shouldn't really have to mention what skill it
needs to use"). A prospect database built by the Lead Builder loaded none of the sales skills; the same brief naming
the prospecting skill went to the Sales Lead and used them. Real: the brief's classification, the tier-2 package the
mission plans, its standard, title and saved card, and the skills the sandbox is given.
"""
from __future__ import annotations

from app.core.command.mission_org import SPECIALISTS, MissionTeam, Package
from app.core.command.work_type import first_skills, specialist_for
from app.core.knowledge.skill_packs import sandbox_skills


def _kind(brief: str):
    found = specialist_for(brief)
    return found["specialist"] if found else None


def test_sales_and_prospecting_work_goes_to_the_sales_lead():
    for brief in ("In C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES, build a proper investor and buyer database for "
                  "Plexecute with at least 50 entries, with contact details",
                  "Find 30 potential acquirers for Plexecute", "Put together a list of UK angel networks",
                  "Write the outreach to everyone on the prospects list, with the pitch deck attached"):
        assert _kind(brief) == "sales", brief


def test_each_kind_of_work_has_its_specialist():
    assert _kind("make me a professional pitch deck for plexecute for investors") == "content"
    assert _kind("Write a competitor analysis of habit and wellbeing apps") == "research"
    assert _kind("Create a financial model for Plexecute's first three years") == "finance"
    assert _kind("Write the business plan for MYCO") == "business"
    assert _kind("Write Plexecute's privacy policy and terms of service") == "legal"
    assert _kind("Write the help centre FAQs for Plexecute") == "customer_support"
    assert _kind("Write the Plexecute launch plan") == "marketing"
    assert _kind("Write five LinkedIn posts about Plexecute") == "content"


def test_software_and_video_work_stays_with_the_lead_builder():
    for brief in ("Carry on with MYCO Phase 1", "Fix the login bug in the Plexecute app",
                  "Build the investor CRM feature in the MYCO backend", "Build the landing page for Plexecute",
                  "Make a 30 second video ad for Plexecute aimed at investors"):
        assert _kind(brief) is None, brief


def test_the_specialist_starts_from_its_own_skills():
    assert first_skills("sales", ("prospecting", "lead-intelligence", "investor-outreach", "cold-email")) == [
        "prospecting", "lead-intelligence", "investor-outreach", "cold-email"]
    sales = [path.rsplit("/", 1)[-1] for path in sandbox_skills("sales")]
    assert {"prospecting", "cold-email", "investor-outreach", "copywriting"} <= set(sales)
    assert "test-driven-development" not in sales


def test_the_mission_plans_the_builder_as_that_specialist():
    team = MissionTeam.__new__(MissionTeam)
    package = team._builder_package(["R1", "R2"], kind=specialist_for("Build an investor database for Plexecute"))
    assert package.specialist == "builder" and package.acting_as == "sales" and package.model == "research"
    assert package.role == "Sales Lead" and package.title == "The Sales Lead does the mission"
    assert "invoke your prospecting" in package.goal and package.requirements == ["R1", "R2"]
    assert package.standard.startswith(SPECIALISTS["sales"]["standard"])
    assert "search tools" in package.standard
    assert package.card()["acting_as"] == "sales" and package.card()["role"] == "Sales Lead"
    plain = team._builder_package(["R1"])
    assert plain.acting_as is None and plain.role == "Lead Builder"
    assert plain.standard == SPECIALISTS["builder"]["standard"]


def test_the_sandbox_gives_the_specialist_its_skills_and_standard():
    from types import SimpleNamespace

    from app.core.command.sandbox_engine import SandboxSpecialist

    package = Package(id="B1", title="t", specialist="builder", goal="g", owns=[], depends_on=[], requirements=[],
                      done_when="", acting_as="sales")
    runner = SandboxSpecialist.__new__(SandboxSpecialist)
    runner.package = package
    runner.team = SimpleNamespace()
    assert runner._standard().startswith("You are JAI's Sales Lead")


def test_a_later_round_keeps_the_specialist_whatever_jai_ran():
    """9 November: round 2 of the Sales Lead's prospects mission read `python` in JAI's own progress note and went
    back to the Lead Builder."""
    from app.core.command.continuation import progress_note

    brief = "In C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES, improve outreach/Plexecute-Prospects.xlsx."
    note = progress_note({"tool_calls": [
        {"tool": "run_command", "inputs": {"command": "python3 build_prospects.py"}, "success": True,
         "output": {"exit_code": 0}},
        {"tool": "write_file", "inputs": {"path": "outreach/build.py"}, "success": True}],
        "verification": {"unmet": ["R3 deploy the code to the repo"]}})
    assert "PROGRESS FROM EARLIER ROUNDS" in note
    assert _kind(f"{brief}\n\n{note}") == "sales"
    assert _kind("RICHARD HAS APPROVED THE SIGN-OFF") is None


def test_work_in_richards_folder_is_a_mission_whatever_words_it_uses():
    """9 November: "finish outreach/Plexecute-Prospects.xlsx ... Do no new research" went to the one-off web
    research answer, which cannot open the folder."""
    from app.core.command.service import CommandService

    finish = ("In C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES, finish outreach/Plexecute-Prospects.xlsx with "
              "what you have found. Move every other organisation to a sheet called \"Not yet proven\". Do no new "
              "research beyond finishing rows you have already started.")
    plan = ("In C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES, put together Plexecute's waiting-list growth plan "
            "with newsletters to sponsor and a marketing plan.")
    for brief in (finish, plan):
        assert CommandService._detect_intent(brief) == "agent_task", brief
    assert CommandService._detect_intent("npm install in C:\\Users\\lilri\\Projects\\MYCO") == "package_install"
    assert CommandService._detect_intent("research the npm package left-pad") == "research"
    assert CommandService._detect_intent("Draft a marketing email for the Plexecute launch") == "company_workflow"


def test_a_specialist_leaves_earlier_missions_tests_alone_and_its_check_is_brief():
    """9 November: the Verifier of a 25-row spreadsheet update re-ran the tests earlier prospects missions had left
    in the folder, which contradicted the new work, for most of an hour."""
    from app.core.command import mission_org

    team = MissionTeam.__new__(MissionTeam)
    package = team._builder_package(["R1"], kind=specialist_for("Build an investor database for Plexecute"))
    assert "leave the old ones alone" in package.goal
    assert "not yours to keep" not in team._builder_package(["R1"]).goal  # software keeps its whole test suite
    assert "earlier missions left in this folder" in mission_org.SPECIALIST_CHECK
    assert mission_org.SPECIALIST_CHECK_STEPS <= 20 and mission_org.SPECIALIST_CHECK_COST <= 0.5


def test_the_report_shows_what_the_mission_cost(monkeypatch):
    import asyncio

    from app.core.command import mission_budget

    async def spent(task_id):
        return 4.0 if task_id == "t1" else 0.0

    monkeypatch.setattr(mission_budget, "spent", spent)
    assert asyncio.run(mission_budget.line("t1")) == "\n\n**Cost of this mission so far: $4.00 (about £3.12).**"
    assert asyncio.run(mission_budget.line("t2")) == ""


def test_specialist_work_is_one_round_of_searching_not_a_software_build():
    """10 November: a 120-row growth list ran four rounds and hours, writing a unit test per requirement and scraping
    pages with Python, when JAI's own search tools were there to use."""
    from app.core.command import mission_org
    from app.core.command.sandbox_engine import builder_method, specialist_method

    team = MissionTeam.__new__(MissionTeam)
    package = team._builder_package(["R1"], kind=specialist_for("Write the Plexecute launch plan"))
    assert package.max_steps == mission_org.SPECIALIST_STEPS <= 100
    assert package.max_cost == mission_org.SPECIALIST_COST <= 2.0 and package.model == mission_org.RESEARCH
    method = specialist_method(package.max_steps)
    assert "web_search" in method and "fetch_url" in method and "Do not write an init script, unit tests" in method
    assert "no second round" in method and "Never pad a list" in method and "init.sh" not in method
    assert "init.sh" in builder_method("Carry on with MYCO Phase 1")
    team.packages = [package]
    assert team._specialist_work() is True
    team.packages = [team._builder_package(["R1"])]
    assert team._specialist_work() is False


def test_research_runs_on_haiku_software_on_sonnet_and_opus_only_when_stuck(monkeypatch):
    """Richard, 10 November: speed and cost. Research and writing on Haiku 5.5 (Luna when Anthropic cannot serve it),
    software on Sonnet 5.5, Opus 5.5 only when a round of software work completed nothing."""
    import asyncio
    from types import SimpleNamespace

    from app.core.command import metrics, sandbox_engine
    from app.core.config import settings
    from app.core.providers import router

    no_credit = set()

    async def has_no_credit(provider):
        return provider in no_credit

    monkeypatch.setattr(router, "has_no_credit", has_no_credit)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "ck-test", raising=False)
    team = MissionTeam.__new__(MissionTeam)

    def model_of(package, stuck=False):
        runner = sandbox_engine.SandboxSpecialist.__new__(sandbox_engine.SandboxSpecialist)
        runner.package, runner.team = package, SimpleNamespace(stuck=stuck)
        return asyncio.run(runner.model())

    research = team._builder_package(["R1"], kind=specialist_for("Build an investor database for Plexecute"))
    software = team._builder_package(["R1"])
    assert model_of(research) == "claude-haiku-5-5" and research.effort is None
    assert settings.OPENHANDS_RESEARCH_EFFORT == "low"
    assert model_of(software) == "claude-sonnet-5-5"
    assert model_of(software, stuck=True) == "claude-opus-5-5"
    assert model_of(research, stuck=True) == "claude-haiku-5-5"  # research is never handed to Opus
    no_credit.add("claude")
    assert model_of(research) == "gpt-6-luna"
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None, raising=False)
    assert model_of(research) == "gpt-6-sol"  # no Anthropic credit and no OpenAI key: the general fallback

    # Haiku's price, and its higher rate once a request passes 100K tokens.
    usage = metrics.Usage()
    usage.add({"input_tokens": 50_000, "output_tokens": 1_000}, "claude-haiku-5-5", "mission")
    assert abs(usage.cost_usd - (50_000 * 0.10 + 1_000 * 0.50) / 1e6) < 1e-12
    usage = metrics.Usage()
    usage.add({"input_tokens": 120_000, "output_tokens": 1_000}, "claude-haiku-5-5", "mission")
    assert abs(usage.cost_usd - (120_000 * 0.50 + 1_000 * 2.50) / 1e6) < 1e-12
    assert metrics.SANDBOX_PRICES["claude-haiku-5-5"] == (0.50, 2.50, 0.05, 0.625)


def test_growth_lists_and_any_document_job_go_to_a_specialist():
    """10 November: "update growth/Plexecute-Waitlist-Growth.xlsx ... Newsletters, podcasts and blogs ... Creators ...
    Communities ... Employers" matched no word and went to the Lead Builder."""
    growth = ("In C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES, update growth/Plexecute-Waitlist-Growth.xlsx. "
              "Keep every row already there that has a published contact. Newsletters, podcasts and blogs (target 30). "
              "Creators (target 40) on YouTube, Instagram, TikTok and LinkedIn. Communities (target 20).")
    assert _kind(growth) == "marketing"
    assert _kind("Find 40 fitness YouTubers with a business email") == "marketing"
    assert _kind("In C:\\Users\\lilri\\Projects\\X, tidy notes/meeting-notes.md") == "research"
    assert _kind("Fix the failing tests in C:\\Users\\lilri\\Projects\\MYCO") is None
    assert _kind("Update the README.md of the MYCO repo") is None  # software words keep it with the builder
