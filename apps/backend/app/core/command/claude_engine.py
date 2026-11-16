"""
JAI Backend - A specialist's mission on the Claude Agent SDK, configured the way Claude Code itself works

Richard, 15 November: "I don't want anything home made ... it should be using proven workflows and loops from the
proven open source repos." The first version of this engine put the SDK inside JAI's own machinery (a written
requirement checklist it had to tick off, a finish tool that could refuse, reminders when it replied in words, a
long hand-written prompt, only a handful of skills, and JAI's versions of every Claude Code tool). The bench showed
the work done within its allowance but never accepted. That machinery is gone. The session is now the standard
Claude Agent SDK set-up, as Anthropic documents it (code.claude.com/docs/en/agent-sdk):

- THE LOOP is Claude Code's own: the agent plans (TodoWrite), works and decides when it has finished. Nothing in
  JAI refuses its finish or prompts it to keep going.
- THE PROMPT is the claude_code preset with the specialist's identity and Richard's standing rules appended
  ("modifying system prompts": the lowest-risk customisation; nothing of the preset is removed).
- THE TOOLS are Claude Code's own: Read, Write, Edit, Glob and Grep in the product's folder, WebSearch, WebFetch,
  TodoWrite, Skill, and Agent for JAI's other specialists. JAI's own tools that Claude Code has no equivalent for
  (workbooks, contact finding from a business's own pages, memory, the knowledge graph, images, voiceovers, video)
  are served beside them as an MCP server. The shell is not part of a specialist's session.
- EVERY SKILL JAI has installed is in the session, loaded the SDK's way (user setting source): Claude sees each
  skill's description and opens the one it needs with the Skill tool.
- SUPERPOWERS AND ECC run as the Claude Code plugins their authors ship (the SDK's plugins option): their agents,
  commands and workflows (Superpowers' brainstorm, plan, execute and verify-before-completion, with its own
  session-start hook; ECC's agents and commands), assembled from the pinned clones AgentShield has scanned. Before 15
  November only their skills were installed and JAI's own loop ran the missions.
- EVERY MODEL CALL of the mission is Claude's (config.missions_on_claude): the check, the report, reading the
  request, the debrief and the business tools' small steps, so no step waits on another provider.
- JAI'S SAFETY RULES are applied with the SDK's documented mechanism for gating every tool call, a PreToolUse hook:
  each call goes through JAI's one permission gate (check_tool_permission: authority level, hard boundaries,
  approval pauses that open Richard's boundary chain) and the folder scope; a PostToolUse hook records every call in
  the mission's evidence trail, the operations feed and the audit log. A cancelled mission is denied its next call
  and the session is interrupted. The session's spending limit is the mission's allowance (max_budget_usd).
- THE CHECK stays JAI's (CLAUDE.md: no unverified output): when the agent has finished, JAI's independent Verifier
  reviews the work and its findings go back to the agent once, as a reply in the same conversation (the documented
  multi-turn pattern); then the report is written from the evidence and states what is still open. A round cut short
  by the allowance or the turn limit carries on by resuming the same SDK session.

If the SDK or its Claude Code engine cannot start (not installed, no Anthropic key), JAI's own loop does the work as
before and the reason is logged: the mission still runs. MISSION_ENGINE=jai switches the engine off.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.command.role_mission import RoleExecutor, role_tools
from app.core.config import settings

logger = logging.getLogger(__name__)

SERVER = "jai"
PREFIX = f"mcp__{SERVER}__"
# Claude Code's own tools in a specialist's session.
FILE_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep")
WEB_TOOLS = ("WebSearch", "WebFetch")
# ToolSearch loads a tool's definition into the session (Claude Code defers the definitions of a large tool set):
# without it the agent cannot call JAI's own tools properly. 15 November: the gate refused it, so the specialist,
# whose first move was to load discover_prospect_companies and fill_contacts, worked one business at a time with
# the only tool it could call blind (123 find_contacts calls), and found 20 businesses with 3 contacts.
LOADERS = ("ToolSearch",)
OWN_TOOLS = FILE_TOOLS + WEB_TOOLS + ("TodoWrite", "Skill", "Agent", "Task") + LOADERS
# Not part of a specialist's session: the shell (JAI's command gate is for the builder's sandbox) and anything that
# would wait for a person.
REMOVED = ("Bash", "BashOutput", "KillShell", "NotebookEdit", "AskUserQuestion", "SendMessage", "Workflow",
           "Agent(fork)")
# JAI's tools that Claude Code's own replace in the session (the same job, Claude Code's way).
REPLACED = {"list_files", "read_file", "search_files", "get_file_metadata", "write_file", "edit_file", "create_folder",
            "move_file", "copy_file", "fetch_url", "web_search", "read_skill", "git_status", "git_log",
            "finish", "requirement_status"}
# How a Claude Code tool appears in JAI's record and permission gate.
JAI_NAME = {"Read": "read_file", "Write": "write_file", "Edit": "edit_file", "Glob": "list_files",
            "Grep": "search_files", "WebFetch": "fetch_url", "WebSearch": "web_search"}
WRITES = ("Write", "Edit")
SUB_AGENTS_AT_ONCE = 3
SESSION_SHARE = 0.75
EXTRA_TURNS = 40
TEXT_LIMIT = 30_000


def enabled() -> bool:
    """The engine is on. Never in tests: tests never spend provider credit (they stand a session in)."""
    if getattr(settings, "TESTING", False):
        return False
    return str(getattr(settings, "MISSION_ENGINE", "claude") or "claude").strip().lower() == "claude"


def engine_model() -> str:
    return str(getattr(settings, "CLAUDE_ENGINE_MODEL", "") or "claude-sonnet-5-5")


def api_key() -> str:
    return str(getattr(settings, "ANTHROPIC_API_KEY", "") or getattr(settings, "CLAUDE_API_KEY", "") or "")


def sessions_root() -> Path:
    """Where each mission's Claude Code configuration (its skills and its session transcripts) lives, so a round
    cut short can resume the same session and a mission's record can be read after the worker restarts (JAI_SESSIONS_DIR; it was the temporary folder before 15 November, which a restart wipes)."""
    return Path(str(getattr(settings, "JAI_SESSIONS_DIR", "") or Path(tempfile.gettempdir()) / "jai-claude"))


