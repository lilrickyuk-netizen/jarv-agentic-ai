"""
JARV Backend - Autonomous Agent Executor (tool-using loop)

This is the core agentic capability: given ANY mission, Claude iteratively
decides which tools to call — list/read/write files, run builds and tests —
observes each result, and keeps going until the mission is done or a boundary
is hit. This is what lets JARV inspect a repo, edit code, run the build, read
the error, fix it, and re-run, scoped to an approved workspace.

The mission works with the same toolbox every specialist agent uses (AgentToolbox): reading,
searching and editing files, folders, git, project detection, builds and tests, package installs,
registry and vulnerability checks, workspace memory, web reads and specialist knowledge, all on the
mission's own ToolRuntime, so one rulebook, one authority level and one log apply. Deleting and
pushing are offered through their boundary tools and pause for Richard's approval.

Safety is enforced by the tool layer (ToolRuntime + fs_inspector):
  * file writes are scoped to the approved workspace; secrets/out-of-scope blocked,
  * commands are classified — read-only, build/test, local git and installs from the official
    registries (inside the workspace or into JARV's tool home) run; delete/deploy/push, chaining,
    sudo and global installs are blocked,
  * every tool call is authority-checked, logged to audit + the operations feed,
    and recorded on the task (visible in task detail).
"""
from __future__ import annotations

import json
from pathlib import PurePosixPath, PureWindowsPath
import logging
from typing import Any, Dict, List, Optional

from types import SimpleNamespace

from app.core.agents.toolbox import BROKEN_ARGUMENTS, WORKSPACE_TOOLS, AgentToolbox, _clip, result_limit
from app.core.config import settings
from app.core.providers import CompletionRequest, Message, get_router

logger = logging.getLogger(__name__)

# Every workspace tool, for the mission. Memory links act on other records and stay with the Memory Agent.
MISSION_TOOLS = tuple(sorted(name for name in WORKSPACE_TOOLS
                             if name not in ("memory_link_to_workspace", "memory_link_to_task")))


class MissionLead:
    """The agent identity a mission's toolbox acts as: JARV's orchestrator, at the mission's authority."""

    name = "orchestrator"

    def __init__(self, runtime):
        from app.core.agents.base import AuthorityLevel

        level = max(0, min(int(getattr(runtime, "authority_level", 3) or 3), 10))
        self.config = SimpleNamespace(agent_id=getattr(runtime, "agent_id", None), authority_level=AuthorityLevel(level))

    def get_allowed_tools(self) -> List[str]:
        return list(MISSION_TOOLS)


def mission_toolbox(runtime, root_host: Optional[str], *, approval_granted: bool = False,
                    approved_tools: Optional[List[str]] = None) -> AgentToolbox:
    """The full toolbox on ``runtime``, confined to ``root_host`` (or the workspace's own folder)."""
    context = SimpleNamespace(
        db_session=runtime.db, workspace_id=runtime.workspace_id, task_id=runtime.task_id,
        user_id=runtime.user_id, session_id=runtime.session_id, approval_granted=approval_granted,
        approved_tools=list(approved_tools or []))
    return AgentToolbox(MissionLead(runtime), context, runtime=runtime, root_host=root_host)


_FINISH = {
    "name": "finish",
    "description": ("Call when the whole mission is done and verified, or when it cannot proceed. "
                    "Provide a summary. Set success to true only when every part of the mission is "
                    "done and verified; anything not done, failing or blocked means false."),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "success": {"type": "boolean",
                        "description": "true only when every part of the mission is done and verified"},
        },
        "required": ["summary", "success"],
    },
}


# The independent check: tools that look and test, never ones that write, delete, push or install.
VERIFIER_TOOLS = ("list_files", "read_file", "search_files", "scan_workspace", "get_file_metadata",
                  "detect_stack", "detect_commands", "find_missing_files", "check_installed", "run_command",
                  "run_build", "run_tests", "git_status", "git_diff", "git_log", "get_command_log",
                  "consult_specialist_knowledge")
VERIFIER_STEPS = 16

