"""
JAI Backend - A specialist's mission on the Claude Agent SDK

Richard, 15 November: JAI produces the work (decks, videos, a database of 156 businesses) but its business missions
do not finish. MYCO Phase 0, the decks and the videos ran on a mature engine (OpenHands, in JAI's sandbox); every
business mission since 13 November ran on an agent loop JAI wrote itself (agent_executor and role_mission), with its
own rounds, reminders, checklist and report layers, and that is where they failed. The Claude Agent SDK is Claude
Code as a library: the same agent loop, context management, skills, sub-agents and hooks.

So the work of a specialist's mission now runs on it, and everything around the work stays JAI's:

- JAI's TOOLS, through an MCP server in this process. Every call goes through the role's own toolbox, so JAI's
  authority levels, workspace confinement, hard boundaries, approval pauses, audit log and the mission's evidence
  trail are exactly what they are for JAI's own loop. Claude Code's own shell, file-writing and web tools are taken
  out of the session (disallowed_tools), and a PreToolUse hook refuses anything else outside the list.
- JAI's SKILLS, natively: the role's trade skills are linked into the session's .claude/skills, so the Skill tool
  loads each SKILL.md as Claude Code does, and Read opens their reference files (the skill packs folder is an added
  directory; nothing else is readable).
- JAI's AGENTS, as sub-agents: the lead specialist can hand part of the work to another of JAI's specialists (the
  Agent tool). A sub-agent has only tools the lead has, through the same toolbox, so it can never exceed the lead's
  authority or folder; it cannot spawn further sub-agents, and at most three run at once.
- JAI's CHECKLIST, CHECK and REPORT: requirement_status and finish are tools here, the independent Verifier and the
  evidence report run after the session exactly as before, and the rounds, the carry-on and the allowance still work.
- MONEY: the session stops at what is left of the mission's allowance (max_budget_usd) and its cost is booked to it.
- CANCEL: every tool call first checks the mission has not been cancelled; a cancelled mission's session is stopped.

If the SDK or its Claude Code engine cannot start (not installed, no Anthropic key), JAI's own loop does the work as
before, and the reason is logged: the mission still runs. MISSION_ENGINE=jai switches the engine off.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.command.role_mission import RoleExecutor, role_tools
from app.core.config import settings

logger = logging.getLogger(__name__)

SERVER = "jai"
PREFIX = f"mcp__{SERVER}__"
# Claude Code's own tools that would act outside JAI's gates: removed from the session.
OUTSIDE_JAI = ("Bash", "BashOutput", "KillShell", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep",
               "WebSearch", "WebFetch", "Agent(fork)", "SendMessage", "Workflow", "AskUserQuestion")
# Claude Code's own tools a specialist keeps: its skills, reading a skill's files and its colleagues.
KEPT = ("Skill", "Read", "Agent", "Task")
EXTRA_TURNS = 40  # loading skills and briefing colleagues take turns of their own
MAX_WORDS_ONLY = 3
SUB_AGENTS_AT_ONCE = 3
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


def _kind(message: Any) -> str:
    return type(message).__name__


def _text(result: Any) -> str:
    text = result if isinstance(result, str) else json.dumps(result, default=str, ensure_ascii=False)
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + f"… [cut: {len(text) - TEXT_LIMIT} more characters]"


class ClaudeRoleExecutor(RoleExecutor):
    """A role's mission whose work runs on the Claude Agent SDK (see the module's notes)."""

    engine = "claude"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.engine_cost_usd = 0.0
        self.engine_note = ""
        self._lock = asyncio.Lock()
        self._client = None
        self._stop: Optional[str] = None

    # ----- the session's parts ------------------------------------------------------------------------------------

    def _skills_dir(self) -> Optional[Path]:
        """A folder for the session whose .claude/skills holds the role's trade skills (links to the installed
        packs), so Claude Code discovers them as project skills. None when no skill is installed."""
        from app.core.command.expertise import _skill_folder, trade_skills

        base = Path(tempfile.mkdtemp(prefix="jai-engine-"))
        target = base / ".claude" / "skills"
        target.mkdir(parents=True)
        linked = 0
        for entry in trade_skills(self.role):
            folder = _skill_folder(entry)
            if (folder / "SKILL.md").is_file() and not (target / entry["skill"]).exists():
                os.symlink(folder, target / entry["skill"], target_is_directory=True)
                linked += 1
        if not linked:
            shutil.rmtree(base, ignore_errors=True)
            return None
        return base

    def _agents(self, names: List[str], sdk) -> Dict[str, Any]:
        """JAI's other specialists as sub-agents of this mission. Each has only tools the lead has (through the
        same toolbox), and none of the lead's own checklist tools."""
        from app.core.command.mission_org import SPECIALISTS

        mine = set(names) - {"finish", "requirement_status"}
        out: Dict[str, Any] = {}
        for role, spec in SPECIALISTS.items():
            if role in (self.role, "builder"):
                continue
            try:
                theirs = [f"{PREFIX}{t}" for t in role_tools(role) if t in mine]
            except Exception:  # noqa: BLE001
                continue
            if not theirs:
                continue
            title = spec.get("title", role)
            out[role.replace("_", "-")] = sdk.AgentDefinition(
                description=f"JAI's {title}: {spec.get('standard', '')[:300]}",
                prompt=(f"You are JAI's {title}, one of the specialists in Richard's AI company, doing one part of a "
                        f"mission for JAI's {self.title}. {spec.get('standard', '')} Your tools are JAI's own (their "
                        f"names start {PREFIX}); you work only in the product's folder. Do the part you are given "
                        "fully, save what you make in the folder, and report back exactly what you saved and where, "
                        "and what you could not do. Never guess a fact, a contact or an address. Contact, send, post, "
                        "publish and spend nothing."),
                tools=theirs + ["Skill", "Read"],
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
        result = await super().run(mission, *args, **kwargs)
        if self.engine_note:
            result["engine"] = {"name": "claude", "model": engine_model(), "cost_usd": round(self.engine_cost_usd, 4),
                                "note": self.engine_note}
            if isinstance(result.get("role"), dict):
                result["role"]["model"] = engine_model()
        return result

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
        from app.core.command.agent_executor import MAX_REFUSED_STOPS, _blocked_or_waiting
        from app.core.command.requirements import update as update_requirement

        state = {"summary": "", "success": True, "finished": False, "settled": False, "last": None,
                 "refused": 0, "calls": 0}
        names = [t["name"] for t in tools]

        def handler(name: str):
            async def call(args: Dict[str, Any]) -> Dict[str, Any]:
                async with self._lock:  # one database session: JAI's tools run one at a time
                    return await self._one_call(name, dict(args or {}), state, total_budget, steps_per_round,
                                                start_continuation, update_requirement, MAX_REFUSED_STOPS,
                                                _blocked_or_waiting)
            return call

        jai_tools = [sdk.tool(t["name"], str(t.get("description") or t["name"])[:1000],
                              t.get("input_schema") or {"type": "object", "properties": {}})(handler(t["name"]))
                     for t in tools]
        server = sdk.create_sdk_mcp_server(name=SERVER, version="1.0.0", tools=jai_tools)

        async def guard(hook_input: Dict[str, Any], tool_use_id: Optional[str], context: Any) -> Dict[str, Any]:
            tool = str((hook_input or {}).get("tool_name") or "")
            if tool.startswith(PREFIX) or tool in KEPT:
                if self._stop:
                    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                   "permissionDecisionReason": self._stop}}
                return {}
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": (
                                               f"{tool} is not one of JAI's tools for this mission. Use the "
                                               f"{PREFIX} tools.")}}

        skills_dir = self._skills_dir()
        from app.core.knowledge.skill_packs import packs_dir

        allowance = float(getattr(settings, "ROLE_MISSION_MAX_COST_USD", 0) or 0)  # the role's allowance
        spent = self._spent_before + float(self.usage.cost_usd or 0)
        budget = max(0.05, allowance - spent) if allowance > 0 else None
        options = sdk.ClaudeAgentOptions(
            system_prompt=(system + "\n\nHOW THIS SESSION WORKS: your tools are JAI's own; their names start "
                           f"{PREFIX} (for example {PREFIX}web_search, {PREFIX}write_spreadsheet). Your skills load "
                           "with the Skill tool; Read opens a skill's own files. Your requirement list is your plan. You may "
                           "hand a self-contained part of the work to another of JAI's specialists with the Agent "
                           "tool, giving it everything it needs in the prompt and waiting for its report. Mark each "
                           f"requirement with {PREFIX}requirement_status as it is met, and end with {PREFIX}finish."),
            model=engine_model(),
            cwd=str(skills_dir) if skills_dir else tempfile.gettempdir(),
            add_dirs=[str(packs_dir())] if skills_dir else [],
            setting_sources=["project"] if skills_dir else [],
            skills="all" if skills_dir else [],
            mcp_servers={SERVER: server},
            allowed_tools=[f"{PREFIX}*", "Skill", "Read", "Agent", "Task"],
            disallowed_tools=list(OUTSIDE_JAI),
            permission_mode="dontAsk",
            hooks={"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[guard])]},
            agents=self._agents(names, sdk),
            max_turns=total_budget + EXTRA_TURNS,
            max_budget_usd=budget,
            env={"ANTHROPIC_API_KEY": api_key(), "CLAUDE_AGENT_SDK_CLIENT_APP": "jai-backend",
                 "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
                 "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": str(SUB_AGENTS_AT_ONCE)},
            stderr=lambda line: logger.debug(f"claude engine: {line}"),
        )
        prompt = messages[0].content if messages and isinstance(messages[0].content, str) else str(mission)
        self.engine_note = f"Claude Agent SDK, {engine_model()}"
        outcome = ""
        try:
            async with sdk.ClaudeSDKClient(options=options) as client:
                self._client = client
                words_only = 0
                await client.query(prompt)
                while True:
                    ended = await self._drain(client)
                    outcome = ended or outcome
                    if state["finished"] or self._stop or outcome != "success":
                        break
                    nudge = self._words_only(total_budget - self.iterations) if words_only < MAX_WORDS_ONLY else None
                    if not nudge:
                        break
                    words_only += 1
                    await client.query(nudge)
        except Exception as exc:  # noqa: BLE001
            if not state["calls"]:
                logger.warning(f"Claude engine could not start ({type(exc).__name__}: {exc}); JAI's own loop runs "
                               "the mission")
                self.engine_note = ""
                return None
            logger.warning(f"Claude engine stopped after {state['calls']} tool calls: {exc}")
            state["summary"] = state["summary"] or (f"The Claude engine stopped ({type(exc).__name__}); the work so "
                                                    "far is saved and the mission carries on from here.")
        finally:
            self._client = None
            if skills_dir:
                shutil.rmtree(skills_dir, ignore_errors=True)
        if outcome == "error_max_budget_usd":
            self.capped = True
            state["summary"] = (f"The {self.title} stopped at this mission's spending allowance. Everything written "
                                "so far is saved in the folder.")
        elif self._stop:
            state["summary"] = self._stop
        elif not state["finished"] and outcome == "success":
            # The engine ended its turn without finish and with nothing left to say: what it last said is the end.
            state["summary"] = state["summary"] or getattr(self, "_agent_said", "") or "(no further action)"
            state["finished"] = True
            state["success"] = not any(r.get("status") != "done" for r in (self.requirements or []))
        continuation = start_continuation + (self.iterations // max(1, steps_per_round))
        return (state["summary"], state["success"], state["finished"], state["settled"], continuation,
                state["last"])

    async def _drain(self, client) -> str:
        """Read the session's messages until its turn ends. Returns the result's subtype ("success",
        "error_max_turns", "error_max_budget_usd", ...)."""
        subtype = ""
        async for message in client.receive_response():
            kind = _kind(message)
            if kind == "AssistantMessage" and not getattr(message, "parent_tool_use_id", None):
                said = " ".join(str(getattr(block, "text", "") or "") for block in getattr(message, "content", [])
                                if _kind(block) == "TextBlock").strip()
                if said:
                    self._agent_said = said[:800]
            elif kind == "ResultMessage":
                self._book(message)
                subtype = str(getattr(message, "subtype", "") or "")
        return subtype

    async def _one_call(self, name, args, state, total_budget, steps_per_round, start_continuation,
                        update_requirement, max_refused, blocked_or_waiting) -> Dict[str, Any]:
        """One of JAI's tools, called by the engine: the same steps JAI's own loop takes for a call."""
        if self._stop:
            return {"content": [{"type": "text", "text": self._stop}], "is_error": True}
        if await self._cancelled():
            self._stop = "This mission was cancelled by Richard. Stop now: do nothing further."
            if self._client is not None:
                asyncio.ensure_future(self._client.interrupt())
            return {"content": [{"type": "text", "text": self._stop}], "is_error": True}
        stop = await self._over_allowance()
        if stop:
            self._stop = stop
            return {"content": [{"type": "text", "text": stop}], "is_error": True}
        self.iterations += 1
        state["calls"] += 1
        state["last"] = f"engine-{state['calls']}"
        if name == "requirement_status":
            out: Any = update_requirement(self.requirements, args)
        elif name == "finish":
            gave_up = args.get("success") is not True
            remaining = total_budget - self.iterations
            settled = gave_up and self._settles(args)
            if gave_up and not settled and remaining > 0 and state["refused"] < max_refused \
                    and not blocked_or_waiting(self.runtime.calls):
                state["refused"] += 1
                out = {"acknowledged": False, "reason": self._not_finished(remaining)}
            else:
                state.update({"summary": args.get("summary", "Mission complete."), "success": not gave_up,
                              "finished": True, "settled": settled})
                out = {"acknowledged": True, "next": "The mission is ending: say nothing more."}
        else:
            out = await self._tool_step(name, args)
            if (self.first_edit_step is None and name in ("write_file", "edit_file", "write_spreadsheet",
                                                         "tidy_spreadsheet", "fill_contacts")
                    and isinstance(out, dict) and out.get("success") is True):
                self.first_edit_step = self.iterations
        from app.core.agents.toolbox import result_limit

        text = _text(out)[:max(result_limit(name), 4000)]
        told = await self._notes()
        if told:
            text += "\n\n" + told
        continuation = start_continuation + (self.iterations // max(1, steps_per_round))
        await self._progress("working", continuation, total_budget)
        failed = isinstance(out, dict) and out.get("success") is False
        return {"content": [{"type": "text", "text": text}], "is_error": bool(failed)}
