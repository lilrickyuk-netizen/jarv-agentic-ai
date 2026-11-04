"""
JAI Backend - Missions run by a team

A mission is not one agent working through a long list. It runs the way JAI is designed to run:

1. The Orchestrator reads the mission, its numbered requirements, the workspace and the specification, and plans
   work packages: what each one delivers, which specialist does it, which files it owns, what it needs first and
   how it is checked.
2. The Swarm Manager spawns one sub-agent per package, a specialist (Software Engineer, QA Engineer, DevOps
   Engineer, Technical Writer, Marketing Lead...) with that role's working standards. Sub-agents run in parallel
   in dependency waves, each with its own tool runtime and database session, at no more than the lead's authority
   and with no more than the lead's tools (deleting and pushing stay with the lead). A sub-agent writes only inside
   the paths its package owns, so parallel work never collides; commands, installs and git run one at a time on
   the machine. Every sub-agent, task and tool call is recorded on the Swarm page with its parent agent, and each
   sub-agent dissolves when its package ends.
3. The integration lead then runs the project's real install, build and tests across everything the team did,
   fixes what breaks where the packages meet, finishes anything left open, and hands the whole mission to the
   independent Verifier, which accepts it only on evidence for every requirement.

A mission whose plan is a single package (one small change) runs as one agent, as before. A later round of the
same mission plans again, for the requirements still open.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from app.core.command.agent_executor import _EDITS, AgentExecutor
from app.core.command.metrics import MeteredRouter, Usage
from app.core.command.requirements import render as render_requirements
from app.core.config import settings
from app.core.providers import CompletionRequest, Message, get_router

logger = logging.getLogger(__name__)

# The lead keeps the actions that pause for Richard; a specialist asks the lead (in its report) instead.
LEAD_ONLY_TOOLS = ("delete_file_with_boundary", "git_push_with_boundary")
# One machine: commands, installs and git run one at a time, whichever specialist asks.
MACHINE_TOOLS_PREFIXES = ("run_", "install_", "git_")
MACHINE_TOOLS = ("check_installed", "detect_commands", "run_prompt_checks")
# One GPU and one browser: media and browsing run one at a time too.
SHARED_SERVICE_TOOLS = ("generate_image", "make_voiceover", "make_video", "use_browser")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".turbo", "coverage",
             ".serena", ".pytest_cache", ".mypy_cache", ".ruff_cache", "target", ".gradle", ".idea", ".vscode"}
TREE_ENTRIES = 400
PACKAGE_STEPS = 8
SUB_AGENT_TIMEOUT_SECONDS = 4 * 3600

# The specialists a mission can call on, with each role's working standard. A sub-agent is briefed with its role's
# standard, so it works the way a senior person in that role works.
SPECIALISTS: Dict[str, Dict[str, str]] = {
    "coding_agent": {
        "title": "Senior Software Engineer",
        "standard": (
            "Read the code around a change before making it and follow the project's own structure, naming, "
            "framework idioms and version pins. Write complete, production-grade code: real implementations, input "
            "validation, error handling, types, no dead code. Keep each change small enough to review. Add or "
            "update the tests that prove the behaviour, run the type check, linter and the tests for what you "
            "changed, and fix every failure before you call finish. Never weaken a test to make it pass."),
    },
    "debugging_agent": {
        "title": "Debugging Specialist",
        "standard": (
            "Reproduce the failure first with the exact command, then read the whole error and the code it points "
            "to. Form one hypothesis at a time and test it with the smallest experiment. Fix the cause, not the "
            "symptom, then rerun the original failing command and the surrounding tests to show it is fixed and "
            "nothing else broke. Search the exact error message for known fixes before guessing."),
    },
    "qa": {
        "title": "QA Engineer",
        "standard": (
            "Work from the requirements: every requirement you own gets a test that would fail if it were not met, "
            "covering the normal path, the edges and the errors. Use the project's test framework and conventions, "
            "keep tests deterministic and independent of the network and of real money. Run the whole suite you "
            "touched, report the exact command and counts, and fix flaky or failing tests at their cause."),
    },
    "devops": {
        "title": "DevOps Engineer",
        "standard": (
            "Make the project build and run the same way everywhere: pinned versions, a lockfile, a reproducible "
            "install, Dockerfiles that build small images as a non-root user, compose files with health checks, CI "
            "that runs install, lint, type check, tests and build. Keep secrets out of files (environment variables "
            "with a documented example file). Prove each piece with the real command: the build, the image build, "
            "a one-off run of the checks. Deploys and releases wait for Richard."),
    },
    "infrastructure": {
        "title": "Infrastructure Engineer",
        "standard": (
            "Describe infrastructure as code (Terraform, Helm, compose) with pinned providers and charts, variables "
            "for every environment difference, least-privilege access, backups and restores, TLS, DNS and resource "
            "limits written down. Validate everything you write with the tool's own check (terraform validate and "
            "fmt, helm lint and template, compose config). Nothing is applied to a real account without Richard."),
    },
    "security": {
        "title": "Security Engineer",
        "standard": (
            "Look for the real risks first: secrets in files or history, injection, broken authentication and "
            "authorisation, unsafe deserialisation, missing input validation, vulnerable dependencies (check_cve), "
            "permissive CORS and headers. Fix what you find in the code, add a test that proves the fix, and record "
            "anything that needs Richard's decision. Never print or copy a secret value."),
    },
    "documentation": {
        "title": "Technical Writer",
        "standard": (
            "Write for the reader who has to act on it: what it is, how to install, configure, run, test and "
            "deploy it, with commands that you have run and that work, in the project's existing documentation "
            "structure. Keep the documents consistent with the code and the specification, name versions exactly, "
            "and remove instructions that are no longer true."),
    },
    "research": {
        "title": "Research Analyst",
        "standard": (
            "Answer the question from current, primary sources (official documentation, release notes, standards, "
            "the market's own figures) found with web_search, research_web and fetch_url. Cite every claim, say how "
            "recent each source is, separate fact from estimate, and write the findings into the workspace where "
            "the rest of the team can use them."),
    },
    "content": {
        "title": "Content Lead",
        "standard": (
            "Write content with one audience and one purpose per piece, in the product's voice, accurate to what "
            "the product really does. Structure it for how it will be read (web page, post, email, script), give "
            "each piece a clear call to action, and keep a content plan file listing every piece and where it goes. "
            "Images and video come from JAI's own tools with their licences recorded. Nothing is published from "
            "Richard's accounts: posts are drafts for him."),
    },
    "marketing": {
        "title": "Marketing Lead",
        "standard": (
            "Start from the customer: who they are, the problem, the alternatives, and why this product wins. Write "
            "the positioning, messaging and the launch plan (channels, sequence, budget needed, the metrics that "
            "show it works) into the workspace, and build the assets the plan needs (landing page copy, emails, "
            "post drafts). Claims must be true and checkable. Spending and publishing wait for Richard."),
    },
    "growth": {
        "title": "Growth Lead",
        "standard": (
            "Define the funnel and its metrics, instrument the product so each step is measured, and design "
            "experiments with a hypothesis, the change, the metric and the decision rule. Implement the tracking "
            "and the experiment code properly, with consent and privacy respected, and test it."),
    },
    "onboarding": {
        "title": "Onboarding Designer",
        "standard": (
            "Design the first-run experience so a new user reaches the product's core value quickly: sign-up, "
            "first setup, the first success, and the help at each step. Implement the flows and their copy in the "
            "product, with empty states and errors handled, and test them as a new user would."),
    },
    "customer_support": {
        "title": "Customer Support Lead",
        "standard": (
            "Write the help centre, FAQs, support macros and escalation rules from what the product actually does, "
            "with clear steps a customer can follow. Set up the support channel's configuration in the workspace "
            "and make sure every answer matches the current product."),
    },
    "sales": {
        "title": "Sales Lead",
        "standard": (
            "Define the ideal customer, the offer and pricing tiers, the sales process and its stages, and write the "
            "materials each stage needs (one-pager, demo script, objection handling, proposal template). Make "
            "pricing and checkout in the product match the offer exactly. Binding commitments wait for Richard."),
    },
    "business": {
        "title": "Business Analyst",
        "standard": (
            "Write the business case with real numbers and their sources: market, costs, pricing, unit economics, "
            "break-even and the risks. Keep the operating plan and the KPIs that measure it in the workspace, "
            "consistent with the product and the marketing plan."),
    },
    "finance": {
        "title": "Finance and Metrics Analyst",
        "standard": (
            "Build the financial model and the metrics from real inputs: prices, costs, volumes, with every "
            "assumption labelled. Check the arithmetic by running it, and keep revenue tracking in the product "
            "consistent with the model. Payments and bank details wait for Richard."),
    },
    "legal": {
        "title": "Legal and Compliance Drafter",
        "standard": (
            "Draft the documents the product needs (terms, privacy policy, cookie notice, data processing, "
            "licences of every dependency and asset) for the jurisdictions it serves, matched to what the product "
            "actually collects and does, and mark each as a draft for Richard to have reviewed. Signing and binding "
            "commitments wait for him."),
    },
    "analytics": {
        "title": "Analytics Engineer",
        "standard": (
            "Define every metric precisely (event, property, calculation), implement the tracking and the queries "
            "or dashboards that compute them, and test them with real or labelled sample data. Respect consent and "
            "privacy, and document the metrics where the team can find them."),
    },
    "creation": {
        "title": "Product Designer",
        "standard": (
            "Design interfaces that are clear, accessible (contrast, keyboard, labels) and consistent with the "
            "product's design system: layout, type, colour, spacing and states (loading, empty, error). Implement "
            "the design in the product's own components, generate the images and media it needs with JAI's tools, "
            "with licences recorded, and check the result in the browser at desktop and phone widths."),
    },
    "community": {
        "title": "Community Manager",
        "standard": (
            "Set up the community's home, its guidelines and moderation rules, the welcome and engagement plan, "
            "and the first posts as drafts. Everything public from Richard's accounts waits for him."),
    },
    "partnerships": {
        "title": "Partnerships Lead",
        "standard": (
            "Identify the partners that bring customers or capability, with the evidence, write the proposal and "
            "the integration plan, and build any integration the product needs properly. Agreements wait for "
            "Richard."),
    },
}

PLAN_TOOL = {
    "name": "plan_work",
    "description": "Record the mission's work packages for JAI's specialist agents.",
    "input_schema": {
        "type": "object",
        "properties": {
            "approach": {"type": "string", "description": "Two or three sentences: how the team will do it"},
            "packages": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string", "description": "P1, P2, ..."},
                "title": {"type": "string"},
                "specialist": {"type": "string", "enum": sorted(SPECIALISTS)},
                "goal": {"type": "string", "description": "What this package delivers, concretely"},
                "owns": {"type": "array", "items": {"type": "string"},
                         "description": "The files and folders only this package writes, relative to the "
                                        "workspace root (a folder ends with /)"},
                "depends_on": {"type": "array", "items": {"type": "string"},
                               "description": "Packages that must finish first"},
                "requirements": {"type": "array", "items": {"type": "string"},
                                 "description": "Ids of the mission requirements this package delivers"},
                "done_when": {"type": "string", "description": "The check that shows it is done (a command and "
                                                               "its expected result, a file and what it holds)"},
            }, "required": ["id", "title", "specialist", "goal", "owns", "done_when"]}},
        },
        "required": ["approach", "packages"],
    },
}

_PLANNER = (
    "You are JAI's Orchestrator, the lead of a team of specialist agents who work on the same workspace at the "
    "same time. Plan the mission as work packages, one specialist each, so the team delivers it completely and "
    "fast. Rules: every open requirement goes to exactly one package; each package owns the files and folders only "
    "it writes (relative to the workspace root, a folder ending in /), and packages that run at the same time own "
    "different paths; put a package in depends_on only when it truly needs that package's output first; done_when "
    "is a real check. Split wherever the work has separate parts (backend and frontend, separate services or "
    "modules, code and its tests, infrastructure and CI, documentation, marketing and content, legal), so parts run "
    "in parallel; plan a single package only for one small change. Use up to {limit} packages. Do not plan the "
    "final whole-project build and test: the integration lead does that after the team. Call plan_work once.")


@dataclass
class Package:
    id: str
    title: str
    specialist: str
    goal: str
    owns: List[str]
    depends_on: List[str]
    requirements: List[str]
    done_when: str
    status: str = "planned"  # planned, working, finished, stopped
    step: int = 0
    steps: int = 0
    doing: Optional[str] = None
    summary: str = ""
    success: bool = False
    tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    sub_agent_id: Optional[UUID] = None
    sub_task_id: Optional[UUID] = None
    started_at: Optional[datetime] = None
    tools: List[str] = field(default_factory=list)

    @property
    def role(self) -> str:
        return SPECIALISTS[self.specialist]["title"]

    def card(self) -> Dict[str, Any]:
        return {"id": self.id, "title": self.title, "specialist": self.specialist, "role": self.role,
                "status": self.status, "step": self.step, "steps": self.steps, "owns": self.owns,
                "depends_on": self.depends_on, "requirements": self.requirements,
                "doing_now": self.doing, "summary": self.summary[:400], "success": self.success,
                "tool_calls": self.calls, "cost_usd": round(self.cost_usd, 4)}


def _clean_path(value: Any) -> Optional[str]:
    text = str(value or "").strip().strip("`'\"").replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = text.lstrip("/")
    if not text or text in (".",) or ".." in text.split("/") or ":" in text[:3]:
        return None
    return text


def parse_plan(arguments: Dict[str, Any], open_ids: List[str], limit: int) -> Dict[str, Any]:
    """The planner's packages, cleaned: known specialists, unique ids, real dependencies, known requirements,
    paths inside the workspace."""
    packages: List[Package] = []
    seen = set()
    raw = arguments.get("packages") if isinstance(arguments, dict) else None
    for i, item in enumerate(raw if isinstance(raw, list) else [], start=1):
        if not isinstance(item, dict) or not str(item.get("goal") or item.get("title") or "").strip():
            continue
        pid = re.sub(r"[^A-Za-z0-9]", "", str(item.get("id") or "")).upper()[:8] or f"P{i}"
        if pid in seen:
            pid = f"P{i}"
        if pid in seen:
            continue
        seen.add(pid)
        specialist = str(item.get("specialist") or "").strip().lower()
        owns = [p for p in (_clean_path(v) for v in (item.get("owns") or [])) if p]
        packages.append(Package(
            id=pid, title=" ".join(str(item.get("title") or item.get("goal")).split())[:160],
            specialist=specialist if specialist in SPECIALISTS else "coding_agent",
            goal=" ".join(str(item.get("goal") or item.get("title")).split())[:1500],
            owns=list(dict.fromkeys(owns))[:20],
            depends_on=[str(d).upper() for d in (item.get("depends_on") or []) if str(d).strip()],
            requirements=[str(r).upper() for r in (item.get("requirements") or []) if str(r).upper() in open_ids],
            done_when=" ".join(str(item.get("done_when") or "").split())[:800]))
        if len(packages) >= limit:
            break
    ids = {p.id for p in packages}
    for p in packages:
        p.depends_on = [d for d in dict.fromkeys(p.depends_on) if d in ids and d != p.id]
    claimed = set()
    for p in packages:  # every requirement in exactly one package
        p.requirements = [r for r in dict.fromkeys(p.requirements) if r not in claimed]
        claimed.update(p.requirements)
    return {"approach": " ".join(str((arguments or {}).get("approach") or "").split())[:800],
            "packages": packages, "unassigned": [r for r in open_ids if r not in claimed]}


def _overlaps(a: List[str], b: List[str]) -> bool:
    for x in a:
        for y in b:
            xs, ys = x.rstrip("/"), y.rstrip("/")
            if xs == ys or xs.startswith(ys + "/") or ys.startswith(xs + "/"):
                return True
    return False


def next_wave(pending: List[Package], finished: Dict[str, Package], parallel: int) -> List[Package]:
    """The packages to run now: their dependencies have finished, they own paths of their own and none of them
    writes where another one in the wave writes. A package with no owned paths runs alone."""
    ready = [p for p in pending if all(d in finished for d in p.depends_on)]
    if not ready:  # a dependency cycle: the earliest planned package goes first
        ready = pending[:1]
    wave: List[Package] = []
    for p in ready:
        if len(wave) >= parallel:
            break
        if not p.owns:
            if not wave:
                return [p]
            continue
        if any(not q.owns or _overlaps(p.owns, q.owns) for q in wave):
            continue
        wave.append(p)
    return wave or ready[:1]


def workspace_tree(container_root: Optional[Path], limit: int = TREE_ENTRIES) -> str:
    """The workspace's folders and files, three levels deep, without dependency and build folders."""
    if container_root is None or not container_root.is_dir():
        return ""
    lines: List[str] = []
    root = container_root

    def walk(folder: Path, depth: int) -> None:
        try:
            entries = sorted(folder.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return
        for entry in entries:
            if len(lines) >= limit:
                return
            if entry.name in SKIP_DIRS or (entry.name.startswith(".") and entry.name not in (".github", ".env.example")):
                continue
            rel = entry.relative_to(root).as_posix()
            lines.append(rel + ("/" if entry.is_dir() else ""))
            if entry.is_dir() and depth < 3:
                walk(entry, depth + 1)

    walk(root, 1)
    if len(lines) >= limit:
        lines.append(f"... (more than {limit} entries)")
    return "\n".join(lines)


def absorb(target: Usage, source: Usage, label: str) -> None:
    """Add a specialist's model use to the mission's figures."""
    for key, value in source.totals.items():
        target.totals[key] = target.totals.get(key, 0) + value
    target.calls += source.calls
    target.cost_usd += source.cost_usd
    target.priced = target.priced and source.priced
    for role, totals in source.by_role.items():
        into = target.by_role.setdefault(f"{label} {role}", {k: 0 for k in totals})
        for key, value in totals.items():
            into[key] = into.get(key, 0) + value


class SpecialistExecutor(AgentExecutor):
    """One sub-agent: the mission's tool loop, briefed as a specialist, writing only where its package owns, with
    the machine and shared services taken one at a time, and every call reported to the team."""

    def __init__(self, runtime, model: str, workspace_root: Optional[str], *, team: "MissionTeam",
                 package: Package):
        super().__init__(runtime, model, workspace_root)
        self.team = team
        self.package = package
        self._seen = 0

    async def _prepare_tools(self) -> List[Dict[str, Any]]:
        tools = await super()._prepare_tools()
        return [t for t in tools if t.get("name") not in LEAD_ONLY_TOOLS]

    def _scope_refusal(self, name: str, args: Dict[str, Any]) -> Optional[str]:
        if name not in _EDITS or self.toolbox is None:
            return None
        owned = self.package.owns
        if not owned:
            return None
        targets = [args.get(k) for k in ("path", "destination", "source" if name == "move_file" else "")
                   if k and args.get(k)]
        bounds = []
        for path in owned:
            host, refused = self.toolbox._resolve_host(path)
            if host and not refused:
                bounds.append(Path(os.path.normpath(str(self.toolbox._to_container(host)))))
        for target in targets:
            host, refused = self.toolbox._resolve_host(str(target))
            if refused or not host:
                return None  # the toolbox refuses it with its own reason
            where = Path(os.path.normpath(str(self.toolbox._to_container(host))))
            if not any(where == b or b in where.parents for b in bounds):
                return (f"Not written: {target} is outside your work package. You ({self.package.role}, "
                        f"{self.package.id}) write only in {', '.join(owned)}; another specialist owns the rest. "
                        "Read what you need, do your part inside your paths, and put anything another package must "
                        "change in your finish summary for the integration lead.")
        return None

    async def _tool_step(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        # The lock is taken before the step's watchdog starts: waiting for another specialist's build is not a
        # hung step.
        if name in LEAD_ONLY_TOOLS:
            out: Dict[str, Any] = {"success": False, "blocked": True, "reason": (
                f"{name} stays with the mission's lead. Say in your finish summary what should be deleted or "
                "pushed and why; the integration lead asks Richard.")}
        else:
            refusal = self._scope_refusal(name, args)
            if refusal:
                out = {"success": False, "blocked": True, "outside_package": True, "reason": refusal}
            else:
                lock = self.team.lock_for(name)
                if lock is None:
                    out = await super()._tool_step(name, args)
                else:
                    async with lock:
                        out = await super()._tool_step(name, args)
        await self._report(name, args, out)
        return out

    async def _report(self, name: str, args: Dict[str, Any], out: Any) -> None:
        """This sub-agent's new tool calls: onto the mission's record (with the specialist's name), its own
        sub-agent log, and its records committed so the rest of JAI sees them now."""
        fresh = self.runtime.calls[self._seen:]
        self._seen = len(self.runtime.calls)
        for call in fresh:
            call["agent"] = self.package.specialist
            call["package"] = self.package.id
        self.package.calls += 1
        if name not in self.package.tools:
            self.package.tools.append(name)
        await self.team.adopt(fresh)
        try:
            await self.runtime.db.commit()
        except Exception as exc:  # noqa: BLE001 - the work is on disk; a record that failed is logged
            logger.warning(f"sub-agent {self.package.id} records not saved: {exc}")
            await self.runtime.db.rollback()
        ok = isinstance(out, dict) and out.get("success") is not False and not out.get("error")
        why = "" if ok or not isinstance(out, dict) else str(out.get("reason") or out.get("error") or "")[:300]
        target = str(args.get("path") or args.get("command") or args.get("query") or args.get("url") or "")[:200]
        await self.team.log(self.package, "info" if ok else "warning", "tool",
                            f"{name} {target}".strip() + (f" -> {why}" if why else ""),
                            {"tool": name, "target": target, "ok": ok})

    async def _progress(self, phase: str, continuation: int, budget: int,
                        check: Optional[Dict[str, Any]] = None) -> None:
        self.package.step, self.package.steps = self.iterations, budget
        said = getattr(self, "_agent_said", None)
        if said:
            self.package.doing = said[:300]
        await self.team.save_progress()

    def _listed(self) -> bool:
        return False  # the mission's report is written once, from the whole team's evidence

    async def _graph_requirements(self) -> None:
        return None  # the lead records the mission's requirements in the graph


class LeadExecutor(AgentExecutor):
    """The mission's lead (the Orchestrator): plans, then integrates and hands over to the Verifier. Its progress
    record carries the team."""

    def __init__(self, runtime, model: str, workspace_root: Optional[str], *, team: "MissionTeam"):
        super().__init__(runtime, model, workspace_root)
        self.team = team

    def _progress_extra(self) -> Dict[str, Any]:
        return self.team.progress_extra()


class MissionTeam:
    """Runs one round of a mission with the orchestrator, specialist sub-agents and the integration lead. Its
    ``run`` takes and returns what ``AgentExecutor.run`` does, so a mission and its continuation rounds use it the
    same way."""

    def __init__(self, runtime, model: str, workspace_root: Optional[str], *,
                 session_factory: Optional[Callable] = None):
        self.runtime = runtime
        self.model = model
        self.workspace_root = workspace_root
        self.lead = LeadExecutor(runtime, model, workspace_root, team=self)
        self.packages: List[Package] = []
        self.approach = ""
        self.parallel = 1
        self.swarm_run_id: Optional[UUID] = None
        self.lead_agent_id: Optional[UUID] = None
        self.phase = "planning"
        self.round_no = 1
        self._session_factory = session_factory
        self._machine = asyncio.Lock()
        self._services = asyncio.Lock()
        self._started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ----- shared state ------------------------------------------------------

    def sessions(self):
        if self._session_factory is not None:
            return self._session_factory()
        from app.core.database import AsyncSessionLocal

        return AsyncSessionLocal()

    def lock_for(self, name: str) -> Optional[asyncio.Lock]:
        if name in SHARED_SERVICE_TOOLS:
            return self._services
        if name in MACHINE_TOOLS or name.startswith(MACHINE_TOOLS_PREFIXES):
            return self._machine
        return None

    async def adopt(self, calls: List[Dict[str, Any]]) -> None:
        self.runtime.calls.extend(calls)

    def progress_extra(self) -> Dict[str, Any]:
        if not self.packages:
            return {}
        return {"team": {"approach": self.approach, "parallel": self.parallel, "phase": self.phase,
                         "swarm_run_id": str(self.swarm_run_id) if self.swarm_run_id else None,
                         "packages": [p.card() for p in self.packages]}}

    async def save_progress(self) -> None:
        from app.core.command import progress

        working = [p for p in self.packages if p.status == "working"]
        done = sum(1 for p in self.packages if p.status in ("finished", "stopped"))
        phase = (f"team: {done} of {len(self.packages)} work packages done"
                 + (f"; working now: " + ", ".join(f"{p.id} {p.role}" for p in working) if working else ""))
        record = progress.snapshot(
            self.runtime.calls, self.lead.requirements, round_no=self.round_no,
            step=sum(p.step for p in self.packages), step_budget=sum(p.steps for p in self.packages) or 1,
            phase=phase, usage=self.lead.usage.summary(), started_at=self._started_at, root=self.workspace_root,
            agent_said=next((p.doing for p in reversed(working) if p.doing), None))
        record.update(self.progress_extra())
        try:
            await progress.save(self.runtime.task_id, record)
        except Exception as exc:  # noqa: BLE001 - progress is a view; the work goes on
            logger.info(f"team progress not saved: {exc}")

    # ----- the swarm's records -----------------------------------------------

    async def _book(self, work) -> Any:
        """One piece of swarm bookkeeping in its own short transaction; a failure is logged, never fatal."""
        try:
            async with self.sessions() as db:
                if getattr(getattr(db.bind, "dialect", None), "name", "") == "postgresql":
                    from sqlalchemy import text

                    await db.execute(text("SET LOCAL lock_timeout = '10s'"))
                value = await work(db)
                await db.commit()
                return value
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"swarm record not written: {exc}")
            return None

    async def _open_swarm(self, mission: str) -> None:
        from sqlalchemy import select

        from app.models.agent import Agent
        from app.models.swarm import SubAgent, SubAgentTask, SwarmRun

        workspace_id = self.runtime.workspace_id

        async def work(db):
            lead = (await db.execute(select(Agent).where(Agent.name == "orchestrator",
                                                         Agent.workspace_id == workspace_id))).scalars().first()
            if lead is None:
                lead = Agent(name="orchestrator", agent_type="core", workspace_id=workspace_id,
                             description="Core orchestration agent (owns mission sessions)", is_active=True,
                             authority_level=9, allowed_tools=[], blocked_tools=[])
                db.add(lead)
                await db.flush()
            now = datetime.now(timezone.utc)
            swarm = SwarmRun(workspace_id=workspace_id, parent_agent_id=lead.id, swarm_type="mission_team",
                             swarm_name=f"Mission team: {mission[:200]}", objective=mission[:8000],
                             status="running", max_subagents=len(self.packages),
                             actual_subagents=len(self.packages), coordination_strategy="dependency_waves",
                             started_at=now,
                             meta_data={"task_id": str(self.runtime.task_id), "approach": self.approach,
                                        "parallel": self.parallel, "round": self.round_no,
                                        "lead_agent": "orchestrator"})
            db.add(swarm)
            await db.flush()
            for p in self.packages:
                child = SubAgent(swarm_run_id=swarm.id, subagent_name=f"{p.specialist}-{p.id}",
                                 subagent_type=p.specialist, role=p.role, specialization=p.title,
                                 model_provider="router", model_name=self.model,
                                 system_prompt=SPECIALISTS[p.specialist]["standard"], status="spawning",
                                 meta_data={"parent_agent_id": str(lead.id), "task_id": str(self.runtime.task_id),
                                            "package": p.id, "owns": p.owns, "depends_on": p.depends_on,
                                            "requirements": p.requirements,
                                            "authority_level": int(self.runtime.authority_level),
                                            "authority_ceiling": int(self.runtime.authority_level),
                                            "timeout_seconds": SUB_AGENT_TIMEOUT_SECONDS,
                                            "can_spawn": False})
                db.add(child)
                await db.flush()
                task = SubAgentTask(subagent_id=child.id, task_description=f"{p.title}: {p.goal}"[:8000],
                                    task_type="work_package", status="pending", priority=5,
                                    meta_data={"done_when": p.done_when, "package": p.id})
                db.add(task)
                await db.flush()
                p.sub_agent_id, p.sub_task_id = child.id, task.id
            return swarm.id, lead.id

        opened = await self._book(work)
        if opened:
            self.swarm_run_id, self.lead_agent_id = opened

    async def log(self, package: Package, level: str, category: str, message: str,
                  context: Optional[Dict[str, Any]] = None) -> None:
        if package.sub_agent_id is None:
            return
        from app.core.security import redact_text
        from app.models.swarm import SubAgentLog

        async def work(db):
            db.add(SubAgentLog(subagent_id=package.sub_agent_id, log_level=level, log_category=category,
                               log_message=redact_text(message)[:4000],
                               context={"parent_agent_id": str(self.lead_agent_id) if self.lead_agent_id else None,
                                        "package": package.id, "task_id": str(self.runtime.task_id),
                                        **(context or {})}))

        await self._book(work)

    async def _mark(self, package: Package, *, starting: bool) -> None:
        if package.sub_agent_id is None:
            return
        from app.models.swarm import SubAgent, SubAgentTask

        async def work(db):
            child = await db.get(SubAgent, package.sub_agent_id)
            task = await db.get(SubAgentTask, package.sub_task_id) if package.sub_task_id else None
            now = datetime.now(timezone.utc)
            if child is None:
                return
            if starting:
                child.status, child.started_at = "working", now
                if task is not None:
                    task.status, task.started_at = "in_progress", now
                return
            outcome = {"package": package.id, "success": package.success, "summary": package.summary[:4000],
                       "steps": package.step, "tool_calls": package.calls, "tools": package.tools}
            # The sub-agent's work is over: it dissolves, keeping its result.
            child.status, child.completed_at, child.success = "dissolved", now, package.success
            started = child.started_at or now
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            child.duration_seconds = int((now - started).total_seconds())
            child.result, child.tokens_used = outcome, int(package.tokens)
            child.api_calls = int(package.calls)
            child.cost = Decimal(str(round(package.cost_usd, 6)))
            child.error_message = None if package.success else package.summary[:2000] or "stopped"
            child.meta_data = {**(child.meta_data or {}), "dissolved_at": now.isoformat(),
                               "dissolve_reason": "work package finished" if package.success else "work package stopped"}
            if task is not None:
                task.status = "completed" if package.success else "failed"
                task.completed_at, task.success, task.result = now, package.success, outcome
                task.duration_seconds = child.duration_seconds

        await self._book(work)

    async def _close_swarm(self, success: bool, summary: str) -> None:
        if self.swarm_run_id is None:
            return
        from app.core.swarm.tracking import SwarmTracker
        from app.models.swarm import SwarmRun

        async def work(db):
            swarm = await db.get(SwarmRun, self.swarm_run_id)
            if swarm is None:
                return
            now = datetime.now(timezone.utc)
            swarm.status = "completed" if success else "failed"
            swarm.completed_at, swarm.success = now, success
            started = swarm.started_at or now
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            swarm.duration_seconds = int((now - started).total_seconds())
            swarm.result = {"summary": summary[:4000], "packages": [p.card() for p in self.packages]}
            swarm.total_api_calls = sum(p.calls for p in self.packages)
            await SwarmTracker().record_final_cost(db, swarm)

        await self._book(work)

    # ----- planning ----------------------------------------------------------

    async def _parallel_limit(self) -> int:
        limit = max(1, min(int(settings.MISSION_PARALLEL_AGENTS), int(settings.SWARM_MAX_CONCURRENT)))
        try:
            from app.models.workspace import Workspace

            workspace = await self.runtime.db.get(Workspace, self.runtime.workspace_id)
            if workspace is not None:
                if not workspace.swarm_enabled or not settings.SWARM_ENABLED:
                    return 1
                limit = min(limit, max(1, int(workspace.max_subagents or limit)))
        except Exception as exc:  # noqa: BLE001
            logger.info(f"workspace swarm limits unavailable: {exc}")
        return limit

    async def _plan(self, router, mission: str, known: Optional[str]) -> None:
        from app.core.workspaces import fs_inspector

        open_reqs = [r for r in self.lead.requirements if r.get("status") != "done"]
        open_ids = [str(r["id"]).upper() for r in open_reqs]
        container = fs_inspector.host_to_container(self.workspace_root) if self.workspace_root else None
        tree = await asyncio.to_thread(workspace_tree, container)
        spec = ""
        try:
            spec = await self.lead._specification_passages(mission)
        except Exception as exc:  # noqa: BLE001 - the plan is made without the passages
            logger.info(f"planning without specification passages: {exc}")
        roster = "\n".join(f"- {name}: {s['title']}" for name, s in sorted(SPECIALISTS.items()))
        limit = int(settings.MISSION_MAX_PACKAGES)
        prompt = (f"MISSION:\n{mission[:8000]}\n\n"
                  f"OPEN REQUIREMENTS:\n{render_requirements(open_reqs)[:12000] or '(none listed)'}\n\n"
                  f"WORKSPACE ({self.workspace_root}):\n{tree[:12000] or '(empty)'}\n\n"
                  + (f"SPECIFICATION SECTIONS:\n{spec[:16000]}\n\n" if spec else "")
                  + (f"WHAT JAI ALREADY KNOWS:\n{known[:6000]}\n\n" if known else "")
                  + f"THE SPECIALISTS:\n{roster}\n\n"
                  f"The team works {self.parallel} at a time. Plan the work packages now.")
        try:
            resp = await self.lead._model_step(router, CompletionRequest(
                model=self.model, messages=[Message(role="user", content=prompt)],
                system=_PLANNER.format(limit=limit), tools=[PLAN_TOOL],
                max_tokens=settings.AGENT_MAX_OUTPUT_TOKENS, temperature=0.0,
                reasoning_effort=getattr(settings, "OPENAI_VERIFIER_REASONING_EFFORT", "high")))
        except Exception as exc:  # noqa: BLE001 - no plan: the lead does the mission alone
            logger.warning(f"mission planning failed: {exc}")
            return
        if resp is None:
            return
        self.lead.tokens += int((resp.usage or {}).get("total_tokens", 0) or 0)
        for call in resp.tool_calls or []:
            if call["function"]["name"] != PLAN_TOOL["name"]:
                continue
            try:
                arguments = json.loads(call["function"]["arguments"] or "{}")
            except (TypeError, ValueError):
                arguments = {}
            plan = parse_plan(arguments, open_ids, limit)
            self.approach, self.packages = plan["approach"], plan["packages"]
            return

    # ----- running -----------------------------------------------------------

    def _brief(self, p: Package, mission: str) -> str:
        others = [q for q in self.packages if q.id != p.id]
        before = [q for q in self.packages if q.id in p.depends_on]
        lines = [
            f"You are JAI's {p.role}, one specialist in the team doing this mission. Your standard: "
            f"{SPECIALISTS[p.specialist]['standard']}",
            "",
            f"THE WHOLE MISSION (for context; do only your work package):\n{mission[:6000]}",
            "",
            f"THE TEAM'S APPROACH: {self.approach}" if self.approach else "",
            f"YOUR WORK PACKAGE {p.id}: {p.title}",
            f"Goal: {p.goal}",
            f"Done when: {p.done_when}" if p.done_when else "",
            (f"You own these paths and are the only one writing there: {', '.join(p.owns)}. Read anything in the "
             f"workspace; write only inside your paths." if p.owns else
             "You work alone in this wave, so you may write anywhere in the workspace."),
        ]
        if others:
            lines.append("The rest of the team: " + "; ".join(
                f"{q.id} {q.role} — {q.title}" + (f" (owns {', '.join(q.owns[:6])})" if q.owns else "")
                for q in others))
        for q in before:
            lines.append(f"{q.id} ({q.role}) finished before you"
                         + (" and reported: " + q.summary[:1200] if q.summary else "."))
        lines.append("When your package is done and checked with real commands, call finish with a summary: the "
                     "files you changed, the commands you ran and their results, and anything another package or "
                     "the integration lead must still do.")
        return "\n".join(line for line in lines if line)

    async def _run_package(self, p: Package, mission: str, known: Optional[str]) -> None:
        from app.core.command.tool_runtime import ToolRuntime

        p.status, p.started_at = "working", datetime.now(timezone.utc)
        await self._mark(p, starting=True)
        await self.log(p, "info", "lifecycle", f"spawned by the orchestrator for {p.id}: {p.title}",
                       {"owns": p.owns, "depends_on": p.depends_on})
        await self.save_progress()
        mine = [dict(r) for r in self.lead.requirements if str(r["id"]).upper() in p.requirements]
        if not mine:
            mine = [{"id": f"{p.id}.1", "text": p.done_when or p.goal, "source": f"work package {p.id}",
                     "status": "open", "evidence": ""}]
        result: Dict[str, Any] = {}
        executor: Optional[SpecialistExecutor] = None
        try:
            async with self.sessions() as db:
                rt = ToolRuntime(db, self.runtime.workspace_id, self.runtime.task_id,
                                 operator=self.runtime.operator, authority_level=int(self.runtime.authority_level),
                                 user_id=self.runtime.user_id, agent_id=self.runtime.agent_id)
                executor = SpecialistExecutor(rt, self.model, self.workspace_root, team=self, package=p)
                try:
                    result = await executor.run(self._brief(p, mission), steps_per_round=PACKAGE_STEPS,
                                                max_continuations=int(settings.MISSION_PACKAGE_ROUNDS),
                                                known=known, verify=False, requirements=mine)
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        except Exception as exc:  # noqa: BLE001 - one specialist's failure is reported; the team goes on
            logger.warning(f"work package {p.id} stopped: {exc}", exc_info=True)
            result = {"success": False, "answer": f"{p.role} stopped: {type(exc).__name__}: {exc}"}
        p.success = bool(result.get("success"))
        p.summary = str(result.get("answer") or result.get("agent_summary") or "")
        p.status = "finished" if p.success else "stopped"
        p.tokens = int(result.get("tokens") or 0)
        if executor is not None:
            p.cost_usd = float(executor.usage.cost_usd)
            absorb(self.lead.usage, executor.usage, p.specialist)
            self.lead.tokens += p.tokens
            self._merge_requirements(p, result.get("requirements") or mine)
        await self.log(p, "info" if p.success else "warning", "execution_result",
                       f"{p.id} {'finished' if p.success else 'stopped'}: {p.summary[:1500]}",
                       {"success": p.success, "steps": p.step})
        await self._mark(p, starting=False)
        await self.save_progress()

    def _merge_requirements(self, p: Package, theirs: List[Dict[str, Any]]) -> None:
        by_id = {str(r["id"]).upper(): r for r in self.lead.requirements}
        for r in theirs:
            mine = by_id.get(str(r.get("id") or "").upper())
            if mine is not None and r.get("status") in ("done", "waiting"):
                mine["status"] = r["status"]
                mine["evidence"] = f"[{p.id} {p.role}] {r.get('evidence') or ''}"[:500]

    async def _run_team(self, mission: str, known: Optional[str]) -> None:
        pending = list(self.packages)
        finished: Dict[str, Package] = {}
        while pending:
            wave = next_wave(pending, finished, self.parallel)
            for p in wave:
                pending.remove(p)
            await asyncio.gather(*(self._run_package(p, mission, known) for p in wave))
            for p in wave:
                finished[p.id] = p

    def _integration_mission(self, mission: str) -> str:
        lines = [mission, "", "THE TEAM'S WORK THIS ROUND (each specialist's own report: check it against the files "
                              "and commands, do not take it on trust):"]
        for p in self.packages:
            lines.append(f"- {p.id} {p.role} — {p.title}: {'finished' if p.success else 'stopped'} after "
                         f"{p.step} steps. {p.summary[:1500]}")
        lines += ["", "YOUR ROLE NOW: you are the integration lead. Install, build and test the whole project with "
                      "its real commands, fix whatever breaks where the packages meet, finish anything the team "
                      "left open or stopped on, ask Richard (through the boundary tools) only for what truly needs "
                      "him, and call finish when the whole mission is done and verified."]
        return "\n".join(lines)

    def _team_report(self) -> str:
        if not self.packages:
            return ""
        lines = [f"**The team** ({len(self.packages)} specialists, up to {self.parallel} at a time"
                 + (f"; {self.approach}" if self.approach else "") + ")"]
        for p in self.packages:
            lines.append(f"- {p.id} {p.role} — {p.title}: {'finished' if p.success else 'stopped'} "
                         f"({p.step} steps, {p.calls} tool calls)")
        return "\n".join(lines) + "\n\n"

    async def run(self, mission: str, steps_per_round: int = 8, max_continuations: int = 4,
                  prior_messages=None, start_continuation: int = 0, known: Optional[str] = None,
                  verify: bool = True, requirements: Optional[List[Dict[str, Any]]] = None,
                  prior_calls: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        self.round_no = start_continuation + 1
        if not settings.MISSION_TEAM_ENABLED or not self.workspace_root or prior_messages:
            return await self.lead.run(mission, steps_per_round, max_continuations, prior_messages,
                                       start_continuation, known, verify, requirements, prior_calls)
        router = MeteredRouter(get_router(), self.lead.usage, "planning", self.lead._cache_key())
        await self.lead._prepare_tools()
        if requirements:
            self.lead.requirements = [dict(r) for r in requirements]
        standing = await self.lead.hard_checks()
        if standing is not None:
            self.lead.hard_baseline = {f["check"] + "|" + f["file"] + "|" + f["detail"]
                                       for f in standing["findings"]}
        if not requirements:
            from app.core.command.requirements import derive
            from app.core.verification.checks import Finding

            spec = ""
            try:
                spec = await self.lead._specification_passages(mission)
            except Exception as exc:  # noqa: BLE001
                logger.info(f"requirements without specification passages: {exc}")
            # As one agent would: for a conformance mission every hard-check finding is a requirement of its own.
            findings = ([Finding(**f).text() for f in self.lead._hard_in_scope(mission, standing)]
                        if standing and standing.get("findings") and self.lead._conformance(mission, standing)
                        else [])
            derived = await derive(router.as_role("requirements"), self.model, mission, spec=spec,
                                   findings=findings)
            self.lead.requirements = derived["requirements"]
            self.lead.tokens += derived["tokens"]
        self.parallel = await self._parallel_limit()
        if any(r.get("status") != "done" for r in self.lead.requirements):
            await self._plan(router, mission, known)
        if len(self.packages) < 2:
            # One small change (or no plan): the lead does it alone, as one agent.
            self.packages = []
            return await self.lead.run(mission, steps_per_round, max_continuations, None, start_continuation,
                                       known, verify, self.lead.requirements, prior_calls)
        self.phase = "team"
        try:
            # What the mission has written so far is committed before the team starts, so no specialist's own
            # session ever waits on a row the lead's open transaction holds.
            await self.runtime.db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"mission records not committed before the team started: {exc}")
            await self.runtime.db.rollback()
        await self._open_swarm(mission)
        await self.save_progress()
        await self._run_team(mission, known)
        self.phase = "integration"
        team_steps = sum(p.step for p in self.packages)
        result = await self.lead.run(self._integration_mission(mission), steps_per_round, max_continuations,
                                     None, start_continuation, known, verify, self.lead.requirements, prior_calls)
        team = [p.card() for p in self.packages]
        await self._close_swarm(bool(result.get("success")), str(result.get("answer") or ""))
        result["answer"] = self._team_report() + str(result.get("answer") or "")
        result["team"] = {"approach": self.approach, "parallel": self.parallel, "packages": team,
                          "swarm_run_id": str(self.swarm_run_id) if self.swarm_run_id else None}
        result["iterations"] = int(result.get("iterations") or 0) + team_steps
        result["tools"] = sorted(set(result.get("tools") or []) | {t for p in self.packages for t in p.tools})
        metrics = dict(result.get("metrics") or {})
        metrics["steps"] = int(metrics.get("steps") or 0) + team_steps
        metrics["team"] = {"packages": len(self.packages), "parallel": self.parallel,
                           "finished": sum(1 for p in self.packages if p.success)}
        result["metrics"] = metrics
        return result


def mission_executor(runtime, model: str, workspace_root: Optional[str], **kwargs):
    """What runs a mission: its team when it has a workspace folder (the lead alone otherwise, inside the team)."""
    return MissionTeam(runtime, model, workspace_root, **kwargs)