_VERDICT = {
    "name": "verdict",
    "description": "Call once with your verdict after checking every requirement of the mission yourself.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verified": {"type": "boolean",
                         "description": "true only when every requirement is met and you saw the evidence yourself"},
            "checks": {"type": "array", "items": {"type": "object", "properties": {
                "requirement": {"type": "string"}, "met": {"type": "boolean"},
                "evidence": {"type": "string", "description": "What you read or ran that shows it"}},
                "required": ["requirement", "met", "evidence"]}},
            "unmet": {"type": "array", "items": {"type": "string"},
                      "description": "Each requirement not met, with what is wrong and where"},
        },
        "required": ["verified", "checks", "unmet"],
    },
}

_VERIFIER_SYSTEM = (
    "You are JARV's Verifier Agent. Another agent says it has completed the mission below. You did not do "
    "the work and you do not take its word for anything: check every requirement of the mission against the "
    "workspace yourself, with the tools, and decide whether it is really done. Read the files the mission "
    "names. Run the project's real checks (build, tests, lint, type-check, the project's own verify task) "
    "and read their output. A command that exits 0 but does nothing (an echo, a script that only prints "
    "that it passed, an empty test suite) is not evidence. A file that exists but holds stand-in content "
    "is not done. A requirement the mission states that you cannot find evidence for is unmet. Do not "
    "change any file. Use one plain command per run_command call. When you have checked everything, call "
    "verdict: verified=true only when every requirement is met and you saw the evidence yourself; list "
    "each unmet requirement precisely (what is wrong, which file or command) so the next round can fix it."
)


# Long missions: every step re-sends the conversation, so old tool results are cut down once the
# conversation passes this size. The newest results stay whole; older ones keep a head and say what to
# call again. Cutting happens in one batch when the limit is crossed, so the conversation's opening stays
# the same between cuts and the provider's prompt cache keeps working.
CONTEXT_BUDGET_CHARS = 240_000
KEEP_RECENT_RESULTS = 6
_ELIDED_HEAD = 400


def compact_messages(messages: List[Any], budget: int = CONTEXT_BUDGET_CHARS,
                     keep_recent: int = KEEP_RECENT_RESULTS) -> int:
    """Shorten old tool results in place when the conversation is over ``budget`` characters.
    Returns the number of characters removed. Tool calls and their pairing are never touched."""
    def size(message: Any) -> int:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return len(content)
        return sum(len(str(block.get("content") or block.get("text") or block.get("input") or ""))
                   for block in content if isinstance(block, dict))

    if sum(size(m) for m in messages) <= budget:
        return 0
    calls: Dict[str, str] = {}
    for message in messages:
        content = getattr(message, "content", None)
        if getattr(message, "role", "") == "assistant" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    args = block.get("input") or {}
                    target = args.get("path") or args.get("command") or args.get("contains") or args.get("pattern") or ""
                    calls[str(block.get("id"))] = f"{block.get('name')} {str(target)[:160]}".strip()
    result_messages = [m for m in messages if getattr(m, "role", "") == "user" and isinstance(m.content, list)
                       and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m.content)]
    removed = 0
    for message in result_messages[:-keep_recent] if keep_recent else result_messages:
        for block in message.content:
            if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                continue
            text = block.get("content")
            if not isinstance(text, str) or len(text) <= _ELIDED_HEAD + 200 or "[earlier result cut" in text:
                continue
            what = calls.get(str(block.get("tool_use_id")), "the tool")
            block["content"] = (text[:_ELIDED_HEAD] + f"… [earlier result cut to save context: {len(text):,} "
                                f"characters from {what}. Call it again if you need the rest.]")
            removed += len(text) - len(block["content"])
    return removed


def _claims(runtime_calls: List[Dict[str, Any]]) -> str:
    """The agent's own trail, as facts the verifier checks rather than trusts: files written, last result
    of each command, and anything still waiting for approval."""
    written: List[str] = []
    last: Dict[str, str] = {}
    waiting: List[str] = []
    for call in runtime_calls:
        if not isinstance(call, dict):
            continue
        inputs = call.get("inputs") if isinstance(call.get("inputs"), dict) else {}
        tool = call.get("tool")
        if tool == "write_file" and inputs.get("path") and call.get("success"):
            if inputs["path"] not in written:
                written.append(str(inputs["path"]))
        elif tool == "run_command" and inputs.get("command"):
            output = call.get("output") if isinstance(call.get("output"), dict) else {}
            code = output.get("exit_code")
            last[str(inputs["command"])[:200]] = f"exit {code}" if code is not None else (
                "ok" if call.get("success") else "did not run")
        if str(call.get("summary") or "").startswith("paused for approval"):
            waiting.append(str(inputs.get("display") or tool)[:200])
    lines: List[str] = []
    if written:
        lines.append("Files it wrote: " + ", ".join(written[-60:]))
    if last:
        lines.append("Last result of each command it ran:")
        lines += [f"- `{command}`: {outcome}" for command, outcome in list(last.items())[-60:]]
    if waiting:
        lines.append("Waiting for Richard's approval: " + ", ".join(dict.fromkeys(waiting)))
    return "\n".join(lines)


