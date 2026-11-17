"""
17 November: the skills Richard listed that JAI did not have are installed from their authors' repositories, every
skill a Claude engine session lists reaches Claude whole (nothing dropped for the listing's budget), and each
department hands independent parts of a job to up to 20 workers on the cheaper model, which start with the job's
playbooks already read. Pure: no provider is called, nothing is spent.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.core.command import claude_engine
from app.core.command.claude_engine import ClaudeRoleExecutor, skill_listing, write_listing
from app.core.knowledge import skill_packs

NEW = {"context-compression", "context-optimization", "memory-systems", "long-horizon-prompting",
       "iterative-retrieval", "shipping-and-launch", "observability-and-instrumentation", "ce-compound",
       "differential-review", "playwright-cli"}


def test_the_new_skills_are_registered_pinned_and_licensed():
    names = {e["skill"] for e in skill_packs.SKILLS}
    assert NEW <= names
    for pack in ("context-engineering", "agent-skills", "compound-engineering", "trailofbits", "playwright-cli"):
        info = skill_packs.PACKS[pack]
        assert len(info["commit"]) == 40 and all(c in "0123456789abcdef" for c in info["commit"]), pack
    assert skill_packs.PACKS["trailofbits"]["licence"] == "CC-BY-SA-4.0"
    assert skill_packs.PACKS["playwright-cli"]["licence"] == "Apache-2.0"
    entries = {e["title"]: e for e in skill_packs.catalogue_entries()}
    review = entries["Trail of Bits Skills: differential-review"]
    assert review["licence"] == "CC-BY-SA-4.0" and "Attribution-ShareAlike" in review["licence_evidence"]
    assert review["local_path"] == "trailofbits/plugins/differential-review/skills/differential-review"
    # Skills that run git or a command go to the builder's sandbox, which has the shell they need.
    sandboxed = {e["skill"]: e["sandbox"] for e in skill_packs.SKILLS}
    assert sandboxed["differential-review"] and sandboxed["ce-compound"] and sandboxed["playwright-cli"]


def _skill(folder: Path, name: str, description: str):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: \"{description}\"\n---\n\n# {name}\n")


def test_the_listing_shows_the_jobs_playbooks_in_full_names_the_rest_and_fits_its_budget(tmp_path):
    config = tmp_path / "config"
    _skill(config / "skills" / "cold-email", "cold-email", "Write first emails. " * 20)
    _skill(config / "skills" / "seo-audit", "seo-audit", "Audit a site's SEO. " * 200)    # past Claude Code's cap
    _skill(config / "plugins" / "ecc" / "skills" / "deep-research", "deep-research", "Research in depth.")
    (config / "plugins" / "ecc" / "commands").mkdir(parents=True)
    (config / "plugins" / "ecc" / "commands" / "plan.md").write_text("---\ndescription: Plan the work.\n---\n")
    (config / "settings.json").write_text(json.dumps({"env": {"KEEP": "1"}}))

    listing = write_listing(config, {"cold-email"})
    settings = json.loads((config / "settings.json").read_text())
    assert settings["skillOverrides"] == {"seo-audit": "name-only"} and settings["env"] == {"KEEP": "1"}
    assert listing["names_only"] == ["seo-audit"]
    assert set(listing["full"]) == {"cold-email", "ecc:deep-research", "ecc:plan"}
    assert listing["budget"] >= listing["chars"] > len("Write first emails. " * 20)
    # A description is counted as Claude Code lists it: at most 1,536 characters, however long the file says.
    every = skill_listing(config, {"cold-email", "seo-audit"})
    assert every["chars"] - listing["chars"] <= claude_engine.DESCRIPTION_CAP + 4


def test_ecc_brings_the_specialists_trade_and_its_learning_system_only(tmp_path, monkeypatch):
    from tests.test_claude_engine import _packs

    packs = _packs(tmp_path / "packs")
    monkeypatch.setattr(skill_packs, "packs_dir", lambda: packs)
    runner = SimpleNamespace(_plugins_on_disk=ClaudeRoleExecutor._plugins_on_disk, _trade=lambda: set())
    plugins = {Path(p["path"]).name: Path(p["path"])
               for p in ClaudeRoleExecutor._plugins(runner, tmp_path / "config")}
    assert {p.name for p in (plugins["ecc"] / "skills").iterdir()} == {"continuous-learning-v2"}
    assert {p.name for p in (plugins["superpowers"] / "skills").iterdir()} == {"brainstorming", "writing-plans"}
    runner._trade = lambda: {"fastapi-patterns"}
    plugins = {Path(p["path"]).name: Path(p["path"])
               for p in ClaudeRoleExecutor._plugins(runner, tmp_path / "config2")}
    assert {p.name for p in (plugins["ecc"] / "skills").iterdir()} == {"fastapi-patterns", "continuous-learning-v2"}


def test_workers_run_on_the_cheaper_model_twenty_at_once_with_the_jobs_playbooks(monkeypatch):
    from app.core.config import settings

    assert claude_engine.workers_at_once() == 20
    assert claude_engine.worker_model() == (settings.CLAUDE_WORKER_MODEL or settings.CLAUDE_LIGHT_MODEL)
    monkeypatch.setattr(settings, "CLAUDE_WORKER_MODEL", "claude-haiku-5-5")
    monkeypatch.setattr(settings, "CLAUDE_WORKERS_AT_ONCE", 50)
    assert claude_engine.worker_model() == "claude-haiku-5-5" and claude_engine.workers_at_once() == 20

    runner = ClaudeRoleExecutor.__new__(ClaudeRoleExecutor)
    runner.role, runner.title, runner.standard, runner.workspace_root = "marketing", "Marketing Lead", "", "C:\\P"
    runner.job = SimpleNamespace(skills=["launch", "copywriting", "seo-audit", "fourth"])
    sdk = SimpleNamespace(AgentDefinition=lambda **kw: SimpleNamespace(**kw))
    agents = runner._agents(["write_spreadsheet", "find_contacts"], sdk)
    worker = agents["marketing-worker"]
    assert worker.skills == ["launch", "copywriting", "seo-audit"]          # the job's playbooks, read at start
    assert worker.model == "claude-haiku-5-5" and "Agent" not in worker.tools and "Bash" not in worker.tools
    assert {t for t in worker.tools if t.startswith(claude_engine.PREFIX)} == {
        f"{claude_engine.PREFIX}write_spreadsheet", f"{claude_engine.PREFIX}find_contacts"}
    assert "marketing" not in agents and all(a.model == "claude-haiku-5-5" for a in agents.values())
    assert "marketing-worker" in runner._appended() and "up to 20 at the same time" in runner._appended()