def ecc_learning_env(folder: Optional[Path]) -> Dict[str, str]:
    """The switches ECC itself reads (affaan-m/ECC: scripts/lib/hook-flags.js, scripts/lib/agent-data-home.js,
    skills/continuous-learning-v2) so its learning system runs in the mission's session as its authors ship it:
    where it keeps what it learns (kept across restarts), which of its hooks are off (settings.ECC_DISABLED_HOOKS),
    its observer switched on in its own config file, the session marked as an Agent SDK session ECC observes
    (CLAUDE_CODE_ENTRYPOINT: ECC's observe.sh records "sdk-ts" sessions and skips the Python SDK's default "sdk-py"
    as automation), and the Claude Code program the observer runs. ECC keeps a workspace that is a git repository's
    lessons to that repository, and lessons from other folders in its global store."""
    if not getattr(settings, "ECC_LEARNING_ENABLED", True):
        return {"ECC_HOOK_PROFILE": "minimal", "ECC_SKIP_OBSERVE": "1"}
    root = Path(str(getattr(settings, "ECC_LEARNING_DIR", "") or "/app/.jai-learned"))
    env = {"CLAUDE_CODE_ENTRYPOINT": "sdk-ts", "ECC_AGENT_DATA_HOME": str(root / "ecc"), "CLV2_HOMUNCULUS_DIR": str(root / "homunculus"),
           "ECC_DISABLED_HOOKS": str(getattr(settings, "ECC_DISABLED_HOOKS", "") or ""),
           "ECC_OBSERVER_MODEL": light_model(),
           # A mission runs unattended at any hour: the observer's desk-hours and idle gates do not apply.
           "OBSERVER_ACTIVE_HOURS_START": "0", "OBSERVER_ACTIVE_HOURS_END": "0", "OBSERVER_MAX_IDLE_SECONDS": "0"}
    try:
        config = root / "homunculus" / "config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        wanted = {"version": "2.1", "observer": {"enabled": True, "run_interval_minutes": 5,
                                                 "min_observations_to_analyze": 20}}
        if not config.is_file() or json.loads(config.read_text(encoding="utf-8")) != wanted:
            config.write_text(json.dumps(wanted, indent=2), encoding="utf-8")
        env["CLV2_CONFIG"] = str(config)
    except (OSError, ValueError) as exc:
        logger.info(f"ECC's observer stays off this session: {exc}")
    try:  # the Claude Code program the SDK ships, for the observer's own short Haiku sessions
        import claude_agent_sdk

        bundled = Path(claude_agent_sdk.__file__).parent / "_bundled"
        if (bundled / "claude").is_file():
            env["PATH"] = f"{bundled}{os.pathsep}{os.environ.get('PATH', '')}"
    except (ImportError, AttributeError, TypeError):
        pass  # Claude Code on the PATH serves, or the observer logs that it found none
    return env


def light_model() -> str:
    from app.core.config import light_model as chosen

    return chosen()


def _kind(message: Any) -> str:
    return type(message).__name__


def _text(result: Any) -> str:
    text = result if isinstance(result, str) else json.dumps(result, default=str, ensure_ascii=False)
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + f"… [cut: {len(text) - TEXT_LIMIT} more characters]"


def _deny(reason: str) -> Dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except (ValueError, OSError):
        return False


