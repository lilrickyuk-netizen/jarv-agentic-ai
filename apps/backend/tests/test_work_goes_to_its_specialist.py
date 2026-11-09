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
    assert package.specialist == "builder" and package.acting_as == "sales" and package.model == "lead"
    assert package.role == "Sales Lead" and package.title.startswith("The Sales Lead")
    assert "invoke your prospecting" in package.goal and package.requirements == ["R1", "R2"]
    assert package.standard.startswith(SPECIALISTS["sales"]["standard"])
    assert "acceptance ledger" in package.standard
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
