"""
JAI Backend - Autonomous Agent Executor (tool-using loop)

This is the core agentic capability: given ANY mission, Claude iteratively
decides which tools to call — list/read/write files, run builds and tests —
observes each result, and keeps going until the mission is done or a boundary
is hit. This is what lets JAI inspect a repo, edit code, run the build, read
the error, fix it, and re-run, scoped to an approved workspace.

The mission works with the same toolbox every specialist agent uses (AgentToolbox): reading,
searching and editing files, folders, git, project detection, builds and tests, package installs,
registry and vulnerability checks, workspace memory, web reads and specialist knowledge, all on the
mission's own ToolRuntime, so one rulebook, one authority level and one log apply. Deleting and
pushing are offered through their boundary tools and pause for Richard's approval.

Safety is enforced by the tool layer (ToolRuntime + fs_inspector):
  * file writes are scoped to the approved workspace; secrets/out-of-scope blocked,
  * commands are classified — read-only, build/test, local git and installs from the official
    registries (inside the workspace or into JAI's tool home) run; delete/deploy/push, chaining,
    sudo and global installs are blocked,
  * every tool call is authority-checked, logged to audit + the operations feed,
    and recorded on the task (visible in task detail).
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import logging
from typing import Any, Dict, List, Optional

from types import SimpleNamespace

from app.core.command.stuck import StuckDetector
from app.core.agents.toolbox import BROKEN_ARGUMENTS, WORKSPACE_TOOLS, AgentToolbox, _clip, result_limit
from app.core.config import settings
from app.core.providers import CompletionRequest, Message, get_router
from app.core.command.requirements import (STATUS_TOOL, derive as derive_requirements, render as render_requirements,
                                           unmet_without_evidence, update as update_requirement)
from app.core.verification.checks import Finding
from app.core.command.metrics import MeteredRouter, Usage

logger = logging.getLogger(__name__)

# The watchdog on each step (a mission stalled for twelve minutes on one step): how long one model call and one tool
# call may take before they are abandoned. A tool's own command timeout comes first; this catches the rest.
MODEL_STEP_SECONDS = 900
TOOL_STEP_SECONDS = max(1200, int(getattr(settings, "AGENT_LONG_COMMAND_TIMEOUT_SECONDS", 900) or 900) + 300)

# Every workspace tool, for the mission. Memory links act on other records and stay with the Memory Agent.
MISSION_TOOLS = tuple(sorted(name for name in WORKSPACE_TOOLS
                             if name not in ("memory_link_to_workspace", "memory_link_to_task")))


class MissionLead:
    """The agent identity a mission's toolbox acts as: JAI's orchestrator, at the mission's authority."""

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


# Tools whose success counts as the mission's first change (Upgrade 5 measures steps until the first edit).
_EDITS = ("write_file", "edit_file", "move_file", "copy_file", "create_folder", "delete_file_with_boundary")

# The independent check: tools that look and test, never ones that write, delete, push or install.
VERIFIER_TOOLS = ("list_files", "read_file", "search_files", "scan_workspace", "get_file_metadata",
                  "detect_stack", "detect_commands", "find_missing_files", "check_installed", "run_command",
                  "run_build", "run_tests", "git_status", "git_diff", "git_log", "get_command_log",
                  "consult_specialist_knowledge", "trace_artifact")
# What JAI's machine has, given to every mission and every round, so no step is spent finding out and no tool is
# mistaken for missing. Keep it in step with apps/backend/Dockerfile.
TOOLCHAIN = (
    "YOUR TOOLCHAIN (installed, on PATH): git, Node 24 with npm, pnpm and yarn (each project's version through "
    "Corepack), uv with Python 3.12, 3.13 and 3.14, Go 1.26, Java 25 (Temurin) with Maven and Gradle, Task, "
    "Terraform, Helm, Syft (SBOMs: syft scan dir:. -o cyclonedx-json=<file>), Trivy (licences, vulnerabilities "
    "and secrets in the workspace: trivy fs --scanners license,vuln,secret .), Gitleaks (secrets: gitleaks dir .), "
    "jq, ripgrep, gcc and make. ANY OTHER LANGUAGE OR VERSION: install it with mise, from official sources into "
    "your tool home (never into the project): 'mise install rust@1.96', 'mise install dotnet@10', 'mise install "
    "ruby@3', 'mise install go@1.24' when a project pins another version; a project's own mise.toml or "
    ".tool-versions is installed with 'mise install'. Run a mise-installed tool with 'mise exec <tool>@<version> "
    "-- <command>' (for example 'mise exec rust@1.96 -- cargo build'). A tool you need is never a blocker: install "
    "it and carry on. Only something that needs Richard (a paid account, a licence key, a password) is a "
    "blocker. There is no Docker inside missions."
)

VERIFIER_STEPS = 16  # the fewest steps the independent check gets