def _tool_schemas() -> List[Dict[str, Any]]:
    """The four core tools, used only when the full toolbox cannot be prepared (no workspace record)."""
    return [
        {
            "name": "list_files",
            "description": "List files and folders at a path inside the approved workspace.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path inside the workspace, relative to its folder (e.g. docs) or absolute"}},
                "required": ["path"],
            },
        },
        {
            "name": "read_file",
            "description": ("Read a file (secret files are redacted), up to 16,000 characters from offset. When "
                            "next_offset is not null the file continues: call again with that offset until it is "
                            "null, and read the whole file before relying on it."),
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"},
                               "offset": {"type": "integer", "description": "Character offset (0 = start)"}},
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": ("Create or edit a file inside the approved workspace (Level 2). "
                            "Writes outside scope or to secret files are blocked. Write a long file in parts: "
                            "the first part without append, each further part with append=true."),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path inside the workspace (e.g. docs/x.md)"},
                    "content": {"type": "string", "description": "The file contents, or the part to add"},
                    "append": {"type": "boolean", "description": "Add content to the end of the file"},
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "run_command",
            "description": ("Run a read-only or build/test command inside the workspace "
                            "(Level 3). Destructive/install/network/deploy/push commands are "
                            "blocked; captures stdout/stderr/exit code."),
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string", "description": "Workspace path to run in"},
                },
                "required": ["command"],
            },
        },
        _FINISH,
    ]


