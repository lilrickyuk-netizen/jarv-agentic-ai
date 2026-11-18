"""
JAI Backend - What JAI has, read from its own code at the moment it is asked

JAI.md describes how JAI works; the counts and names of what it has change with every upgrade, so they are never
written by hand. This reads them from where they live: the skill packs and their skills (skill_packs.PACKS and
SKILLS, less any AgentShield blocked), each department's skills (expertise.own_skills), the tool and agent registries,
the models and workers the Claude engine uses, and the upgrades installed (the repository's history, upgrades.recent).
Richard, 18 November: "I want JAI to be able to tell me exactly what skills it has, what it's capable of doing,
what upgrades it has had." No AI and nothing spent: it reads files and the registries.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Departments whose work is checking or setting up, not a trade with skills of its own.
_NOT_DEPARTMENTS = frozenset({"verifier", "environment"})


def skills_and_packs() -> Dict[str, Any]:
    """Every skill pack with its source, pin, licence and usable skills; every department's own skills."""
    from app.core.command.expertise import own_skills
    from app.core.command.mission_org import SPECIALISTS
    from app.core.knowledge.skill_packs import PACKS, SKILLS, blocked, skill_path

    refused = blocked()
    packs: List[Dict[str, Any]] = []
    for name, info in PACKS.items():
        mine = [e for e in SKILLS if e["pack"] == name]
        usable = [e["skill"] for e in mine if f"{name}/{skill_path(e)}" not in refused]
        packs.append({"pack": name, "title": info.get("title") or name, "publisher": info.get("publisher") or "",
                      "repo": info.get("repo") or "", "commit": str(info.get("commit") or "")[:7],
                      "licence": info.get("licence") or "MIT", "skills": sorted(usable),
                      "blocked": sorted(e["skill"] for e in mine if e["skill"] not in usable)})
    departments = []
    for role, spec in SPECIALISTS.items():
        if role in _NOT_DEPARTMENTS:
            continue
        names = sorted({e["skill"] for e in own_skills(role)})
        if names:
            departments.append({"role": role, "title": spec.get("title") or role, "skills": names})
    total = len({(e["pack"], e["skill"]) for e in SKILLS})
    usable = sum(len(p["skills"]) for p in packs)
    return {"packs": packs, "departments": departments, "skills_total": total, "skills_usable": usable}


def engine() -> Dict[str, Any]:
    """The models and workers a mission runs with."""
    from app.core.command.claude_engine import engine_model, worker_model, workers_at_once
    from app.core.command.mission_org import CREATIVE_CHECK_COST
    from app.core.knowledge.skill_packs import VIDEO_SKILL

    return {"lead_model": engine_model(), "worker_model": worker_model(), "workers_at_once": workers_at_once(),
            "video_skill": VIDEO_SKILL, "creative_check_max_usd": CREATIVE_CHECK_COST}


def registries() -> Dict[str, int]:
    """How many tools and agents are registered."""
    out = {"tools": 0, "agents": 0}
    try:
        from app.core.tools.registry import list_tools

        out["tools"] = len(list_tools())
    except Exception as exc:  # noqa: BLE001 - a count left at 0 is said as not read, never invented
        logger.info("tool registry not read: %s", exc)
    try:
        from app.core.agents.registry import list_agents

        out["agents"] = len(list_agents())
    except Exception as exc:  # noqa: BLE001
        logger.info("agent registry not read: %s", exc)
    return out


async def inventory(upgrade_days: int = 30) -> Dict[str, Any]:
    """Everything above, and the upgrades installed in the last ``upgrade_days`` days (newest first)."""
    from app.core import upgrades

    found = skills_and_packs()
    return {**found, "engine": engine(), "registries": registries(),
            "upgrades": await upgrades.recent(upgrade_days, 50)}


def as_text(inv: Dict[str, Any]) -> str:
    """The inventory as plain lines, for JAI to answer from in words (chat and voice)."""
    lines = [f"LIVE INVENTORY (read from my code just now): {inv['skills_usable']} usable skills of "
             f"{inv['skills_total']} installed, in {len(inv['packs'])} skill packs; "
             f"{inv['registries']['tools'] or 'an unread number of'} registered tools; "
             f"{inv['registries']['agents'] or 'an unread number of'} registered agents."]
    e = inv["engine"]
    lines.append(f"Missions: the lead specialist runs on {e['lead_model']}; its workers on {e['worker_model']}, up to "
                 f"{e['workers_at_once']} at once; new video work runs on the {e['video_skill']} skill, then an "
                 f"independent creative check (up to ${e['creative_check_max_usd']:.0f}).")
    lines.append("Skill packs:")
    for p in inv["packs"]:
        lines.append(f"- {p['title']} ({p['publisher']}, {p['licence']}, {p['repo']} at {p['commit']}): "
                     f"{len(p['skills'])} skills: {', '.join(p['skills'])}"
                     + (f"; blocked by AgentShield: {', '.join(p['blocked'])}" if p["blocked"] else ""))
    lines.append("Each department's own skills:")
    for d in inv["departments"]:
        lines.append(f"- {d['title']}: {', '.join(d['skills'])}")
    if inv["upgrades"]:
        lines.append(f"Upgrades installed in the last 30 days, newest first ({len(inv['upgrades'])}):")
        lines.extend(f"- {u['when'][:10]}: {u['what']}" for u in inv["upgrades"])
    else:
        lines.append("Upgrade history: not readable here (the repository's history is not mounted).")
    return "\n".join(lines)