def verifier_steps(requirement_count: int) -> int:
    """Steps for the independent check: enough to look at every requirement (about three each: read, run, read the
    output) and give its verdict; 16 at least, 48 at most. A fixed 16 ran out before a verdict on a nine-requirement
    mission, and a check with no verdict sent the mission round again for nothing."""
    return min(48, max(VERIFIER_STEPS, 8 + 3 * max(0, int(requirement_count or 0))))

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
    "You are JAI's Verifier Agent. Another agent says it has completed the mission below. You did not do "
    "the work and you do not take its word for anything: check every requirement of the mission against the "
    "workspace yourself, with the tools, and decide whether it is really done. Read the files the mission "
    "names. For .xlsx files use read_file to inspect sheets and rows; never use head, cat or other commands "
    "to dump raw workbook bytes. Run the project's real checks (build, tests, lint, type-check, the project's own verify task) "
    "and read their output. A command that exits 0 but does nothing (an echo, a script that only prints "
    "that it passed, an empty test suite) is not evidence. A file that exists but holds stand-in content "
    "is not done. A requirement the mission states that you cannot find evidence for is unmet. Do not "
    "change any file. Use one plain command per run_command call. When you have checked everything, call "
    "verdict: verified=true only when every requirement is met and you saw the evidence yourself; list "
    "each unmet requirement precisely (what is wrong, which file or command) so the next round can fix it.\n"
    "Judge each requirement by evidence that can exist. Requirements about how the work was done (staying in "
    "scope, the order of steps, committing in clear steps, not pushing) are shown by the repository itself: "
    "git log, git show --stat, git status and git diff, and by the recorded actions you are given. Do not mark "
    "one unmet for want of a proof no file or command could give (a timeline of the agent's thinking, proof "
    "that nothing else was ever considered). A requirement that the mission give a report is met by the report "
    "above when it covers every requirement with evidence. A project task that takes minutes (a verify or test "
    "task) may be run; if it cannot finish, run its parts and say so. You have a limited number of steps: check "
    "the requirements in order, keep notes as you go, and call verdict before you run out, with met=false and "
    "the reason for anything you could not check."
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


# How many times one run sends back a finish that gives up with nothing blocking it.
MAX_REFUSED_STOPS = 2
MAX_WORDS_ONLY = 3  # replies in words, with work open, that a role's agent is sent back to work from


def _blocked_or_waiting(runtime_calls: List[Dict[str, Any]]) -> bool:
    """Whether anything in this run is waiting for Richard (a refused shell form is not a reason to stop:
    there is always a plain command or a file tool for it)."""
    return any(isinstance(c, dict) and str(c.get("summary") or "").startswith("paused for approval")
               for c in runtime_calls)


