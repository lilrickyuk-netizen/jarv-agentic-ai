"""
The skill packs a specialist may use (Upgrades 1-5): Superpowers, UI/UX Pro Max, Marketing Skills, No AI Slop and
BRAG Slim, cloned at pinned commits into JAI's skill-packs/ folder and mounted read-only at /jai/skills.

JAI's backend names the skills for each run's specialist ("pack/root/skill" folders). Each becomes an OpenHands
AgentSkills skill: only its name and description are in the system prompt, and its full text is loaded when the
specialist calls invoke_skill, so a package pays only for the skills it actually uses.

Two things an AgentSkills skill could otherwise do are switched off, because this service runs as root and the
skills are third-party text: inline !`command` lines (OpenHands runs them when a skill is invoked, outside JAI's
gate) are made literal text, and a skill's own MCP servers (.mcp.json) are never started. Anything a skill tells
the specialist to run goes through the gated terminal like every other command.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import List, Sequence

logger = logging.getLogger("jai.sandbox.skills")

SKILLS_DIR = Path(os.environ.get("JAI_SKILLS_DIR", "/jai/skills"))

# OpenHands' own pattern for skill content (openhands.sdk.skills.execute): fenced blocks, escaped commands and
# inline code are kept; !`command` is what it would run.
_PATTERN = re.compile(r"(?P<fenced>```[\s\S]*?(?:```|$))|(?P<escaped>\\!`[^`]+`)|(?P<inline>(?<!!)`[^`]+`)"
                      r"|!`(?P<cmd>[^`]+)`")


def inert(content: str) -> str:
    """The skill's text with every runnable !`command` escaped, so invoking it shows the command, never runs it."""
    return _PATTERN.sub(lambda m: "\\" + m.group(0) if m.group("cmd") is not None else m.group(0), content)


def load(folders: Sequence[str], root: Path = SKILLS_DIR) -> List:
    """The named skills, ready for AgentContext(skills=...). A folder that is missing, outside the packs or fails
    to load is skipped (logged): a skill is an addition to a specialist, never a reason for a package to fail."""
    from openhands.sdk.skills import Skill

    base = root.resolve()
    skills, names = [], set()
    for folder in folders:
        path = (base / folder / "SKILL.md").resolve()
        try:
            path.relative_to(base)
        except ValueError:
            logger.warning("skill %s is outside the skill packs; skipped", folder)
            continue
        if not path.is_file():
            logger.info("skill %s is not installed; skipped", folder)
            continue
        try:
            skill = Skill.load(path, strict=False, skip_mcp=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("skill %s did not load: %s", folder, exc)
            continue
        if skill.name in names:
            continue
        names.add(skill.name)
        skills.append(skill.model_copy(update={"content": inert(skill.content), "mcp_tools": None}))
    return skills
