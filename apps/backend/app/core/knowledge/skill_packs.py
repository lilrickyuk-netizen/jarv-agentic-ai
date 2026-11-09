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
    "ecc": {"repo": "affaan-m/ECC", "commit": "d2ef2680594f9a17526a6e1a2e18b3d242c5d17b", "root": "skills",
            "title": "ECC", "publisher": "Affaan Mustafa (affaan-m/ECC)",
            "copyright": "Copyright (c) 2026 Affaan Mustafa"},
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
SECURITY_ROLE = "security"
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
    # ----- ECC (everything-claude-code): stack patterns, production checks, growth, video ---------------------
    # Only the skills; ECC's own agents, hooks and orchestration are left out (JAI's 31 agents and orchestrator
    # already do that work). Where it overlaps Superpowers, Superpowers stays the sandbox's procedure.
    _s("ecc", "fastapi-patterns", (CODING, DEBUG, QA), (CODING, DEBUG)),
    _s("ecc", "python-testing", (CODING, QA, DEBUG), (CODING, QA)),
    _s("ecc", "nextjs-turbopack", (CODING, DEBUG), (CODING, DEBUG)),
    _s("ecc", "react-patterns", (CODING,), (CODING,)),
    _s("ecc", "typescript-patterns", (CODING, QA), (CODING,)),
    _s("ecc", "frontend-patterns", (CODING, CREATION), (CODING,)),
    _s("ecc", "backend-patterns", (CODING, INFRA), (CODING,)),
    _s("ecc", "api-design", (CODING, DOCS), (CODING,)),
    _s("ecc", "postgres-patterns", (CODING, INFRA, DEBUG), (CODING, INFRA)),
    _s("ecc", "redis-patterns", (CODING, INFRA)),
    _s("ecc", "database-migrations", (CODING, DEVOPS, INFRA), (CODING, DEVOPS)),
    _s("ecc", "docker-patterns", (DEVOPS, INFRA, CODING), (DEVOPS, INFRA, ENVIRONMENT)),
    _s("ecc", "kubernetes-patterns", (INFRA, DEVOPS)),
    _s("ecc", "deployment-patterns", (DEVOPS, INFRA), (DEVOPS, INFRA)),
    _s("ecc", "coding-standards", (CODING, QA, VERIFY)),
    _s("ecc", "error-handling", (CODING, DEBUG), (CODING, DEBUG)),
    _s("ecc", "e2e-testing", (QA, CODING), (QA,)),
    _s("ecc", "browser-qa", (QA, VERIFY), (QA, VERIFY)),
    _s("ecc", "ai-regression-testing", (QA, VERIFY)),
    _s("ecc", "verification-loop", (VERIFY, QA)),
    _s("ecc", "delivery-gate", (VERIFY, DEVOPS), (VERIFY,)),
    _s("ecc", "production-audit", (VERIFY, SECURITY_ROLE, DEVOPS), (VERIFY, SECURITY_ROLE)),
    _s("ecc", "canary-watch", (DEVOPS, "monitoring", HEAL)),
    _s("ecc", "security-review", (SECURITY_ROLE, CODING, VERIFY), (SECURITY_ROLE,)),
    _s("ecc", "security-scan", (SECURITY_ROLE,), (SECURITY_ROLE,)),
    _s("ecc", "agent-security-hardening", (SECURITY_ROLE, EVOLVE)),
    _s("ecc", "architecture-decision-records", (CODING, DOCS, ORCH), (CODING, DOCS)),
    _s("ecc", "codebase-onboarding", (CODING, DOCS, RESEARCH), (CODING, DOCS)),
    _s("ecc", "repo-scan", (CODING, SECURITY_ROLE, RESEARCH)),
    _s("ecc", "git-workflow", (CODING, DEVOPS)),
    _s("ecc", "documentation-lookup", (CODING, RESEARCH, DOCS)),
    _s("ecc", "context-budget", (ORCH, SWARM, EVOLVE)),
    _s("ecc", "cost-aware-llm-pipeline", (ORCH, FINANCE, EVOLVE)),
    _s("ecc", "prompt-caching-strategy", (ORCH, EVOLVE)),
    _s("ecc", "deep-research", (RESEARCH,), (RESEARCH,)),
    _s("ecc", "market-research", (RESEARCH, BUSINESS, MARKETING), (RESEARCH, BUSINESS)),
    _s("ecc", "search-first", (RESEARCH, CODING)),
    _s("ecc", "competitive-report-structure", (RESEARCH, BUSINESS)),
    _s("ecc", "product-lens", (BUSINESS, MARKETING, RESEARCH)),
    _s("ecc", "seo", (MARKETING, CONTENT), (MARKETING, CONTENT)),
    _s("ecc", "marketing-campaign", (MARKETING, GROWTH), (MARKETING,)),
    _s("ecc", "content-engine", (CONTENT, MARKETING), (CONTENT,)),
    _s("ecc", "article-writing", (CONTENT, DOCS), (CONTENT,)),
    _s("ecc", "brand-voice", (MARKETING, CONTENT, CREATION)),
    _s("ecc", "crosspost", (CONTENT, COMMUNITY, MARKETING)),
    _s("ecc", "social-publisher", (CONTENT, MARKETING)),
    _s("ecc", "lead-intelligence", (SALES, RESEARCH), (SALES,)),
    _s("ecc", "email-ops", (SALES, SUPPORT, MARKETING)),
    _s("ecc", "investor-materials", (BUSINESS, FINANCE, PARTNER), (BUSINESS,)),
    _s("ecc", "investor-outreach", (BUSINESS, PARTNER, SALES), (BUSINESS, PARTNER)),
    _s("ecc", "customer-billing-ops", (FINANCE, SUPPORT)),
    _s("ecc", "finance-billing-ops", (FINANCE, BUSINESS)),
    _s("ecc", "dashboard-builder", (ANALYTICS, CODING), (ANALYTICS,)),
    _s("ecc", "remotion-video-creation", (CREATION, MARKETING), (CREATION,)),
    _s("ecc", "manim-video", (CREATION, CONTENT), (CREATION,)),
    _s("ecc", "video-editing", (CREATION, CONTENT), (CREATION,)),
    _s("ecc", "ui-demo", (CREATION, MARKETING, CODING), (CREATION,)),
    _s("ecc", "frontend-design-direction", (CREATION, CODING)),
    _s("ecc", "make-interfaces-feel-better", (CODING, CREATION, QA), (CODING,)),
    _s("ecc", "accessibility", (CODING, QA, CREATION), (CODING, QA)),
    # ----- BRAG Slim (Upgrade 5) --------------------------------------------------------------------------
    _s("brag", "brag-slim", (CREATION, CONTENT, MARKETING), (CREATION, CONTENT, MARKETING)),
    # The full BRAG pipeline as well (HyperFrames, its bundled music and sound effects): on Opus 5.5 it hands over to
    # Slim itself, and any other model follows its own rule into the full pipeline instead of a weaker Slim run.
    _s("brag", "brag", (CREATION, CONTENT, MARKETING), (CREATION, CONTENT, MARKETING)),
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


