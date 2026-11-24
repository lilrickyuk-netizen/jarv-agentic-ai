"""24 November, Richard: "The full Superpowers and ECC plugins in every Claude SDK session, sandbox included, with
ECC's learning persisted between missions", every skill usable ("offer short-editing again"). The backend tells the
sandbox which packs come whole as plugins (and keeps their skills out of the plain list, so none is listed twice),
the business engine's plugins carry every skill of their pack, and short-editing is offered to the studio."""
from pathlib import Path

from app.core.command import claude_engine
from app.core.config import settings
from app.core.knowledge import skill_packs


def _packs(root: Path) -> Path:
    """A skill-packs folder as scripts/skill-packs.sh leaves it: Superpowers and ECC with their plugin parts."""
    files = {
        "superpowers/skills/brainstorming/SKILL.md": "---\nname: brainstorming\ndescription: b\n---\n",
        "superpowers/skills/writing-plans/SKILL.md": "---\nname: writing-plans\ndescription: w\n---\n",
        "superpowers/agents/code-reviewer.md": "a", "superpowers/hooks/hooks.json": "{}",
        "ecc/skills/continuous-learning-v2/SKILL.md": "---\nname: continuous-learning-v2\ndescription: l\n---\n",
        "ecc/skills/fastapi-patterns/SKILL.md": "---\nname: fastapi-patterns\ndescription: f\n---\n",
        "ecc/skills/not-chosen-by-jai/SKILL.md": "---\nname: not-chosen-by-jai\ndescription: n\n---\n",
        "ecc/agents/planner.md": "a", "ecc/hooks/hooks.json": "{}", "ecc/scripts/hooks/observe.sh": "#",
        "ecc/commands/evolve.md": "c",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


def test_the_sandbox_is_told_which_packs_come_whole_and_their_skills_are_not_listed_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SKILL_PACKS_DIR", str(_packs(tmp_path / "packs")))
    plugins = {p["name"]: p for p in skill_packs.sandbox_plugins()}
    assert set(plugins) == {"superpowers", "ecc"}
    assert plugins["ecc"]["parts"] == ["agents", "commands", "hooks", "scripts"] and plugins["ecc"]["whole_root"]
    assert plugins["superpowers"]["whole_root"] and plugins["ecc"]["root"] == "skills"
    apart = skill_packs.all_skills(plugins_apart=True)
    assert not [p for p in apart if p.split("/", 1)[0] in plugins]          # left to the plugins
    assert [p for p in skill_packs.all_skills() if p.startswith("ecc/")]   # the plain list still has them


def test_no_plugin_packs_on_disk_means_the_plain_list_keeps_every_skill(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SKILL_PACKS_DIR", str(tmp_path / "empty"))
    assert skill_packs.sandbox_plugins() == []
    assert skill_packs.all_skills(plugins_apart=False) == skill_packs.all_skills()


def test_the_business_engines_ecc_plugin_carries_every_skill_of_the_pack(tmp_path, monkeypatch):
    """17 November it carried only the specialist's trade; 24 November, every skill (the full plugin)."""
    monkeypatch.setattr(settings, "SKILL_PACKS_DIR", str(_packs(tmp_path / "packs")))
    engine = claude_engine.ClaudeRoleExecutor.__new__(claude_engine.ClaudeRoleExecutor)
    config = tmp_path / "config"
    config.mkdir()
    out = engine._plugins(config)
    assert {Path(p["path"]).name for p in out} == {"superpowers", "ecc"}
    ecc = {p.name for p in (config / "plugins" / "ecc" / "skills").iterdir()}
    assert {"continuous-learning-v2", "fastapi-patterns", "not-chosen-by-jai"} <= ecc
    superpowers = {p.name for p in (config / "plugins" / "superpowers" / "skills").iterdir()}
    assert {"brainstorming", "writing-plans"} <= superpowers


def test_short_editing_is_offered_to_the_studio_again():
    entry = next(e for e in skill_packs.SKILLS if e["skill"] == "short-editing")
    assert entry["pack"] == "video-agent-skills"
    for role in ("creation", "content"):
        assert "short-editing" in {p.rsplit("/", 1)[-1] for p in skill_packs.sandbox_skills(role)}, role
