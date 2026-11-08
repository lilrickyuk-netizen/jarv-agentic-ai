"""
JAI Backend - Third-party skill packs (Upgrades 1-5)

Five MIT-licensed skill libraries, each pinned to one commit and cloned by scripts/skill-packs.sh into the
git-ignored folder skill-packs/ (mounted read-only into the backend, the worker and the engineering sandbox):

- Superpowers (obra/superpowers): planning, test-driven development, systematic debugging, code review and
  verification before completion, for the engineering agents.
- UI/UX Pro Max (nextlevelbuilder/ui-ux-pro-max-skill): design-system, typography, colour, layout and
  accessibility knowledge with its searchable local data, for frontend and creation work.
- Marketing Skills (coreyhaines31/marketingskills): SEO, CRO, copy, email, ads, launch, pricing and the rest,
  each skill given to the agents whose work it is.
- No AI Slop (petergyang/no-ai-slop): the final editorial pass for writing that goes to people.
- BRAG Slim (latent-spaces/brag): a project or website made into a short launch video with music and share copy.

Two ways in, both selective so no task pays for knowledge it does not need:

1. JAI's own agents: each skill (its SKILL.md and the Markdown files beside it) is a source in JAI's knowledge
   library for the agents listed here, split into passages and found by hybrid search on the task, like the
   official documentation (consult_specialist_knowledge, search_documentation, the briefs).
2. The mission sandbox: each specialist sees the names and one-line descriptions of its role's skills and loads a
   skill's full text only when it calls invoke_skill (OpenHands' AgentSkills support).

Skills left out on purpose: the ones that make an agent stop to ask Richard questions (Superpowers'
brainstorming), that are about Superpowers itself, or that would start a second orchestration system inside the
sandbox (subagent-driven development and parallel dispatch are knowledge for the orchestrator and the swarm
manager, which already do this in JAI). Removing a pack's folder removes it everywhere; nothing else changes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from app.models.knowledge_library import LICENCE_STORE

PACKS: Dict[str, Dict[str, str]] = {
    "superpowers": {"repo": "obra/superpowers", "commit": "22f0b463e7a5e579904dd6211a520321035526f7",
                    "root": "skills", "title": "Superpowers", "publisher": "Jesse Vincent (obra/superpowers)",
                    "copyright": "Copyright (c) 2025 Jesse Vincent"},
    "ui-ux-pro-max": {"repo": "nextlevelbuilder/ui-ux-pro-max-skill",
                      "commit": "4f2dbb67e64969a9a30ab00742f2d55d66ddec2b", "root": ".claude/skills",
                      "title": "UI/UX Pro Max", "publisher": "Next Level Builder",
                      "copyright": "Copyright (c) 2024 Next Level Builder"},
    "marketingskills": {"repo": "coreyhaines31/marketingskills", "commit": "96798cf38736ecdba015a1d2b0521b0c8f8f41dd",
                        "root": "skills", "title": "Marketing Skills", "publisher": "Corey Haines",
                        "copyright": "Copyright (c) 2025 Corey Haines"},
    "no-ai-slop": {"repo": "petergyang/no-ai-slop", "commit": "000650b156983f5159695b441477f4e63b25dc85",
                   "root": "skills", "title": "No AI Slop", "publisher": "Peter Yang",
                   "copyright": "Copyright (c) 2026 Peter Yang"},
    "brag": {"repo": "latent-spaces/brag", "commit": "669ab9286aa28b6c3ee30e75f181ee74319d012a", "root": "skills",
             "title": "BRAG", "publisher": "Shunit Haviv Hakimi (latent-spaces/brag)",
             "copyright": "Copyright (c) 2026 Shunit Haviv Hakimi"},
}

CODING, DEBUG, DEVOPS, QA, VERIFY = "coding_agent", "debugging_agent", "devops", "qa", "verifier"
INFRA, DOCS, ORCH, SWARM, HEAL, EVOLVE = "infrastructure", "documentation", "orchestrator", "swarm_manager", \
    "self_healing", "self_evolution"
MARKETING, GROWTH, SUPPORT, SALES, ONBOARD = "marketing", "growth", "customer_support", "sales", "onboarding"
COMMUNITY, PARTNER, CONTENT, CREATION = "community", "partnerships", "content", "creation"
ANALYTICS, BUSINESS, RESEARCH, FINANCE, LEGAL = "analytics", "business", "research", "finance", "legal"
ENVIRONMENT = "environment"
ENGINEERING_ROLES = (CODING, DEBUG, QA, DEVOPS, INFRA, ENVIRONMENT)
WRITERS = (CONTENT, MARKETING, SALES, SUPPORT, COMMUNITY, DOCS, ONBOARD, PARTNER, GROWTH, BUSINESS)


def _s(pack: str, skill: str, agents: Sequence[str], sandbox: Sequence[str] = ()) -> Dict:
    return {"pack": pack, "skill": skill, "agents": tuple(agents), "sandbox": tuple(sandbox)}


SKILLS: List[Dict] = [
    # ----- Superpowers (Upgrade 1) ------------------------------------------------------------------------
    _s("superpowers", "test-driven-development", (CODING, DEBUG, QA), (CODING, DEBUG, QA)),
    _s("superpowers", "systematic-debugging", (CODING, DEBUG, QA, DEVOPS, HEAL, VERIFY),
       (CODING, DEBUG, QA, DEVOPS, INFRA, ENVIRONMENT)),
    _s("superpowers", "verification-before-completion", (CODING, DEBUG, QA, VERIFY, DEVOPS),
       ENGINEERING_ROLES + (VERIFY, CREATION, DOCS)),
    _s("superpowers", "writing-plans", (ORCH, CODING, SWARM), (CODING,)),
    _s("superpowers", "executing-plans", (CODING, ORCH), (CODING,)),
    _s("superpowers", "requesting-code-review", (CODING, QA, VERIFY), (CODING, QA)),
    _s("superpowers", "receiving-code-review", (CODING, DEBUG), (CODING, DEBUG)),
    _s("superpowers", "dispatching-parallel-agents", (ORCH, SWARM)),
    _s("superpowers", "subagent-driven-development", (ORCH, SWARM)),
    _s("superpowers", "using-git-worktrees", (CODING, DEVOPS)),
    _s("superpowers", "finishing-a-development-branch", (CODING, DEVOPS)),
    _s("superpowers", "writing-skills", (EVOLVE,)),
    # ----- UI/UX Pro Max (Upgrade 2) ----------------------------------------------------------------------
    _s("ui-ux-pro-max", "ui-ux-pro-max", (CODING, CREATION, QA, ONBOARD), (CODING, CREATION, QA, ONBOARD)),
    _s("ui-ux-pro-max", "design-system", (CODING, CREATION), (CODING, CREATION)),
    _s("ui-ux-pro-max", "ui-styling", (CODING, CREATION), (CODING, CREATION)),
    _s("ui-ux-pro-max", "brand", (MARKETING, CREATION, CONTENT), (MARKETING, CREATION, CONTENT)),
    _s("ui-ux-pro-max", "banner-design", (CREATION, MARKETING), (CREATION, MARKETING)),
    _s("ui-ux-pro-max", "design", (CREATION, MARKETING)),
    _s("ui-ux-pro-max", "slides", (CONTENT, MARKETING, BUSINESS), (CONTENT,)),
    # ----- Marketing Skills (Upgrade 3) -------------------------------------------------------------------
    _s("marketingskills", "product-marketing", (MARKETING, GROWTH, CONTENT), (MARKETING, CONTENT)),
    _s("marketingskills", "marketing-plan", (MARKETING, GROWTH, BUSINESS), (MARKETING,)),
    _s("marketingskills", "marketing-ideas", (MARKETING, GROWTH), (MARKETING,)),
    _s("marketingskills", "marketing-psychology", (MARKETING, GROWTH, SALES)),
    _s("marketingskills", "marketing-loops", (GROWTH, MARKETING)),
    _s("marketingskills", "marketing-council", (MARKETING, BUSINESS)),
    _s("marketingskills", "launch", (MARKETING, GROWTH, CONTENT), (MARKETING, CONTENT)),
    _s("marketingskills", "copywriting", (MARKETING, CONTENT, SALES, ONBOARD), (MARKETING, CONTENT, CREATION)),
    _s("marketingskills", "copy-editing", (MARKETING, CONTENT, DOCS), (MARKETING, CONTENT)),
    _s("marketingskills", "content-strategy", (CONTENT, MARKETING), (CONTENT,)),
    _s("marketingskills", "social", (MARKETING, CONTENT, COMMUNITY), (MARKETING, CONTENT)),
    _s("marketingskills", "emails", (MARKETING, ONBOARD, GROWTH), (MARKETING, ONBOARD)),
    _s("marketingskills", "sms", (MARKETING, GROWTH)),
    _s("marketingskills", "video", (CREATION, MARKETING, CONTENT), (CREATION, MARKETING, CONTENT)),
    _s("marketingskills", "image", (CREATION, MARKETING), (CREATION,)),
    _s("marketingskills", "ad-creative", (MARKETING, CREATION), (MARKETING, CREATION)),
    _s("marketingskills", "ads", (MARKETING, GROWTH, ANALYTICS), (MARKETING,)),
    _s("marketingskills", "seo-audit", (MARKETING, CONTENT, CODING), (MARKETING, CONTENT)),
    _s("marketingskills", "ai-seo", (MARKETING, CONTENT), (MARKETING, CONTENT)),
    _s("marketingskills", "programmatic-seo", (MARKETING, CONTENT, CODING)),
    _s("marketingskills", "schema", (MARKETING, CODING), (MARKETING,)),
    _s("marketingskills", "site-architecture", (MARKETING, CODING)),
    _s("marketingskills", "link-building", (MARKETING, PARTNER)),
    _s("marketingskills", "directory-submissions", (MARKETING, GROWTH)),
    _s("marketingskills", "cro", (GROWTH, MARKETING, ONBOARD), (GROWTH, MARKETING)),
    _s("marketingskills", "ab-testing", (GROWTH, ANALYTICS), (GROWTH, ANALYTICS)),
    _s("marketingskills", "signup", (GROWTH, ONBOARD), (GROWTH, ONBOARD)),
    _s("marketingskills", "onboarding", (ONBOARD, GROWTH), (ONBOARD,)),
    _s("marketingskills", "popups", (GROWTH, MARKETING)),
    _s("marketingskills", "paywalls", (GROWTH, FINANCE, BUSINESS)),
    _s("marketingskills", "pricing", (BUSINESS, GROWTH, FINANCE, SALES), (BUSINESS, GROWTH)),
    _s("marketingskills", "offers", (MARKETING, SALES, GROWTH)),
    _s("marketingskills", "churn-prevention", (GROWTH, SUPPORT, ANALYTICS), (GROWTH,)),
    _s("marketingskills", "referrals", (GROWTH, MARKETING)),
    _s("marketingskills", "lead-magnets", (MARKETING, SALES)),
    _s("marketingskills", "free-tools", (MARKETING, GROWTH)),
    _s("marketingskills", "analytics", (ANALYTICS, GROWTH), (ANALYTICS,)),
    _s("marketingskills", "attribution", (ANALYTICS, MARKETING)),
    _s("marketingskills", "conversion-tracking", (ANALYTICS, CODING), (ANALYTICS,)),
    _s("marketingskills", "customer-research", (RESEARCH, MARKETING, SALES), (RESEARCH, MARKETING)),
    _s("marketingskills", "competitors", (RESEARCH, MARKETING, BUSINESS), (RESEARCH, MARKETING)),
    _s("marketingskills", "competitor-profiling", (RESEARCH, MARKETING, SALES), (RESEARCH,)),
    _s("marketingskills", "reverse-engineer-marketing", (RESEARCH, MARKETING)),
    _s("marketingskills", "cold-email", (SALES,), (SALES,)),
    _s("marketingskills", "prospecting", (SALES, RESEARCH), (SALES,)),
    _s("marketingskills", "sales-enablement", (SALES, CONTENT), (SALES,)),
    _s("marketingskills", "revops", (SALES, FINANCE, ANALYTICS)),
    _s("marketingskills", "community-marketing", (COMMUNITY, MARKETING), (COMMUNITY,)),
    _s("marketingskills", "influencer-marketing", (MARKETING, PARTNER, LEGAL)),
    _s("marketingskills", "events", (COMMUNITY, MARKETING)),
    _s("marketingskills", "co-marketing", (PARTNER, MARKETING), (PARTNER,)),
    _s("marketingskills", "public-relations", (MARKETING, CONTENT)),
    _s("marketingskills", "aso", (MARKETING, GROWTH)),
    # ----- No AI Slop (Upgrade 4) -------------------------------------------------------------------------
    _s("no-ai-slop", "no-ai-slop", WRITERS, WRITERS + (CREATION,)),
    # ----- BRAG Slim (Upgrade 5) --------------------------------------------------------------------------
    _s("brag", "brag-slim", (CREATION, CONTENT, MARKETING), (CREATION, CONTENT, MARKETING)),
]

# Files inside a skill folder that are not guidance for the agent (the pack's own tests and evaluation sets).
_SKIP_PARTS = {"evals", "tests", "node_modules", ".git"}
MAX_SKILL_CHARS = 1_500_000


def packs_dir() -> Path:
    from app.core.config import settings

    return Path(str(getattr(settings, "SKILL_PACKS_DIR", "") or "/data/skill-packs"))


def skill_path(entry: Dict) -> str:
    """The skill's folder inside its pack's repository (and inside skill-packs/<pack>/)."""
    return f"{PACKS[entry['pack']]['root']}/{entry['skill']}"


def skill_id(entry: Dict) -> str:
    return f"{entry['pack']}/{entry['skill']}"


def skill_url(entry: Dict) -> str:
    pack = PACKS[entry["pack"]]
    return f"https://github.com/{pack['repo']}/tree/{pack['commit']}/{skill_path(entry)}"


def catalogue_entries() -> List[Dict]:
    """The skills as knowledge-library sources: stored text (MIT), read from the local pinned clone."""
    out = []
    for entry in SKILLS:
        pack = PACKS[entry["pack"]]
        out.append({
            "url": skill_url(entry), "title": f"{pack['title']}: {entry['skill']}", "publisher": pack["publisher"],
            "agents": list(entry["agents"]), "licence": "MIT",
            "licence_evidence": (f"https://github.com/{pack['repo']}/blob/{pack['commit']}/LICENSE "
                                 f"(MIT License, {pack['copyright']})"),
            "licence_class": LICENCE_STORE, "local_path": f"{entry['pack']}/{skill_path(entry)}"})
    return out


def read_skill(local_path: str, root: Optional[Path] = None) -> Tuple[Optional[str], str]:
    """(Markdown, reason): the skill's SKILL.md first, then every other Markdown file in its folder, each under
    its own file heading, so passages keep the file they came from. None and the reason when it cannot be read."""
    base = (root or packs_dir()).resolve()
    folder = (base / local_path).resolve()
    try:
        folder.relative_to(base)
    except ValueError:
        return None, "outside the skill packs folder"
    main = folder / "SKILL.md"
    if not main.is_file():
        return None, f"skill pack not installed ({local_path}); run scripts/skill-packs.sh"
    parts = [main.read_text(encoding="utf-8", errors="replace")]
    for path in sorted(folder.rglob("*.md")):
        if path == main or _SKIP_PARTS & set(path.relative_to(folder).parts):
            continue
        parts.append(f"\n\n# {path.relative_to(folder).as_posix()}\n\n"
                     + path.read_text(encoding="utf-8", errors="replace"))
    text = "".join(parts)
    return text[:MAX_SKILL_CHARS], ""


def sandbox_skills(specialist: str) -> List[str]:
    """The skills a mission specialist sees in the sandbox, as their folders inside skill-packs/
    ("pack/root/skill"); each is listed by name and description and loaded only when the specialist invokes it."""
    from app.core.config import settings

    if not getattr(settings, "SKILL_PACKS_ENABLED", True):
        return []
    return [f"{e['pack']}/{skill_path(e)}" for e in SKILLS if specialist in e["sandbox"]]


def installed() -> Dict[str, bool]:
    """Which packs are cloned at their pinned commit (a .jai-commit file written by scripts/skill-packs.sh)."""
    out = {}
    for name, pack in PACKS.items():
        marker = packs_dir() / name / ".jai-commit"
        try:
            out[name] = marker.read_text(encoding="utf-8").strip() == pack["commit"]
        except OSError:
            out[name] = False
    return out