class ClaudeRoleExecutor(RoleExecutor):
    """A role's mission whose work runs on the Claude Agent SDK, set up as Claude Code is (see the module's notes)."""

    engine = "claude"
    # The independent check of an engine mission: at most 20 model calls and 5 minutes (15 November: up to 80 calls
    # on a 10-row workbook). The checklist it works from is at most 8 items (requirements.MAX_SPECIALIST_REQUIREMENTS).
    verifier_cap = 20
    verifier_seconds = 300

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.engine_cost_usd = 0.0
        self.engine_note = ""
        self._lock = asyncio.Lock()   # one database session: JAI's tools and records go one at a time
        self._client = None
        self._stop: Optional[str] = None
        self.delegated: List[Dict[str, str]] = []  # each part handed to a colleague: who, and what
        self._verify_on = False       # set by run(verify=...): a team member's part is checked by its lead
        self._verdict: Optional[Dict[str, Any]] = None
        self._verdict_calls = -1
        self.session_id: Optional[str] = None
        self.skills_seen: List[str] = []
        self.plugins_seen: List[str] = []
        self._result_text = ""
        self._agent_said = ""

    # ----- the session's parts ------------------------------------------------------------------------------------

    def _config_dir(self) -> Path:
        """The mission's Claude Code configuration folder, holding every installed JAI skill under skills/ (the
        skills of a pack that loads as a plugin come with its plugin instead). A skill AgentShield blocked is never
        linked."""
        from app.core.command.expertise import _skill_folder, _usable
        from app.core.knowledge.skill_packs import SKILLS

        key = str(getattr(self.runtime, "task_id", None) or f"session-{os.getpid()}-{id(self)}")
        base = sessions_root() / key
        target = base / "skills"
        target.mkdir(parents=True, exist_ok=True)
        plugged = set(self._plugins_on_disk())
        for entry in _usable([e for e in SKILLS if e["pack"] not in plugged]):
            try:
                folder = _skill_folder(entry)
            except Exception:  # noqa: BLE001 - a skill that cannot be placed is left out, the rest load
                continue
            link = target / entry["skill"]
            if (folder / "SKILL.md").is_file() and not link.exists():
                try:
                    os.symlink(folder, link, target_is_directory=True)
                except OSError:
                    continue
        return base

    @staticmethod
    def _plugins_on_disk() -> List[str]:
        """The packs that load as Claude Code plugins (Superpowers, ECC) and whose plugin parts are installed."""
        from app.core.knowledge.skill_packs import PACKS, packs_dir, plugin_parts

        out = []
        for name in PACKS:
            parts = plugin_parts(name)
            base = packs_dir() / name
            if parts and any((base / part).is_dir() for part in parts):
                out.append(name)
        return out

    def _plugins(self, config: Path) -> List[Dict[str, str]]:
        """Superpowers and ECC as Claude Code plugins, as their authors ship them to Claude Code: their agents,
        commands and (Superpowers') hooks, with their skills. Each is assembled in the mission's configuration folder
        from the pinned, AgentShield-scanned clone: a part AgentShield blocked, and a skill it blocked, is left out.
        ECC's skills are the ones JAI chose for its stack and goals (60 of its 314)."""
        from app.core.command.expertise import _skill_folder, _usable
        from app.core.knowledge.skill_packs import PACKS, SKILLS, packs_dir, plugin_parts

        out: List[Dict[str, str]] = []
        for name in self._plugins_on_disk():
            pack, base = PACKS[name], packs_dir() / name
            try:
                refused = {line.strip().strip("/") for line in
                           (base / ".jai-blocked-parts").read_text(encoding="utf-8").splitlines() if line.strip()}
            except OSError:
                refused = set()
            home = config / "plugins" / name
            shutil.rmtree(home, ignore_errors=True)
            (home / ".claude-plugin").mkdir(parents=True)
            (home / ".claude-plugin" / "plugin.json").write_text(json.dumps({
                "name": name, "description": f"{pack.get('title', name)} by {pack.get('publisher', '')}",
                "version": str(pack.get("commit", ""))[:7]}))
            for part in plugin_parts(name):
                source = base / part
                if not source.is_dir() or part in refused:
                    continue
                if part == "hooks":
                    os.symlink(source, home / "hooks", target_is_directory=True)
                    continue
                (home / part).mkdir()
                for item in sorted(source.iterdir()):
                    if f"{part}/{item.name}" not in refused and not item.name.startswith("."):
                        os.symlink(item, home / part / item.name, target_is_directory=item.is_dir())
            (home / "skills").mkdir()
            chosen = [e for e in SKILLS if e["pack"] == name]
            if name == "superpowers":  # the whole workflow: its skills hand on to one another by name
                root = base / pack["root"]
                listed = {e["skill"] for e in chosen}
                chosen += [{"pack": name, "skill": d.name, "agents": (), "sandbox": ()} for d in sorted(
                    root.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file() and d.name not in listed] \
                    if root.is_dir() else []
            for entry in _usable(chosen):
                folder = _skill_folder(entry)
                if (folder / "SKILL.md").is_file() and not (home / "skills" / entry["skill"]).exists():
                    os.symlink(folder, home / "skills" / entry["skill"], target_is_directory=True)
            out.append({"type": "local", "path": str(home)})
        return out

    def _folder(self) -> Optional[Path]:
        """The product's folder inside the container (the session's working directory)."""
        from app.core.workspaces import fs_inspector

        return fs_inspector.host_to_container(self.workspace_root) if self.workspace_root else None

    def _host(self, path: Path, folder: Path) -> str:
        """The host path JAI's permission gate and record use for a path in the product's folder."""
        rel = path.resolve().relative_to(folder.resolve()).as_posix()
        root = str(self.workspace_root).rstrip("\\/")
        sep = "\\" if ("\\" in root or root[1:2] == ":") else "/"
        return root if rel in ("", ".") else root + sep + rel.replace("/", sep)

    def _appended(self) -> str:
        """The specialist's identity and Richard's standing rules, appended to Claude Code's own prompt."""
        rules = list(getattr(self.job, "rules", None) or [])
        parts = [
            f"You are JAI's {self.title}, one of the 31 specialists in Richard Curley's AI company. {self.standard}",
            f"Today's date is {datetime.now(timezone.utc):%d %B %Y}.",
            f"You work in the product's folder ({self.workspace_root}), your working directory. Save what you make "
            "there.",
            "No one is watching this session as it runs: where a skill or workflow would stop to ask Richard a "
            "question or for approval of a plan, take the most reasonable answer from his request and his rules, "
            "write the assumption down in the work, and carry on to the finished deliverable.",
            "Richard's rules for all work: contact, send, post, publish and spend nothing (drafts only). Use only facts "
            "you found and can source; never guess a contact, an email address or a figure. Contact details are only "
            "those a business publishes itself (UK PECR).",
            f"JAI's own tools (names starting {PREFIX}) do what Claude Code's do not: {PREFIX}write_spreadsheet, "
            f"{PREFIX}tidy_spreadsheet and {PREFIX}check_spreadsheet for Excel workbooks, {PREFIX}find_contacts and "
            f"{PREFIX}fill_contacts for the contact details a business publishes on its own pages, and JAI's memory "
            f"and knowledge graph. Claude Code's Read cannot open an Excel, Word or PDF file: open one with "
            f"{PREFIX}read_document (15 November: four steps of a mission were lost to Read on .xlsx files).",
            f"For a list or database of businesses, work at machine speed, not one business at a time: "
            f"{PREFIX}discover_prospect_companies gives every business of a type in an area from OpenStreetMap (free "
            f"open data) with its website; save them with {PREFIX}write_spreadsheet; {PREFIX}fill_contacts then reads "
            f"all their own sites side by side for the published phone, email and contact page; "
            f"{PREFIX}find_decision_makers and {PREFIX}verify_prospect_email add named people and check addresses. "
            "Search the web for what open data does not hold. A business that publishes no email or phone is never "
            "a reason to stop: it stays marked under still to check, is not counted, and you carry on with more "
            "businesses until the number Richard asked for can be contacted (fill_contacts reports how many can).",
        ]
        if rules:
            parts.append("Richard's standing rules for this product (every one applies):\n"
                         + "\n".join(f"- {r}" for r in rules))
        return "\n\n".join(parts)

    def _prompt(self, mission: str) -> str:
        """Richard's request, the job as JAI's specialist set it out, and what JAI's independent check looks for."""
        parts = [mission]
        text = str(getattr(self.job, "text", "") or "")
        if text:
            parts.append(f"THE JOB AS JAI SET IT OUT:\n{text}")
        if self.requirements:
            parts.append("WHAT JAI'S INDEPENDENT CHECK WILL LOOK FOR IN THE FINISHED WORK:\n" + "\n".join(
                f"- {r['id']}: {r['text']}" for r in self.requirements))
        return "\n\n".join(parts)

    def _agents(self, names: List[str], sdk) -> Dict[str, Any]:
        """JAI's other specialists as sub-agents. Each has Claude Code's own tools and only the JAI tools the lead
        has, so it can never exceed the lead's authority or folder (the same hooks gate its calls)."""
        from app.core.command.mission_org import SPECIALISTS

        mine = set(names)
        out: Dict[str, Any] = {}
        for role, spec in SPECIALISTS.items():
            if role in (self.role, "builder"):
                continue
            try:
                theirs = [f"{PREFIX}{t}" for t in role_tools(role) if t in mine]
            except Exception:  # noqa: BLE001
                theirs = []
            title = spec.get("title", role)
            out[role.replace("_", "-")] = sdk.AgentDefinition(
                description=f"JAI's {title}: {str(spec.get('standard', ''))[:300]}",
                prompt=(f"You are JAI's {title}, doing one part of a mission for JAI's {self.title}. "
                        f"{spec.get('standard', '')} You work in the product's folder ({self.workspace_root}). Do "
                        "the part you are given fully, save what you make in the folder, and report exactly what you "
                        "saved and where, and what you could not do. Never guess a fact, a contact or an address. "
                        "Contact, send, post, publish and spend nothing."),
                tools=list(FILE_TOOLS + WEB_TOOLS + ("TodoWrite", "Skill") + LOADERS) + theirs,
                model="inherit",
            )
        return out

    async def _cancelled(self) -> bool:
        task_id = getattr(self.runtime, "task_id", None)
        if task_id is None or getattr(self.runtime, "db", None) is None:
            return False
        from sqlalchemy import select

        from app.models.task import Task

        try:
            status = (await self.runtime.db.execute(select(Task.status).where(Task.id == task_id))
                      ).scalar_one_or_none()
        except Exception:  # noqa: BLE001 - the check is a guard, not a reason to stop
            return False
        return str(status or "").lower() == "cancelled"

    def _book(self, result: Any) -> None:
        """The session's cost and tokens, booked to the mission's account."""
        cost = float(getattr(result, "total_cost_usd", None) or 0.0)
        self.engine_cost_usd += cost
        self.usage.cost_usd += cost
        usage = getattr(result, "usage", None) or {}
        self.usage.calls += int(getattr(result, "num_turns", 0) or 0)
        parts = {"input": usage.get("input_tokens", 0), "cached": usage.get("cache_read_input_tokens", 0),
                 "cache_write": usage.get("cache_creation_input_tokens", 0), "output": usage.get("output_tokens", 0)}
        role = self.usage.by_role.setdefault("mission", {"calls": 0, "input": 0, "cached": 0, "cache_write": 0,
                                                         "output": 0, "reasoning": 0})
        role["calls"] += int(getattr(result, "num_turns", 0) or 0)
        for key, value in parts.items():
            self.usage.totals[key] += int(value or 0)
            role[key] += int(value or 0)
            self.tokens += int(value or 0)

    def _progress_extra(self) -> Dict[str, Any]:
        extra = super()._progress_extra()
        for card in (extra.get("team") or {}).get("packages") or []:
            card["model"] = engine_model()
            card["engine"] = "Claude Agent SDK"
        return extra

    async def run(self, mission: str, *args, **kwargs) -> Dict[str, Any]:
        self._verify_on = bool(kwargs.get("verify", True))
        result = await super().run(mission, *args, **kwargs)
        if self.engine_note:
            result["engine"] = {"name": "claude", "model": engine_model(), "cost_usd": round(self.engine_cost_usd, 4),
                                "note": self.engine_note, "delegated": list(self.delegated),
                                "session_id": self.session_id, "skills": len(self.skills_seen),
                                "plugins": list(self.plugins_seen)}
            if isinstance(result.get("role"), dict):
                result["role"]["model"] = engine_model()
                result["role"]["engine"] = result["engine"]  # kept on the mission's record with the role
        return result

    async def verify(self, mission: str, summary: str, settled: bool = False) -> Dict[str, Any]:
        """The check after the session: the one already made stands when nothing has been done since."""
        if self._verdict is not None and self._verdict_calls == len(self.runtime.calls):
            verdict, self._verdict = self._verdict, None
        else:
            verdict = await super().verify(mission, summary, settled=settled)
        mark_met(self.requirements, verdict.get("checks"))
        return verdict

    # ----- the gate: JAI's permission check and record on every call (PreToolUse / PostToolUse) --------------------

    async def _pre(self, hook_input: Dict[str, Any], folder: Optional[Path], readable: List[Path]
                   ) -> Dict[str, Any]:
        tool = str((hook_input or {}).get("tool_name") or "")
        args = (hook_input or {}).get("tool_input") or {}
        if self._stop:
            return _deny(self._stop)
        async with self._lock:
            if await self._cancelled():
                self._stop = "This mission was cancelled by Richard. Stop now: do nothing further."
                if self._client is not None:
                    asyncio.ensure_future(self._client.interrupt())
                return _deny(self._stop)
            if tool.startswith(PREFIX) or tool in ("TodoWrite", "Skill") + LOADERS:
                return {}  # JAI's own tools enforce JAI's gate themselves; planning, skills and loading a tool's
                # definition touch nothing
            if tool in ("Agent", "Task"):
                self.delegated.append({"to": str(args.get("subagent_type") or "")[:60],
                                       "what": str(args.get("description") or "")[:200]})
                return {}
            if tool in FILE_TOOLS:
                if folder is None:
                    return _deny("This mission has no product folder, so there are no files to work on.")
                raw = args.get("file_path") or args.get("path") or args.get("notebook_path") or str(folder)
                path = Path(str(raw))
                path = path if path.is_absolute() else folder / path
                if not _inside(path, folder):
                    if tool == "Read" and any(_inside(path, r) for r in readable):
                        return {}  # a skill's own reference files
                    reason = f"{raw} is outside the product's folder ({self.workspace_root}). Work only inside it."
                    await self.runtime._record(JAI_NAME[tool], {"path": str(raw)}, False, f"blocked: {reason}")
                    return _deny(reason)
                content = args.get("content") if tool == "Write" else args.get("new_string")
                stopped = await self.runtime._enforce(JAI_NAME[tool], path=self._host(path, folder),
                                                      content=str(content) if content is not None else None)
                return _deny(str(stopped.get("reason") or "JAI's permission gate stopped this action.")) \
                    if stopped else {}
            if tool in WEB_TOOLS:
                if tool == "WebFetch":
                    from app.core import internet

                    ok, why = internet._ssrf_ok(str(args.get("url") or ""))
                    if not ok:
                        return _deny(f"That address is not one JAI may open: {why}")
                stopped = await self.runtime._enforce(JAI_NAME[tool], action_description=str(
                    args.get("url") or args.get("query") or ""))
                return _deny(str(stopped.get("reason") or "JAI's permission gate stopped this action.")) \
                    if stopped else {}
        return _deny(f"{tool} is not part of a specialist's session.")

    async def _post(self, hook_input: Dict[str, Any], folder: Optional[Path], total_budget: int,
                    continuation: int) -> Dict[str, Any]:
        tool = str((hook_input or {}).get("tool_name") or "")
        args = (hook_input or {}).get("tool_input") or {}
        answer = (hook_input or {}).get("tool_response")
        async with self._lock:
            self.iterations += 1
            if tool in JAI_NAME:
                failed = isinstance(answer, dict) and bool(answer.get("is_error") or answer.get("error"))
                raw = str(args.get("file_path") or args.get("path") or args.get("url") or args.get("query")
                          or args.get("pattern") or "")
                where = raw
                if folder is not None and tool in FILE_TOOLS and raw:
                    path = Path(raw) if Path(raw).is_absolute() else folder / raw
                    if _inside(path, folder):
                        where = self._host(path, folder)
                inputs = {"path": where} if tool in FILE_TOOLS else {"url": where} if tool == "WebFetch" \
                    else {"query": where}
                if tool in WRITES:
                    inputs["bytes"] = len(str(args.get("content") or args.get("new_string") or ""))
                    if self.first_edit_step is None and not failed:
                        self.first_edit_step = self.iterations
                await self.runtime._record(JAI_NAME[tool], inputs, not failed,
                                           f"{tool} {where}"[:300] + (" (failed)" if failed else ""),
                                           output={"engine": "claude", "result": _text(answer)[:1500]})
            told = await self._notes()
            await self._progress("working", continuation, total_budget)
        if told:  # Richard's words to the working mission (command/steer) reach the agent at its next step
            return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": told}}
        return {}

    # ----- the session --------------------------------------------------------------------------------------------

    async def _engine_loop(self, mission, messages, system, tools, total_budget, steps_per_round,
                           start_continuation):
        if not enabled():
            return None
        if not api_key():
            logger.warning("Claude engine not used: no Anthropic API key; JAI's own loop runs the mission")
            return None
        try:
            import claude_agent_sdk as sdk
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Claude engine not used ({exc}); JAI's own loop runs the mission")
            return None
        from app.core.knowledge.skill_packs import packs_dir

        state = {"calls": 0, "last": None}
        mine = [t for t in tools if t["name"] not in REPLACED]
        names = [t["name"] for t in mine]

        def handler(name: str):
            async def call(args: Dict[str, Any]) -> Dict[str, Any]:
                async with self._lock:
                    return await self._one_call(name, dict(args or {}), state, total_budget, steps_per_round,
                                                start_continuation)
            return call

        jai_tools = [sdk.tool(t["name"], str(t.get("description") or t["name"])[:1000],
                              t.get("input_schema") or {"type": "object", "properties": {}})(handler(t["name"]))
                     for t in mine]
        server = sdk.create_sdk_mcp_server(name=SERVER, version="1.0.0", tools=jai_tools)
        folder = self._folder()
        config = self._config_dir()
        readable = [config, Path(str(packs_dir()))]
        continuation = start_continuation

        async def pre(hook_input, tool_use_id, context):
            return await self._pre(hook_input, folder, readable)

        async def post(hook_input, tool_use_id, context):
            return await self._post(hook_input, folder, total_budget, continuation)

        allowance = float(self._cap or 0)  # the mission's allowance (role_mission.run sets it)
        spent = self._spent_before + float(self.usage.cost_usd or 0)
        # A quarter of the allowance is kept for what runs after the session (the independent check, the report):
        # the session's own limit covers only the session (15 November: $1.52 against a $1.28 allowance).
        budget = max(0.05, allowance * SESSION_SHARE - spent) if allowance > 0 else None
        resume = self._resumable()
        options = sdk.ClaudeAgentOptions(
            system_prompt={"type": "preset", "preset": "claude_code", "append": self._appended()},
            model=engine_model(),
            cwd=str(folder) if folder is not None else str(config),
            add_dirs=[str(p) for p in readable],
            setting_sources=["user"],              # the mission's config folder: every JAI skill
            skills="all",
            plugins=self._plugins(config),         # Superpowers and ECC, as their authors ship them
            mcp_servers={SERVER: server},
            allowed_tools=list(OWN_TOOLS) + [f"{PREFIX}*"],
            disallowed_tools=list(REMOVED) + ([] if folder is not None else list(FILE_TOOLS[1:])),
            permission_mode="dontAsk",
            hooks={"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[pre])],
                   "PostToolUse": [sdk.HookMatcher(matcher=None, hooks=[post])]},
            agents=self._agents(names, sdk),
            max_turns=total_budget + EXTRA_TURNS,
            max_budget_usd=budget,
            resume=resume,
            env={"ANTHROPIC_API_KEY": api_key(), "CLAUDE_AGENT_SDK_CLIENT_APP": "jai-backend",
                 "CLAUDE_CONFIG_DIR": str(config),
                 "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
                 "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": str(SUB_AGENTS_AT_ONCE),
                 # Claude Code's own telemetry and other non-essential traffic stay off: JAI's work is Richard's.
                 "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1",
                 **ecc_learning_env(folder)},
            stderr=lambda line: logger.debug(f"claude engine: {line}"),
        )
        self.engine_note = f"Claude Agent SDK, {engine_model()}"
        outcome, finished = "", False
        try:
            async with sdk.ClaudeSDKClient(options=options) as client:
                self._client = client
                await client.query("Carry on with the mission from where you stopped." if resume
                                   else self._prompt(mission))
                outcome = await self._drain(client)
                if outcome == "success" and not self._stop:
                    finished = True
                    review = await self._review(mission)
                    if review:
                        await client.query(review)
                        outcome = await self._drain(client) or outcome
        except Exception as exc:  # noqa: BLE001
            if not self.iterations and not state["calls"]:
                logger.warning(f"Claude engine could not start ({type(exc).__name__}: {exc}); JAI's own loop runs "
                               "the mission")
                self.engine_note = ""
                return None
            logger.warning(f"Claude engine stopped after {self.iterations} steps: {exc}")
            self._result_text = self._result_text or (
                f"The Claude engine stopped ({type(exc).__name__}); the work so far is saved and the mission carries "
                "on from here.")
            finished = False
        finally:
            self._client = None
        summary = self._result_text or self._agent_said or "(no further action)"
        if outcome == "error_max_budget_usd":
            self.capped = True
            finished = False
            summary = (f"The {self.title} stopped at this mission's spending allowance. Everything written so far is "
                       "saved in the folder.")
        elif self._stop:
            summary, finished = self._stop, True
        elif outcome and outcome != "success":
            finished = False  # the turn limit or an error: the next round resumes this session
        # After the review the agent has answered what the check found: what is left is reported, not re-run.
        settled = finished and self._verdict is not None and not self._verdict.get("verified")
        continuation = start_continuation + (self.iterations // max(1, steps_per_round))
        return summary, finished, finished, settled, continuation, state["last"]

    def _session_file(self) -> Optional[Path]:
        task_id = getattr(self.runtime, "task_id", None)
        return sessions_root() / str(task_id) / "session.txt" if task_id else None

    def _resumable(self) -> Optional[str]:
        """The SDK session an earlier round of this mission left, when it is still here to resume."""
        found = self._session_file()
        try:
            return (found.read_text().strip() or None) if found is not None and found.is_file() else None
        except OSError:
            return None

    def _keep_session(self) -> None:
        found = self._session_file()
        if found is not None and self.session_id:
            try:
                found.parent.mkdir(parents=True, exist_ok=True)
                found.write_text(self.session_id)
            except OSError:
                pass

    async def _review(self, mission: str) -> Optional[str]:
        """JAI's independent check of the finished work. None when it accepts the work (or the mission's lead checks
        it); otherwise what it found, to send back to the agent once in the same conversation."""
        if not self._verify_on or self._verdict is not None:
            return None
        await self._progress("independent check", 0, 0)
        verdict = await self.verify_in_time(mission, self._result_text or self._agent_said)
        self._verdict, self._verdict_calls = verdict, len(self.runtime.calls)
        mark_met(self.requirements, verdict.get("checks"))
        if verdict.get("verified"):
            return None
        found = [str(u)[:400] for u in (verdict.get("unmet") or [])][:15] or [
            "The review did not confirm the work."]
        self._verdict_calls = -1  # what the agent does next is checked afresh after the session
        return ("JAI's independent review of your work (by a separate agent that did not do it) found:\n"
                + "\n".join(f"- {f}" for f in found)
                + "\n\nAddress what can be addressed, in the files. Where something cannot be found in published "
                "sources, say so in the work itself rather than leaving it to look complete.")

    async def _drain(self, client) -> str:
        """Read the session's messages until its turn ends. Returns the result's subtype ("success",
        "error_max_turns", "error_max_budget_usd", ...)."""
        subtype = ""
        async for message in client.receive_response():
            kind = _kind(message)
            if kind == "SystemMessage" and getattr(message, "subtype", "") == "init":
                data = getattr(message, "data", None) or {}
                self.session_id = str(data.get("session_id") or self.session_id or "") or None
                self.skills_seen = [str(s) for s in (data.get("skills") or [])]
                self.plugins_seen = [str((p or {}).get("name") if isinstance(p, dict) else p)
                                     for p in (data.get("plugins") or [])]
                agents = data.get("agents") or []
                logger.info(f"Claude engine session {self.session_id}: {len(data.get('tools') or [])} tools, "
                            f"{len(self.skills_seen)} skills, {len(agents)} agents, plugins "
                            f"{', '.join(self.plugins_seen) or 'none'}"
                            + (f"; plugin errors: {data.get('plugin_errors')}" if data.get("plugin_errors") else ""))
            elif kind == "AssistantMessage" and not getattr(message, "parent_tool_use_id", None):
                said = " ".join(str(getattr(block, "text", "") or "") for block in getattr(message, "content", [])
                                if _kind(block) == "TextBlock").strip()
                if said:
                    self._agent_said = said[:2000]
            elif kind == "ResultMessage":
                self._book(message)
                subtype = str(getattr(message, "subtype", "") or "")
                self.session_id = str(getattr(message, "session_id", "") or self.session_id or "") or None
                self._keep_session()
                text = getattr(message, "result", None)
                if text:
                    self._result_text = str(text)[:6000]
        return subtype

    async def _one_call(self, name, args, state, total_budget, steps_per_round, start_continuation
                        ) -> Dict[str, Any]:
        """One of JAI's own tools, called by the engine: the role's toolbox, which applies JAI's gate itself."""
        if self._stop:
            return {"content": [{"type": "text", "text": self._stop}], "is_error": True}
        state["calls"] += 1
        state["last"] = f"engine-{state['calls']}"
        out = await self._tool_step(name, args)
        if (self.first_edit_step is None and name in ("write_spreadsheet", "tidy_spreadsheet", "fill_contacts")
                and isinstance(out, dict) and out.get("success") is True):
            self.first_edit_step = self.iterations + 1
        from app.core.agents.toolbox import result_limit

        text = _text(out)[:max(result_limit(name), 4000)]
        failed = isinstance(out, dict) and out.get("success") is False
        return {"content": [{"type": "text", "text": text}], "is_error": bool(failed)}


def mark_met(requirements: Optional[List[Dict[str, Any]]], checks: Any) -> int:
    """Mark done each requirement JAI's independent check found met, with evidence, and return how many are done.
    In JAI's own loop the specialist marks each requirement with requirement_status; the engine's session does not
    have that tool, so from 15 November no requirement was ever marked done and every mission's card said "0
    requirements done" though the check had confirmed four of eight with evidence (16 November, mission 6f10b402).
    The rule is the check's own (agent_executor._request_done): a met check naming the requirement, with evidence."""
    import re

    found = [c for c in (checks or []) if isinstance(c, dict) and c.get("met") is True
             and str(c.get("evidence") or "").strip()]
    for requirement in requirements or []:
        if not isinstance(requirement, dict) or requirement.get("status") == "done" or not requirement.get("id"):
            continue
        pattern = re.compile(rf"\b{re.escape(str(requirement['id']))}\b", re.I)
        check = next((c for c in found if pattern.search(str(c.get("requirement") or ""))), None)
        if check is not None:
            requirement["status"] = "done"
            requirement["evidence"] = str(requirement.get("evidence") or check.get("evidence"))[:600]
            requirement["checked_by"] = "JAI's independent check"
    return sum(1 for r in requirements or [] if isinstance(r, dict) and r.get("status") == "done")


def forget(task_id: Any) -> None:
    """Remove a finished mission's Claude Code folder (its skill links and session transcripts)."""
    if task_id:
        shutil.rmtree(sessions_root() / str(task_id), ignore_errors=True)