def blocked(root: Optional[Path] = None) -> set:
    """Skills AgentShield flagged (scripts/scan-skill-packs.sh writes each pack's .jai-blocked): never loaded, as
    "pack/root/skill"."""
    base = root or packs_dir()
    out = set()
    for name in PACKS:
        try:
            lines = (base / name / ".jai-blocked").read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        out |= {f"{name}/{line.strip().strip('/')}" for line in lines if line.strip()}
    return out


def scan_status(root: Optional[Path] = None) -> Dict[str, str]:
    """Each pack's AgentShield verdict: its grade and how many skills were blocked, or that it was not scanned."""
    import json

    base = root or packs_dir()
    out = {}
    for name in PACKS:
        try:
            report = json.loads((base / name / ".agentshield.json").read_text(encoding="utf-8", errors="replace"))
            grade = (report.get("score") or {}).get("grade", "?")
            out[name] = f"grade {grade}"
        except (OSError, ValueError):
            out[name] = "not scanned"
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
    if local_path.strip("/") in blocked(base):
        return None, "blocked: AgentShield found a critical risk in this skill, so JAI does not use it"
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
    refused = blocked()
    # The one builder takes on every role, so it is offered every skill (listed by name, loaded only when used).
    mine = [e for e in SKILLS if e["sandbox"] and (specialist == "builder" or specialist in e["sandbox"])]
    return list(dict.fromkeys(path for path in (f"{e['pack']}/{skill_path(e)}" for e in mine) if path not in refused))


def named_skill(text: str) -> Optional[Dict]:
    """The one skill a brief asks JAI to use, named just before the word "skill" ("with your BRAG Slim skill",
    "using its brag skill", "the test-driven-development skill"), or None. Letters only, so "BRAG Slim" and
    "brag-slim" are the same; a pack's name stands for its skill when the pack has only one. A brief that names
    several skills is planned as usual. Without the word "skill": a distinctive pack named on its own ("using BRAG").
    Work a skill could do is never sent to it unasked: on 9 November BRAG took over an hour and many times the cost
    to make a video ad no better than the one builder made in minutes for about four pounds."""
    import re

    def letters(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (value or "").lower())

    refused = blocked()  # a skill AgentShield blocked is never handed to a specialist
    usable = [e for e in SKILLS if e["sandbox"] and f"{e['pack']}/{skill_path(e)}" not in refused]
    names: Dict[str, Dict] = {letters(e["skill"]): e for e in usable}
    for pack, info in PACKS.items():
        only = [e for e in usable if e["pack"] == pack]
        if len(only) == 1:
            names.setdefault(letters(pack), only[0])
            names.setdefault(letters(info.get("title", "")), only[0])
    found = {}
    for match in re.finditer(r"((?:[\w-]+\s+){1,4})skills?\b", text or "", re.I):
        words = match.group(1).split()
        for n in range(1, len(words) + 1):  # the words just before "skill": the last one, the last two, ...
            entry = names.get(letters("".join(words[-n:])))
            if entry is not None:
                found[entry["skill"]] = entry
                break
    if found or re.search(r"\bskills?\b", text or "", re.I):
        return next(iter(found.values())) if len(found) == 1 else None
    # "Using BRAG, make ...", without the word "skill".
    for match in re.finditer(r"\b(?:using|with|use|via)\s+(?:your\s+|its\s+|the\s+)?([\w-]+(?:\s+[\w-]+)?)", text or "",
                             re.I):
        words = match.group(1).split()
        for n in (len(words), 1):
            entry = names.get(letters("".join(words[:n])))
            if entry is not None and entry["pack"] in _NAMED_ALONE:
                return entry
    return None


# Packs whose name is distinctive enough to stand alone ("using BRAG"); an everyday skill name ("with
# accessibility in mind") is not taken as a request to run that skill.
_NAMED_ALONE = frozenset({"brag"})


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