def evidence_calls(earlier: Optional[List[Dict[str, Any]]], current: List[Dict[str, Any]],
                   limit: int = 220) -> List[Dict[str, Any]]:
    """Every round's actions as one evidence trail: earlier rounds' calls then this round's, keeping only the
    latest of each repeated action (the same command or file), so a requirement proven in round 3 can still be
    cited in round 9 and the trail stays short. Approval pauses are kept as they are."""
    def key(call: Dict[str, Any]) -> Optional[tuple]:
        inputs = call.get("inputs") if isinstance(call.get("inputs"), dict) else {}
        target = inputs.get("command") or inputs.get("path") or inputs.get("destination") or inputs.get("query")
        if str(call.get("summary") or "").startswith("paused for approval"):
            return None
        return (call.get("tool"), str(target)[:300]) if target else None

    calls = [c for c in list(earlier or []) + list(current or []) if isinstance(c, dict)]
    latest: Dict[tuple, int] = {}
    for index, call in enumerate(calls):
        k = key(call)
        if k is not None:
            latest[k] = index
    kept = [c for i, c in enumerate(calls) if (key(c) is None or latest[key(c)] == i)]
    return kept[-limit:]


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
        self.stuck_loops = 0  # times the mission was told it was going round in circles (Wave 5)
        self.hard_baseline: Optional[set] = None  # hard-check findings when the mission started
        self.usage = Usage()  # every model call's tokens and cost (Upgrade 5)
        self.first_edit_step: Optional[int] = None
        self.requirements: List[Dict[str, Any]] = []  # the numbered requirement list (Upgrade 2)
        self._started_at: Optional[str] = None
        self._round: tuple = (0, 0)  # the round and step allowance of the latest progress record
        self.prior_calls: List[Dict[str, Any]] = []  # earlier rounds' actions, evidence for this round's report

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

    async def _progress(self, phase: str, continuation: int, budget: int,
                        check: Optional[Dict[str, Any]] = None) -> None:
        """The mission's live progress record, after every step (read by "how is it going?")."""
        from datetime import datetime, timezone

        from app.core.command import progress

        if self._started_at is None:
            self._started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._round = (continuation, budget)
        record = progress.snapshot(
            self.runtime.calls, self.requirements, round_no=continuation + 1, step=self.iterations,
            step_budget=budget, phase=phase, usage=self.usage.summary(), started_at=self._started_at,
            root=self.workspace_root, check=check, agent_said=getattr(self, "_agent_said", None))
        record.update(self._progress_extra())
        await progress.save(self.runtime.task_id, record)

    def _progress_extra(self) -> Dict[str, Any]:
        """More for the progress record (a mission run by a team adds the team)."""
        return {}

    def _system_prompt(self, full: bool) -> str:
        """Who the mission's agent is and how it works (a role's agent says its own; see role_mission)."""
        return (
            "You are JAI, an autonomous software engineer operating a real machine. " + TOOLCHAIN + " "
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
               "check_package_registry and check_cve before adding a dependency, web_search to find "
               "current documentation, releases and fixes for an error, research_web for a cited answer to a "
               "question that needs several sources, fetch_url to read a page, read_mission_report to read an "
               "earlier mission's whole report, code_overview, code_find_symbol, code_references, "
               "code_implementations and code_diagnostics to understand code as an IDE does (definitions, "
               "callers, errors) before and after changing it, read_document for PDFs, Word, PowerPoint and "
               "Excel files, use_browser to click through a site like a visitor (follow its links, its sign-up "
               "and waitlist flows), knowledge_graph_search and knowledge_graph_add for what JAI's work here has "
               "established, recall_richard for what Richard has said he wants, generate_image to make an image on "
               "JAI's own GPU (saved in assets/images with its licence recorded), make_voiceover for narration in "
               "JAI's own voice, make_video for a short narrated, subtitled video, social_channels and "
               "social_draft to draft posts in Postiz for Richard to schedule (JAI never publishes), memory_search for what JAI already knows about this workspace, memory_add "
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

    def _reminder(self) -> Optional[str]:
        """A word to the agent between steps (a role's agent is reminded to save what it has found), or None."""
        return None

    def _words_only(self, remaining: int) -> Optional[str]:
        """What the agent is told when it replies in words, without a tool, while work is open; None when such a
        reply ends the mission (the base mission; a role's agent is sent back to work, see role_mission)."""
        return None

    def _not_finished(self, remaining: int) -> str:
        """What the agent is told when it stops short with nothing in its way (a role's agent is told in its own
        trade's terms; see role_mission)."""
        return (f"Not accepted yet: nothing is blocked or waiting for approval, and you have "
                f"{remaining} steps left. Reading is not progress: make the changes the mission "
                f"asks for, verify them with real commands, then call finish. If something truly "
                f"stops you (a hard boundary, or a credential or decision only Richard can give), "
                f"call finish again and name it; then the rest is reported as waiting on him.")

    async def _notes(self) -> Optional[str]:
        """What Richard has said about this mission since the last step (command/steer), or None. A role's agent
        reads its notes; the base mission has none."""
        return None

    async def _over_allowance(self) -> Optional[str]:
        """Why the mission must stop spending now (its allowance is used), or None. The base mission has no allowance
        of its own here: its team and the daily limit guard it."""
        return None

    async def run(self, mission: str, steps_per_round: int = 8,
                  max_continuations: int = 4,
                  prior_messages: Optional[List[Message]] = None,
                  start_continuation: int = 0,
                  known: Optional[str] = None,
                  verify: bool = True,
                  requirements: Optional[List[Dict[str, Any]]] = None,
                  prior_calls: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Run the tool loop with AUTO-CONTINUATION. The same conversation (and thus
        every prior tool result) is preserved across continuation rounds — the
        mission is never restarted. Stops only on a real terminal state:
        finished (completed), stalled/no-tools, or the continuation cap reached
        (-> needs_continuation, with a checkpoint to resume from).
        """
        router = MeteredRouter(get_router(), self.usage, "mission", self._cache_key())
        tools = await self._prepare_tools()
        self.prior_calls = [c for c in (prior_calls or []) if isinstance(c, dict)]
        if not prior_messages:
            standing = await self.hard_checks()
            # The baseline is what the workspace held when the mission started: a team's lead keeps the one taken
            # before its specialists changed anything.
            if standing is not None and self.hard_baseline is None:
                self.hard_baseline = {f["check"] + "|" + f["file"] + "|" + f["detail"]
                                      for f in standing["findings"]}
            if standing and standing.get("findings"):
                from app.core.verification.checks import render_findings

                known = (f"{known}\n\n" if known else "") + (
                    "WHAT JAI'S HARD CHECKS FIND IN THE WORKSPACE NOW (files compared with the authority documents. "
                    "A conformance mission is not accepted while any remain; any mission is refused if it adds a "
                    "new one or leaves one in a file it changed):\n"
                    + render_findings(standing))
            # Upgrade 2: the workspace's specification is searchable knowledge, and the mission starts from a
            # numbered requirement list (carried over from earlier rounds when there is one).
            spec_text = await self._specification_passages(mission)
            if requirements:
                self.requirements = [dict(r) for r in requirements]
            else:
                findings = ([Finding(**f).text() for f in self._hard_in_scope(mission, standing)]
                            if standing and standing.get("findings") and self._conformance(mission, standing)
                            else [])
                derived = await derive_requirements(router.as_role("requirements"), self.model, mission,
                                                    spec=spec_text, findings=findings)
                self.requirements = derived["requirements"]
                self.tokens += derived["tokens"]
            await self._graph_requirements()
            starting = await self._starting_context(mission, standing)
            if starting:
                known = (f"{known}\n\n" if known else "") + (
                    "STARTING CONTEXT (gathered before your first step, so you need not look for it):\n" + starting)
            remembered = await self._remembered(mission)
            if remembered:
                known = (f"{known}\n\n" if known else "") + remembered
            reference = await self._reference_passages(mission)
            if reference:
                known = (f"{known}\n\n" if known else "") + (
                    "SOURCE DOCUMENTATION (official, cited; consult it before changing anything it covers, and "
                    "use consult_specialist_knowledge or fetch_url for more):\n" + reference)
        if self.requirements:
            tools = tools + [STATUS_TOOL]
        names = {tool["name"] for tool in tools}
        full = self.toolbox is not None
        system = self._system_prompt(full)
        # Resume: keep the prior conversation if provided (no restart, no lost work).
        messages: List[Message] = prior_messages if prior_messages else [
            Message(role="user", content=(
                f"MISSION:\n{mission}\n\n"
                + (f"Approved workspace root: {self.workspace_root}\n" if self.workspace_root else "")
                + (f"\nWHAT JAI ALREADY KNOWS (its memory and verified lessons for this workspace, and source "
                   f"documentation; check memory against the files before relying on it):\n{known}\n\n"
                   if known else "")
                + (f"REQUIREMENTS (work from this list; mark each with requirement_status as you finish it, "
                   f"with its evidence; the independent check needs evidence for every one):\n"
                   f"{render_requirements(self.requirements)}\n\n" if self.requirements else "")
                + "Begin by inspecting what you need, then act. Call finish when the whole "
                "mission is complete and verified."))]

        final_summary = ""
        success = True
        finished = False
        last_tool = None
        continuation = start_continuation
        total_budget = steps_per_round * (max_continuations + 1)
        refused_stops = 0
        words_only = 0
        stuck = StuckDetector()
        await self._progress("working", continuation, total_budget)

        while self.iterations < total_budget and not finished:
            stop = await self._over_allowance()
            if stop:
                final_summary = stop
                break
            self.iterations += 1
            # Continuation boundary: nudge the model to keep going from where it is.
            if self.iterations > steps_per_round and (self.iterations - 1) % steps_per_round == 0:
                continuation += 1
                messages.append(Message(role="user", content=(
                    f"[CONTINUATION {continuation}] You have not called finish yet. Continue the "
                    f"SAME mission from your current progress (files already written persist). "
                    f"Do the remaining work and call finish when the whole mission is verified."
                    + (f"\n\nREQUIREMENTS NOW:\n{render_requirements(self.requirements)}"
                       if self.requirements else ""))))
            else:
                reminder = self._reminder()
                if reminder:
                    messages.append(Message(role="user", content=reminder))
            told = await self._notes()
            if told:
                messages.append(Message(role="user", content=told))
            # The brief (the mission, the job, the playbooks) is not what fills a conversation: only the room the
            # tool results take is limited, so a specialist's full playbooks do not push its findings out early.
            brief_chars = len(messages[0].content) if messages and isinstance(messages[0].content, str) else 0
            self.context_trimmed += compact_messages(messages, budget=CONTEXT_BUDGET_CHARS + brief_chars)
            resp = await self._model_step(router, CompletionRequest(
                model=self.model, messages=messages, system=system,
                tools=tools, max_tokens=settings.AGENT_MAX_OUTPUT_TOKENS, temperature=0.0,
            ))
            if resp is None:
                # The model stopped answering: the round ends here with its work kept, and the mission carries
                # on from this step in its next round instead of waiting on a call that never returns.
                final_summary = (f"The model did not answer within {MODEL_STEP_SECONDS // 60} minutes, twice, at "
                                 f"step {self.iterations}; the work so far is kept and the mission carries on "
                                 f"from here.")
                self.iterations -= 1
                break
            self.tokens += (resp.usage or {}).get("total_tokens", 0)

            if not resp.tool_calls:
                # A reply in words with work still open is not the end of a role's mission: the agent is told so
                # and works on (14 November: the Partnerships Lead read the workbook, described what it would do
                # in words, and the mission ended there after 14 of its 75 steps with nothing changed).
                nudge = self._words_only(total_budget - self.iterations) if words_only < MAX_WORDS_ONLY else None
                if nudge:
                    words_only += 1
                    if (resp.content or "").strip():
                        self._agent_said = resp.content.strip()[:800]
                        messages.append(Message(role="assistant", content=resp.content))
                    messages.append(Message(role="user", content=nudge))
                    continue
                # Model produced a final answer without finish -> treat as done.
                final_summary = resp.content.strip() or "(no further action)"
                finished = True
                break

            assistant_blocks: List[Dict[str, Any]] = []
            if resp.content:
                assistant_blocks.append({"type": "text", "text": resp.content})
                # What the agent last said it is doing and why, for "what's going on?" (the progress record).
                self._agent_said = resp.content.strip()[:800]
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
                elif call["name"] == STATUS_TOOL["name"]:
                    out = update_requirement(self.requirements, call["args"])
                elif call["name"] == "finish":
                    gave_up = call["args"].get("success") is not True
                    remaining = total_budget - self.iterations
                    if gave_up and remaining > 0 and refused_stops < MAX_REFUSED_STOPS \
                            and not _blocked_or_waiting(self.runtime.calls):
                        # Stopping short with nothing in the way is not an outcome: carry on.
                        refused_stops += 1
                        out = {"acknowledged": False, "reason": self._not_finished(remaining)}
                    else:
                        final_summary = call["args"].get("summary", "Mission complete.")
                        # A finish that does not say it succeeded is not a success.
                        success = not gave_up
                        finished = True
                        out = {"acknowledged": True}
                else:
                    out = await self._tool_step(call["name"], call["args"])
                    if (self.first_edit_step is None and call["name"] in _EDITS and isinstance(out, dict)
                            and out.get("success") is True):
                        self.first_edit_step = self.iterations
                result_blocks.append({"type": "tool_result", "tool_use_id": call["id"],
                                      # A read_file part is passed back whole; other results are clipped.
                                      "content": _clip(out, result_limit(call["name"]))})
                if call["name"] not in ("finish", STATUS_TOOL["name"]):
                    nudge = stuck.observe(call["name"], call["args"], out)
                    if nudge:
                        self.stuck_loops += 1
                        logger.info("mission %s: %s", getattr(self.runtime, "task_id", ""), nudge[:200])
                        result_blocks.append({"type": "text", "text": nudge})
            messages.append(Message(role="user", content=result_blocks))
            await self._progress("working", continuation, total_budget)

        needs_continuation = not finished
        if needs_continuation:
            final_summary = (final_summary or
                             "Reached the continuation cap before the mission self-reported finish.")
            success = False

        # A mission never accepts itself: when it says it is done, an independent check decides.
        verification: Optional[Dict[str, Any]] = None
        if finished and success and verify:
            await self._progress("independent check", continuation, total_budget)
            verification = await self.verify(mission, final_summary)
            if not verification["verified"]:
                success = False
                unmet = verification.get("unmet") or ["The independent check did not confirm the mission."]
                final_summary += ("\n\n**Independent check: not complete yet.**\n"
                                  + "\n".join(f"- {item}" for item in unmet))
                # The mission goes on to fix what the check found (within the automatic-round cap).
                needs_continuation = True

        # Upgrade 4: the report Richard sees is built from numbered evidence only; the agent's own words are kept
        # beside it but no longer shown as the result.
        agent_summary = final_summary
        report: Optional[Dict[str, Any]] = None
        check_calls = (verification or {}).pop("calls", None) or []
        if self._listed():
            from app.core.synthesis import build_ledger, render, synthesize

            await self._progress("writing the report", continuation, total_budget)
            ledger = build_ledger(evidence_calls(self.prior_calls, self.runtime.calls), check_calls)
            made = await synthesize(router.as_role("report"), self.model, mission, self.requirements, ledger,
                                    verification,
                                    (verification or {}).get("hard_checks"))
            self.tokens += made["tokens"]
            report = made["report"]
            final_summary = render(report)

        return {
            "answer": final_summary,
            "agent_summary": agent_summary,
            "report": report,
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
            "stuck_loops": self.stuck_loops,
            "requirements": self.requirements,
            "metrics": {
                "usage": self.usage.summary(), "steps": self.iterations, "rounds": continuation,
                "steps_to_first_edit": self.first_edit_step,
                "verifier_findings": len((verification or {}).get("unmet") or []),
                "hard_failures": len(((verification or {}).get("hard_checks") or {}).get("findings") or []),
            },
            "messages": messages,  # checkpoint payload for resume
        }

    async def hard_checks(self) -> Optional[Dict[str, Any]]:
        """JAI's deterministic conformance checks on the workspace folder (Upgrade 1a), with the workspace's
        authority_docs and superseded_docs. None when the folder or its record cannot be read."""
        import asyncio

        from app.core.verification.checks import run_hard_checks
        from app.core.workspaces import fs_inspector

        if not self.workspace_root or self.runtime.workspace_id is None:
            return None
        try:
            from app.models.workspace import Workspace

            workspace = await self.runtime.db.get(Workspace, self.runtime.workspace_id)
            config = dict((workspace.config or {}) if workspace is not None else {})
            folder = fs_inspector.host_to_container(self.workspace_root)
            if folder is None or not folder.is_dir():
                return None
            return await asyncio.to_thread(run_hard_checks, folder, config)
        except Exception as exc:  # noqa: BLE001 - the Verifier agent still checks; the miss is logged
            logger.warning(f"hard checks could not run: {exc}")
            return None

    async def _graph_requirements(self) -> None:
        """The requirement list as graph nodes tied to the mission (Upgrade 3)."""
        if not self.requirements or self.runtime.workspace_id is None or self.runtime.task_id is None:
            return
        try:
            from app.core.graph import graph_service

            async with self.runtime.db.begin_nested():
                await graph_service.record_requirements(self.runtime.db, self.runtime.workspace_id,
                                                        self.runtime.task_id, self.requirements)
        except Exception as exc:  # noqa: BLE001 - the graph records; it never stops a mission
            logger.warning(f"requirements not recorded in the graph: {exc}")

    async def _graph_verification(self, checks: List[Dict[str, Any]], hard: Optional[Dict[str, Any]]) -> None:
        """The Verifier's evidence and the hard-check failures as graph edges (Upgrade 3)."""
        if self.runtime.workspace_id is None or self.runtime.task_id is None:
            return
        try:
            from app.core.graph import graph_service

            async with self.runtime.db.begin_nested():
                await graph_service.record_verification(
                    self.runtime.db, self.runtime.workspace_id, self.runtime.task_id, self.requirements, checks,
                    (hard or {}).get("findings") or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"verification not recorded in the graph: {exc}")

    async def _starting_context(self, mission: str, standing: Optional[Dict[str, Any]]) -> str:
        """What an engineer looks at first (Upgrade 5): the stack and the project's real commands, the
        specification's version pins, what the artifact graph knows about files the mission names, and this
        workspace's recent failures. Each part is optional; a part that cannot be read is left out."""
        import re

        parts: List[str] = []
        if self.toolbox is not None:
            for name in ("detect_stack", "detect_commands"):
                try:
                    found = await self.toolbox.call(name, {})
                    if isinstance(found, dict) and found.get("success") is not False:
                        parts.append(f"{name}: " + json.dumps({k: v for k, v in found.items() if k != "success"},
                                                              default=str)[:1500])
                except Exception as exc:  # noqa: BLE001
                    logger.info(f"starting context: {name} unavailable: {exc}")
        pins = (standing or {}).get("pins") or {}
        if pins:
            parts.append("Specification pins: " + ", ".join(f"{k} {v}" for k, v in sorted(pins.items())))
        if self.runtime.workspace_id is not None:
            named = list(dict.fromkeys(re.findall(r"(?<![\w/])((?:[\w.-]+/)*[\w-]+\.[A-Za-z0-9]{1,8})(?![\w/])",
                                                  mission)))[:5]
            if named:
                try:
                    from app.core.graph import graph_service

                    for key in named:
                        trace = await graph_service.trace(self.runtime.db, self.runtime.workspace_id, key, depth=2)
                        if trace["nodes"]:
                            parts.append(f"What JAI has recorded about {key}:\n"
                                         + graph_service.describe(trace, limit=8))
                except Exception as exc:  # noqa: BLE001
                    logger.info(f"starting context: graph unavailable: {exc}")
            try:
                from datetime import datetime, timedelta, timezone

                from sqlalchemy import select

                from app.models.task import Task

                since = datetime.now(timezone.utc) - timedelta(days=7)
                failed = (await self.runtime.db.execute(select(Task).where(
                    Task.workspace_id == self.runtime.workspace_id, Task.status.in_(("failed", "partial")),
                    Task.updated_at >= since, Task.id != self.runtime.task_id)
                    .order_by(Task.updated_at.desc()).limit(3))).scalars().all()
                if failed:
                    parts.append("Recent failures in this workspace: " + "; ".join(
                        f"{t.title[:80]} ({t.status}: {(t.error_message or '')[:160]})" for t in failed))
            except Exception as exc:  # noqa: BLE001
                logger.info(f"starting context: recent failures unavailable: {exc}")
        return "\n".join(parts)

    def _cache_key(self) -> Optional[str]:
        return f"jarv-mission-{self.runtime.task_id}" if getattr(self.runtime, "task_id", None) else None

    def _listed(self) -> bool:
        """True when the requirement list is a real breakdown, not just the mission repeated (the requirements step
        had nothing to add): then the Verifier's own checks are the breakdown."""
        return bool(self.requirements) and not (len(self.requirements) == 1
                                                and self.requirements[0].get("source") == "mission")

    @staticmethod
    def _conformance(mission: str, hard: Dict[str, Any]) -> bool:
        """A mission about meeting the specification: it names an authority document, or asks for conformance
        or a phase."""
        text = f" {mission.lower()} "
        authority = [str(d).lower() for d in hard.get("authority_docs") or []]
        return any(word in text for word in ("conform", "specification", " spec ", " phase ")) or any(
            Path(d).name in text for d in authority)

    async def _specification_passages(self, mission: str) -> str:
        """Read the workspace's authority documents into its knowledge (rebuilt only when they change) and
        return their sections most relevant to the mission."""
        if not self.workspace_root or self.runtime.workspace_id is None:
            return ""
        try:
            from app.core.knowledge.ingest import knowledge_ingestor
            from app.core.knowledge.search import render_passages, search_passages
            from app.core.workspaces import fs_inspector
            from app.models.workspace import Workspace

            workspace = await self.runtime.db.get(Workspace, self.runtime.workspace_id)
            docs = [str(d) for d in ((workspace.config or {}).get("authority_docs") or [])] if workspace else []
            folder = fs_inspector.host_to_container(self.workspace_root)
            if not docs or folder is None or not folder.is_dir():
                return ""
            for doc in docs:
                async with self.runtime.db.begin_nested():
                    await knowledge_ingestor.ingest_workspace_document(self.runtime.db, self.runtime.workspace_id,
                                                                       folder, doc)
            hits = await search_passages(self.runtime.db, mission, workspace_id=self.runtime.workspace_id,
                                         limit=12, workspace_only=True)
            return render_passages(hits, chars=2000)
        except Exception as exc:  # noqa: BLE001 - the mission still runs; the miss is logged
            logger.warning(f"specification passages unavailable: {exc}")
            return ""

    def _hard_in_scope(self, mission: str, hard: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The hard-check findings that block this mission: every one for a conformance mission (it names an
        authority document, or asks for conformance or a phase); otherwise those the mission introduced and
        those in files it changed. A resumed run has no starting baseline, so there the changed-files rule and
        the conformance rule decide."""
        if self._conformance(mission, hard):
            return list(hard["findings"])
        written = [str((c.get("inputs") or {}).get("path") or "").replace("\\", "/").lower()
                   for c in self.runtime.calls if isinstance(c, dict)
                   and c.get("tool") in ("write_file", "edit_file", "move_file", "delete_file_with_boundary")
                   and isinstance(c.get("inputs"), dict)]
        chosen = []
        for finding in hard["findings"]:
            key = finding["check"] + "|" + finding["file"] + "|" + finding["detail"]
            new = self.hard_baseline is not None and key not in self.hard_baseline
            touched = any(path.endswith(finding["file"].lower()) for path in written if path)
            if new or touched:
                chosen.append(finding)
        return chosen

    async def _reference_passages(self, mission: str) -> str:
        """The documentation passages most relevant to the mission, from every agent's field, as cited lines."""
        if self.toolbox is None:
            return ""
        try:
            from app.core.knowledge.search import render_passages, search_passages

            hits = await search_passages(self.runtime.db, mission, agents=None,
                                         workspace_id=self.runtime.workspace_id, limit=6)
            return render_passages(hits)
        except Exception as exc:  # noqa: BLE001 - reference material is an addition, never a reason to fail
            logger.warning(f"mission reference passages unavailable: {exc}")
            return ""

    async def _remembered(self, mission: str) -> str:
        """What Richard has told JAI and what JAI's work has established that bear on this mission (Wave 6: Mem0
        and Graphiti); nothing when the knowledge service is off or slow."""
        import asyncio

        from app.core import knowledge_service as ks

        if not ks.enabled():
            return ""
        workspace = getattr(self.runtime, "workspace_id", None)
        told, known = await asyncio.gather(
            ks.quietly(ks.recall(mission, 8, timeout=4.0), []),
            ks.quietly(ks.search_graph(mission, [workspace], 10, timeout=4.0), []) if workspace
            else asyncio.sleep(0, []))
        parts = []
        if told:
            parts.append("WHAT RICHARD HAS TOLD JAI THAT BEARS ON THIS (his preferences and decisions; follow them "
                         "unless the mission says otherwise):\n" + "\n".join(f"- {m['memory']}" for m in told))
        if known:
            parts.append("WHAT JAI'S EARLIER WORK HERE ESTABLISHED (its knowledge graph; check against the files "
                         "before relying on it):\n" + "\n".join(
                             f"- {f['fact']}" + (" (no longer true)" if f.get("no_longer_true") else "")
                             for f in known))
        return "\n\n".join(parts)

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
        trail = _claims(evidence_calls(self.prior_calls, self.runtime.calls))
        hard = await self.hard_checks()
        hard_failures: List[str] = []
        hard_text = ""
        if hard is not None:
            from app.core.verification.checks import Finding, render_findings

            hard_failures = [Finding(**f).text()[:500] for f in self._hard_in_scope(mission, hard)][:30]
            hard_text = ("JAI'S HARD CHECKS (deterministic; " + (
                f"{len(hard_failures)} of these are unmet for this mission whatever you find" if hard_failures
                else "none of these is in this mission's scope") + "; check everything else the mission "
                "requires yourself):\n" + render_findings(hard) + "\n\n")
        messages: List[Message] = [Message(role="user", content=(
            f"MISSION:\n{mission}\n\nWorkspace folder: {self.workspace_root or toolbox.root_host}\n\n"
            f"WHAT THE OTHER AGENT REPORTED (claims to check, not facts):\n{summary[:4000]}\n\n"
            + (f"ITS RECORDED ACTIONS:\n{trail}\n\n" if trail else "")
            + hard_text
            + (f"THE MISSION'S REQUIREMENTS (give one check per requirement, naming its id, with the evidence you "
               f"saw; a requirement without evidence is unmet):\n{render_requirements(self.requirements)}\n\n"
               if self._listed() else "")
            + "Check every requirement yourself, then call verdict."))]
        router = MeteredRouter(get_router(), self.usage, "verifier", self._cache_key())
        tokens = steps = 0
        verdict: Optional[Dict[str, Any]] = None
        limit = verifier_steps(len(self.requirements))
        while steps < limit and verdict is None:
            steps += 1
            compact_messages(messages)
            last = steps == limit
            if steps == limit - 2:
                messages.append(Message(role="user", content=(
                    "Two steps left: finish what you are checking now; your next-but-one step must be verdict.")))
            elif last:
                messages.append(Message(role="user", content=(
                    "Last step: call verdict now with the checks you have made. Mark any requirement you did not "
                    "get to as met=false with the reason 'not checked in the steps available'.")))
            resp = await router.complete(CompletionRequest(
                model=self.model, messages=messages, system=_VERIFIER_SYSTEM, tools=[_VERDICT] if last else tools,
                max_tokens=settings.AGENT_MAX_OUTPUT_TOKENS, temperature=0.0,
                reasoning_effort=getattr(settings, "OPENAI_VERIFIER_REASONING_EFFORT", "high")))
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
            # The progress record moves on with the check, so "how is it going?" never hears a stale step.
            from app.core.command import progress

            await self._progress("independent check", *self._round,
                                 check=progress.check_state(runtime.calls, steps, limit, self.workspace_root))
        self.tokens += tokens
        if verdict is None:
            return {"verified": False, "checks": [], "tokens": tokens, "steps": steps, "hard_checks": hard,
                    "unmet": hard_failures + [f"The independent check did not reach a verdict in {steps} steps."],
                    "calls": list(runtime.calls)}
        checks = [c for c in (verdict.get("checks") or []) if isinstance(c, dict)][:60]
        unmet = [str(u)[:500] for u in (verdict.get("unmet") or []) if str(u).strip()][:30]
        unmet += [f"{c.get('requirement')}: {c.get('evidence')}"[:500] for c in checks
                  if c.get("met") is False and not any(str(c.get("requirement")) in u for u in unmet)]
        # Verified means the verifier said so AND none of its own checks failed.
        verified = verdict.get("verified") is True and not unmet and bool(checks)
        if verdict.get("verified") is True and not checks:
            unmet = ["The independent check reported no evidence for any requirement."]
        # Every listed requirement needs a met check with evidence (Upgrade 2).
        if self._listed():
            unmet += [u for u in unmet_without_evidence(self.requirements, checks) if u not in unmet]
            verified = verified and not unmet
        # A failed hard check is unmet whatever the Verifier agent concluded.
        unmet = hard_failures + [u for u in unmet if u not in hard_failures]
        verified = verified and not hard_failures
        await self._graph_verification(checks, hard)
        return {"verified": verified, "checks": checks, "unmet": unmet, "tokens": tokens, "steps": steps,
                "hard_checks": hard, "calls": list(runtime.calls)}

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

    async def _model_step(self, router, request) -> Optional[Any]:
        """One model call, with a watchdog: a call that has not answered in MODEL_STEP_SECONDS is abandoned and
        asked once more; None when the second one does not answer either."""
        import asyncio

        for attempt in (1, 2):
            try:
                return await asyncio.wait_for(router.complete(request), timeout=MODEL_STEP_SECONDS)
            except asyncio.TimeoutError:
                logger.warning("mission %s: model call %s of 2 at step %s did not answer within %ss",
                               getattr(self.runtime, "task_id", ""), attempt, self.iterations, MODEL_STEP_SECONDS)
        return None

    async def _tool_step(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """One tool call, with a watchdog: a tool that has not returned in TOOL_STEP_SECONDS is stopped and the
        agent told, so one hung call never holds the mission."""
        import asyncio

        limit = TOOL_STEP_SECONDS
        try:
            return await asyncio.wait_for(self._dispatch(name, args), timeout=limit)
        except asyncio.TimeoutError:
            logger.warning("mission %s: tool %s did not return within %ss", getattr(self.runtime, "task_id", ""),
                           name, limit)
            return {"success": False, "timed_out": True,
                    "error": (f"{name} did not return within {limit // 60} minutes and was stopped. Do not run it "
                              f"the same way again: if it starts something that keeps running, run a one-off "
                              f"check instead; if it is slow, narrow it (one package, one test file).")}

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
