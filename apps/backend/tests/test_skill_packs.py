"""
Upgrades 1-5: the skill packs (Superpowers, UI/UX Pro Max, Marketing Skills, No AI Slop, BRAG Slim) as JAI
knowledge. Real: the manifest, reading a skill from a pack folder, the knowledge library storing it as passages for
its agents only and finding it by hybrid search, the sandbox policy and the catalogue. The pack folder is a small
one made in the test, so nothing is downloaded and no model is called.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.knowledge import skill_packs
from tests.conftest import AsyncTestingSessionLocal


def test_every_pack_is_mit_and_pinned_to_a_full_commit():
    for name, pack in skill_packs.PACKS.items():
        assert len(pack["commit"]) == 40 and int(pack["commit"], 16) >= 0, name
    entries = skill_packs.catalogue_entries()
    assert len({e["url"] for e in entries}) == len(entries) == len(skill_packs.SKILLS)
    for entry in entries:
        assert entry["url"].startswith("https://github.com/") and "/tree/" in entry["url"]
        assert (entry["licence"], entry["licence_evidence"].count("MIT License")) == ("MIT", 1) or \
            (entry["licence"], entry["licence_evidence"].count("Apache License 2.0")) == ("Apache-2.0", 1)
        assert entry["licence_class"] == "store" and entry["agents"]


def test_the_right_agents_get_the_right_skills():
    by_skill = {e["skill"]: set(e["agents"]) for e in skill_packs.SKILLS}
    assert {"coding_agent", "debugging_agent"} <= by_skill["systematic-debugging"]
    assert "coding_agent" in by_skill["ui-ux-pro-max"] and "creation" in by_skill["ui-ux-pro-max"]
    assert by_skill["cold-email"] == {"sales"}
    assert {"content", "marketing", "sales"} <= by_skill["no-ai-slop"]
    assert {"creation", "marketing"} <= by_skill["brag-slim"]
    # Full BRAG hands its composition brief to Hyperframes' own skills: without them it improvised (9 November).
    assert {"hyperframes", "hyperframes-cli", "hyperframes-registry", "media-use"} <= set(by_skill)
    names = {e["skill"] for e in skill_packs.SKILLS}
    # Left out: asking Richard questions mid-task, and Superpowers' own meta skills.
    assert not names & {"brainstorming", "using-superpowers", "diagnosing-superpowers"}


def test_sandbox_specialists_see_only_their_roles_skills():
    engineer = skill_packs.sandbox_skills("coding_agent")
    assert "superpowers/skills/test-driven-development" in engineer
    assert "ui-ux-pro-max/.claude/skills/ui-ux-pro-max" in engineer
    assert not any(s.startswith("marketingskills/skills/cold-email") for s in engineer)
    creator = skill_packs.sandbox_skills("creation")
    assert "brag/skills/brag-slim" in creator and "marketingskills/skills/video" in creator
    assert "superpowers/skills/verification-before-completion" in skill_packs.sandbox_skills("verifier")
    # No orchestration skills inside the sandbox: JAI's mission team already runs the team.
    every = {s for role in ("coding_agent", "creation", "marketing", "verifier", "sales")
             for s in skill_packs.sandbox_skills(role)}
    assert not any("subagent-driven" in s or "dispatching-parallel" in s for s in every)


def _pack(root: Path) -> str:
    folder = root / "superpowers" / "skills" / "systematic-debugging"
    (folder / "evals").mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: systematic-debugging\ndescription: Debug by root cause.\n---\n"
                                     f"# Systematic debugging\n\nFind the root cause first. rootcause{root.name}\n")
    (folder / "root-cause-tracing.md").write_text("## Tracing\n\nTrace the bad value back to where it began.\n")
    (folder / "evals" / "cases.md").write_text("never stored\n")
    return "superpowers/skills/systematic-debugging"


def test_a_skill_is_read_with_its_own_files_and_never_outside_the_packs(tmp_path):
    local = _pack(tmp_path)
    text, reason = skill_packs.read_skill(local, root=tmp_path)
    assert reason == "" and text.startswith("---\nname: systematic-debugging")
    assert "# root-cause-tracing.md" in text and "never stored" not in text
    assert skill_packs.read_skill("../../etc", root=tmp_path)[0] is None
    missing, why = skill_packs.read_skill("brag/skills/brag-slim", root=tmp_path)
    assert missing is None and "skill-packs.sh" in why


def test_the_sandbox_may_view_skills_but_never_change_them():
    from app.core.command.sandbox_policy import Scope, check_file

    scope = Scope(root="/tmp/jarv_sandbox/myco")
    assert check_file("view", "/jai/skills/brag/skills/brag-slim/SKILL.md", scope) is None
    assert "read-only" in check_file("create", "/jai/skills/brag/skills/brag-slim/SKILL.md", scope)
    assert "outside" in check_file("view", "/etc/passwd", scope)


def test_the_catalogue_carries_the_skills_unless_they_are_switched_off(monkeypatch):
    from app.core.config import settings
    from app.core.knowledge.documentation import catalogue

    urls = {e["url"] for e in catalogue()}
    assert {e["url"] for e in skill_packs.catalogue_entries()} <= urls
    monkeypatch.setattr(settings, "SKILL_PACKS_ENABLED", False)
    assert not {e["url"] for e in skill_packs.catalogue_entries()} & {e["url"] for e in catalogue()}
    assert skill_packs.sandbox_skills("coding_agent") == []


@pytest.mark.integration
def test_a_skill_is_stored_for_its_agents_and_found_by_the_task(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.core.knowledge.ingest import KnowledgeIngestor
    from app.core.knowledge.search import search_passages

    monkeypatch.setattr(settings, "SKILL_PACKS_DIR", str(tmp_path))
    local = _pack(tmp_path)
    entry = {**next(e for e in skill_packs.catalogue_entries() if e["local_path"] == local),
             "url": f"https://github.com/obra/superpowers/tree/test-{uuid4().hex[:8]}/skills/systematic-debugging"}
    ingestor = KnowledgeIngestor()

    async def run():
        async with AsyncTestingSessionLocal() as db:
            if db.get_bind().dialect.name != "postgresql":
                return None
            results = await ingestor.install(db, [entry], agents=["debugging_agent"])
            mine = await search_passages(db, f"rootcause{tmp_path.name}", agents=["debugging_agent"])
            theirs = await search_passages(db, f"rootcause{tmp_path.name}", agents=["sales"])
            again = await ingestor.install(db, [entry], agents=["debugging_agent"])
            return results, mine, theirs, again

    out = asyncio.run(run())
    if out is None:
        pytest.skip("passage search needs PostgreSQL")
    results, mine, theirs, again = out
    assert results[0]["status"] == "updated" and results[0]["passages"] >= 2
    assert mine and mine[0]["licence"] == "MIT" and "superpowers" in mine[0]["url"]
    assert theirs == []  # a skill reaches only the agents whose work it is
    assert again[0]["status"] == "unchanged"


def test_ecc_skills_reach_the_right_agents_without_its_agents_or_hooks():
    ecc = {e["skill"]: e for e in skill_packs.SKILLS if e["pack"] == "ecc"}
    assert {"fastapi-patterns", "postgres-patterns", "security-review", "remotion-video-creation", "seo",
            "investor-outreach", "lead-intelligence"} <= set(ecc)
    assert "coding_agent" in ecc["fastapi-patterns"]["agents"] and "security" in ecc["security-review"]["agents"]
    assert "ecc/skills/remotion-video-creation" in skill_packs.sandbox_skills("creation")
    assert skill_packs.PACKS["ecc"]["repo"] == "affaan-m/ECC"
    # One skill name per specialist: the sandbox loads skills by name.
    for role in ("coding_agent", "creation", "marketing", "content", "qa", "verifier", "security", "sales"):
        names = [p.rsplit("/", 1)[1] for p in skill_packs.sandbox_skills(role)]
        assert len(names) == len(set(names)), role


def test_a_skill_agentshield_flags_is_never_read_or_listed(tmp_path, monkeypatch):
    from app.core.config import settings

    local = _pack(tmp_path)
    (tmp_path / "superpowers" / ".jai-blocked").write_text("skills/systematic-debugging\n")
    (tmp_path / "superpowers" / ".agentshield.json").write_text('{"score": {"grade": "B"}, "findings": []}')
    monkeypatch.setattr(settings, "SKILL_PACKS_DIR", str(tmp_path))
    text, reason = skill_packs.read_skill(local)
    assert text is None and reason.startswith("blocked") and "AgentShield" in reason
    assert "superpowers/skills/systematic-debugging" not in skill_packs.sandbox_skills("debugging_agent")
    assert skill_packs.scan_status()["superpowers"] == "grade B"
    assert skill_packs.scan_status()["ecc"] == "not scanned"


@pytest.mark.integration
def test_a_skill_flagged_after_it_was_stored_leaves_every_search(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.core.knowledge.ingest import KnowledgeIngestor
    from app.core.knowledge.search import search_passages

    monkeypatch.setattr(settings, "SKILL_PACKS_DIR", str(tmp_path))
    local = _pack(tmp_path)
    entry = {**next(e for e in skill_packs.catalogue_entries() if e["local_path"] == local),
             "url": f"https://github.com/obra/superpowers/tree/flag-{uuid4().hex[:8]}/skills/systematic-debugging"}
    ingestor = KnowledgeIngestor()

    async def run():
        async with AsyncTestingSessionLocal() as db:
            if db.get_bind().dialect.name != "postgresql":
                return None
            await ingestor.install(db, [entry], agents=["debugging_agent"])
            before = await search_passages(db, f"rootcause{tmp_path.name}", agents=["debugging_agent"])
            (tmp_path / "superpowers" / ".jai-blocked").write_text("skills/systematic-debugging\n")
            again = await ingestor.install(db, [entry], agents=["debugging_agent"])
            after = await search_passages(db, f"rootcause{tmp_path.name}", agents=["debugging_agent"])
            return before, again, after

    out = asyncio.run(run())
    if out is None:
        pytest.skip("passage search needs PostgreSQL")
    before, again, after = out
    assert before and again[0]["status"] == "blocked" and after == []