class AgentExecutor:
    """Runs the Claude tool-use loop against the real tool runtime."""

    def __init__(self, runtime, model: str, workspace_root: Optional[str]):
        self.runtime = runtime
        # The agent keeps working while one of its commands waits for Richard, so a paused
        # command must not put the whole mission into waiting_on_approval: the mission owns its
        # own status and records its outcome when it ends.
        self.runtime.pause_task_on_boundary = False
        self.model = model
        self.workspace_root = workspace_root
        self.iterations = 0
        self.tokens = 0
        self.toolbox: Optional[AgentToolbox] = None
        self.context_trimmed = 0

    async def _prepare_tools(self) -> List[Dict[str, Any]]:
        """The full mission toolbox; the four core tools only when there is no workspace record to confine to."""
        try:
            toolbox = mission_toolbox(self.runtime, self.workspace_root)
            await toolbox.prepare()
        except Exception as exc:  # noqa: BLE001 - no workspace: the core tools still enforce every rule
            logger.info(f"mission toolbox unavailable, using the core tools: {exc}")
            return _tool_schemas()
        self.toolbox = toolbox
        if toolbox.root_host and not self.workspace_root:
            self.workspace_root = toolbox.root_host
        return toolbox.model_tools() + [_FINISH]

    async def run(self, mission: str, steps_per_round: int = 8,
                  max_continuations: int = 4,
                  prior_messages: Optional[List[Message]] = None,
                  start_continuation: int = 0,
                  known: Optional[str] = None,
                  verify: bool = True) -> Dict[str, Any]:
        """
        Run the tool loop with AUTO-CONTINUATION. The same conversation (and thus
        every prior tool result) is preserved across continuation rounds — the
        mission is never restarted. Stops only on a real terminal state:
        finished (completed), stalled/no-tools, or the continuation cap reached
        (-> needs_continuation, with a checkpoint to resume from).
        """
        router = get_router()
        tools = await self._prepare_tools()
        names = {tool["name"] for tool in tools}
        full = self.toolbox is not None
        system = (
            "You are JARV, an autonomous software engineer operating a real machine. "
            "You complete the operator's mission by USING TOOLS — inspect files, edit "
            "code, run builds and tests — iterating until the mission is genuinely done. "
            f"You operate ONLY inside the approved workspace"
            + (f" rooted at `{self.workspace_root}`. " if self.workspace_root else ". ")
            + "Paths may be relative to that folder. "
            + ("YOUR TOOLS: search_files to find code by name or content, read_file, edit_file for a change "
               "to part of a file (prefer it to rewriting the file), write_file for new files, create_folder, "
               "move_file and copy_file inside the workspace, detect_stack and detect_commands to learn the "
               "project's real install/build/test commands, run_build, run_tests, install_package, "
               "check_installed, run_command, git_status, git_diff, git_log, git_create_branch, "
               "check_package_registry and check_cve before adding a dependency, fetch_url for public "
               "documentation, memory_search for what JARV already knows about this workspace, memory_add "
               "for decisions and lessons worth keeping, and consult_specialist_knowledge for reference "
               "material in your field. Deleting (delete_file_with_boundary) and pushing "
               "(git_push_with_boundary) pause for Richard's approval: ask for them only when the mission "
               "needs them, then carry on with the rest. "
               if full else
               "Make real changes with write_file and verify with run_command. You cannot delete or push. ")
            + "Deploys and releases need Richard's approval. "
            "MACHINE: git, Node 24 with npm and Corepack (pnpm and yarn at the version a project pins), Python 3.11 to "
            "3.14 with uv (uv fetches any exact Python a project pins), Task, Terraform, Helm, gcc and make, "
            "jq, rg. If a project needs another tool, install it yourself from the official "
            "registries: `uv tool install <package>` (e.g. semgrep), `uv python install <version>`, "
            "`pnpm add -D <package>` or `npm install -D <package>` in the project, `npx <tool>`. "
            "Tools you install stay installed. Never ask the operator to install a tool for you. "
            "COMMAND RULES: run ONE plain command per call. Shell chaining, pipes, redirection and "
            "expansion (&&, ;, |, >, 2>&1, $VAR, $(...), backticks, `cd X && ...`) are refused; quoted "
            "arguments are fine (git commit -m \"any message\"). Use cwd for a sub-folder. "
            "To verify Python, use `python3 -m py_compile <file>` or a test command. "
            "If a command is blocked or 'requires approval', do NOT retry the same command — "
            "continue with the rest of the mission and report what is waiting. "
            "Never claim something was done or verified unless a tool result in this conversation shows it. "
            "When the WHOLE mission is done, call finish."
        )
        # Resume: keep the prior conversation if provided (no restart, no lost work).
        messages: List[Message] = prior_messages if prior_messages else [
            Message(role="user", content=(
                f"MISSION:\n{mission}\n\n"
                + (f"Approved workspace root: {self.workspace_root}\n" if self.workspace_root else "")
                + (f"\nWHAT JARV ALREADY KNOWS (from its memory and verified lessons for this workspace; "
                   f"check it against the files before relying on it):\n{known}\n\n" if known else "")
                + "Begin by inspecting what you need, then act. Call finish when the whole "
                "mission is complete and verified."))]

        final_summary = ""
        success = True
        finished = False
        last_tool = None
        continuation = start_continuation
        total_budget = steps_per_round * (max_continuations + 1)

        while self.iterations < total_budget and not finished:
            self.iterations += 1
            # Continuation boundary: nudge the model to keep going from where it is.
            if self.iterations > steps_per_round and (self.iterations - 1) % steps_per_round == 0:
                continuation += 1
                messages.append(Message(role="user", content=(
                    f"[CONTINUATION {continuation}] You have not called finish yet. Continue the "
                    f"SAME mission from your current progress (files already written persist). "
                    f"Do the remaining work and call finish when the whole mission is verified.")))
            self.context_trimmed += compact_messages(messages)
            resp = await router.complete(CompletionRequest(
                model=self.model, messages=messages, system=system,
                tools=tools, max_tokens=settings.AGENT_MAX_OUTPUT_TOKENS, temperature=0.0,
            ))
            self.tokens += (resp.usage or {}).get("total_tokens", 0)

            if not resp.tool_calls:
                # Model produced a final answer without finish -> treat as done.
                final_summary = resp.content.strip() or "(no further action)"
                finished = True
                break

            assistant_blocks: List[Dict[str, Any]] = []
            if resp.content:
                assistant_blocks.append({"type": "text", "text": resp.content})
            parsed: List[Dict[str, Any]] = []
            for tc in resp.tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                    broken = not isinstance(args, dict)
                except Exception:  # noqa: BLE001
                    args, broken = {}, True
                assistant_blocks.append({"type": "tool_use", "id": tc["id"], "name": name,
                                         "input": args if isinstance(args, dict) else {}})
                parsed.append({"id": tc["id"], "name": name, "args": args if isinstance(args, dict) else {},
                               "broken": broken})
            messages.append(Message(role="assistant", content=assistant_blocks))

            result_blocks: List[Dict[str, Any]] = []
            for call in parsed:
                last_tool = call["id"]
                if call.get("broken"):
                    out = {"success": False, "error": BROKEN_ARGUMENTS.format(name=call["name"])}
                elif call["name"] == "finish":
                    final_summary = call["args"].get("summary", "Mission complete.")
                    # A finish that does not say it succeeded is not a success.
                    success = call["args"].get("success") is True
                    finished = True
                    out = {"acknowledged": True}
                else:
                    out = await self._dispatch(call["name"], call["args"])
                result_blocks.append({"type": "tool_result", "tool_use_id": call["id"],
                                      # A read_file part is passed back whole; other results are clipped.
                                      "content": _clip(out, result_limit(call["name"]))})
            messages.append(Message(role="user", content=result_blocks))

        needs_continuation = not finished
        if needs_continuation:
            final_summary = (final_summary or
                             "Reached the continuation cap before the mission self-reported finish.")
            success = False

        # A mission never accepts itself: when it says it is done, an independent check decides.
        verification: Optional[Dict[str, Any]] = None
        if finished and success and verify:
            verification = await self.verify(mission, final_summary)
            if not verification["verified"]:
                success = False
                unmet = verification.get("unmet") or ["The independent check did not confirm the mission."]
                final_summary += ("\n\n**Independent check: not complete yet.**\n"
                                  + "\n".join(f"- {item}" for item in unmet))
                # The mission goes on to fix what the check found (within the automatic-round cap).
                needs_continuation = True

        return {
            "answer": final_summary,
            "iterations": self.iterations,
            "success": success and finished,
            "finished": finished,
            "needs_continuation": needs_continuation,
            "step_limit_reached": needs_continuation and not finished,
            "verification": verification,
            "continuation_count": continuation,
            "resume_from_step": self.iterations,
            "remaining_steps": max(0, total_budget - self.iterations),
            "last_tool_call_id": last_tool,
            "tokens": self.tokens,
            "tools": sorted(names),
            "context_trimmed_chars": self.context_trimmed,
            "messages": messages,  # checkpoint payload for resume
        }

    async def verify(self, mission: str, summary: str) -> Dict[str, Any]:
        """Check the mission with a separate agent that did not do the work: fresh conversation, its own
        runtime and log entries (operator agent:verifier), look-and-test tools only, no approval requests."""
        from app.core.command.tool_runtime import ToolRuntime

        runtime = ToolRuntime(self.runtime.db, self.runtime.workspace_id, self.runtime.task_id,
                              operator="agent:verifier", authority_level=self.runtime.authority_level,
                              user_id=self.runtime.user_id, session_id=self.runtime.session_id,
                              open_boundary_flows=False)
        runtime.pause_task_on_boundary = False
        toolbox = mission_toolbox(runtime, self.workspace_root)
        try:
            await toolbox.prepare()
        except Exception as exc:  # noqa: BLE001
            return {"verified": False, "checks": [], "tokens": 0, "steps": 0,
                    "unmet": [f"The independent check could not open the workspace: {exc}"]}
        toolbox.withhold([name for name in toolbox.available if name not in VERIFIER_TOOLS])
        tools = toolbox.model_tools() + [_VERDICT]
        trail = _claims(self.runtime.calls)
        messages: List[Message] = [Message(role="user", content=(
            f"MISSION:\n{mission}\n\nWorkspace folder: {self.workspace_root or toolbox.root_host}\n\n"
            f"WHAT THE OTHER AGENT REPORTED (claims to check, not facts):\n{summary[:4000]}\n\n"
            + (f"ITS RECORDED ACTIONS:\n{trail}\n\n" if trail else "")
            + "Check every requirement yourself, then call verdict."))]
        router = get_router()
        tokens = steps = 0
        verdict: Optional[Dict[str, Any]] = None
        while steps < VERIFIER_STEPS and verdict is None:
            steps += 1
            compact_messages(messages)
            resp = await router.complete(CompletionRequest(
                model=self.model, messages=messages, system=_VERIFIER_SYSTEM, tools=tools,
                max_tokens=settings.AGENT_MAX_OUTPUT_TOKENS, temperature=0.0))
            tokens += int((resp.usage or {}).get("total_tokens", 0) or 0)
            if not resp.tool_calls:
                break
            blocks: List[Dict[str, Any]] = [{"type": "text", "text": resp.content}] if resp.content else []
            results: List[Dict[str, Any]] = []
            for tc in resp.tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except Exception:  # noqa: BLE001
                    args = None
                blocks.append({"type": "tool_use", "id": tc["id"], "name": name,
                               "input": args if isinstance(args, dict) else {}})
                if not isinstance(args, dict):
                    out: Any = {"success": False, "error": BROKEN_ARGUMENTS.format(name=name)}
                elif name == "verdict":
                    verdict = args
                    out = {"acknowledged": True}
                else:
                    out = await toolbox.call(name, args)
                results.append({"type": "tool_result", "tool_use_id": tc["id"],
                                "content": _clip(out, result_limit(name))})
            messages.append(Message(role="assistant", content=blocks))
            messages.append(Message(role="user", content=results))
        self.tokens += tokens
        if verdict is None:
            return {"verified": False, "checks": [], "tokens": tokens, "steps": steps,
                    "unmet": [f"The independent check did not reach a verdict in {steps} steps."]}
        checks = [c for c in (verdict.get("checks") or []) if isinstance(c, dict)][:60]
        unmet = [str(u)[:500] for u in (verdict.get("unmet") or []) if str(u).strip()][:30]
        unmet += [f"{c.get('requirement')}: {c.get('evidence')}"[:500] for c in checks
                  if c.get("met") is False and not any(str(c.get("requirement")) in u for u in unmet)]
        # Verified means the verifier said so AND none of its own checks failed.
        verified = verdict.get("verified") is True and not unmet and bool(checks)
        if verdict.get("verified") is True and not checks:
            unmet = ["The independent check reported no evidence for any requirement."]
        return {"verified": verified, "checks": checks, "unmet": unmet, "tokens": tokens, "steps": steps}

    def _host(self, value: Any) -> str:
        """A tool path as a host path: relative paths ("docs/x.md", "/docs/x.md" under a Windows folder)
        resolve from the workspace root, absolute paths are used as given (the runtime enforces scope)."""
        raw = str(value or "").strip().strip('"').strip("'")
        root = self.workspace_root
        if not root:
            return raw
        windows_root = ":" in root[:3] or "\\" in root
        if not raw or raw in (".", "./"):
            return root
        if windows_root:
            if ":" in raw[:3]:
                return raw
            return str(PureWindowsPath(root) / PureWindowsPath(raw.replace("/", "\\").lstrip("\\")))
        if raw.startswith("/"):
            return raw
        return str(PurePosixPath(root) / raw)

    async def _dispatch(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if self.toolbox is not None:
            return await self.toolbox.call(name, args)  # never raises; refusals come back as results
        try:
            if name == "list_files":
                return await self.runtime.list_files(self._host(args.get("path")))
            if name == "read_file":
                try:
                    offset = max(0, int(args.get("offset") or 0))
                except (TypeError, ValueError):
                    offset = 0
                return await self.runtime.read_file(self._host(args.get("path")), offset=offset)
            if name == "write_file":
                if not str(args.get("path") or "").strip():
                    return {"success": False, "error": "write_file needs the path of the file to write."}
                return await self.runtime.write_file(self._host(args.get("path")), args.get("content", ""),
                                                     overwrite=True, append=bool(args.get("append")))
            if name == "run_command":
                return await self.runtime.run_command(
                    args.get("command", ""), cwd_host=self._host(args.get("cwd")),
                    allow_build=True)
            return {"error": f"unknown tool '{name}'"}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"agent tool '{name}' failed: {exc}")
            return {"error": str(exc)}
