"""
JARV Backend - Autonomous Agent Executor (tool-using loop)

This is the core agentic capability: given ANY mission, Claude iteratively
decides which tools to call — list/read/write files, run builds and tests —
observes each result, and keeps going until the mission is done or a boundary
is hit. This is what lets JARV inspect a repo, edit code, run the build, read
the error, fix it, and re-run, scoped to an approved workspace.

Safety is enforced by the tool layer (ToolRuntime + fs_inspector):
  * file writes are scoped to the approved workspace; secrets/out-of-scope blocked,
  * commands are classified — read-only + build/test run; delete/deploy/push/
    install/network are blocked,
  * every tool call is authority-checked, logged to audit + the operations feed,
    and recorded on the task (visible in task detail).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.core.providers import CompletionRequest, Message, get_router

logger = logging.getLogger(__name__)


def _tool_schemas() -> List[Dict[str, Any]]:
    return [
        {
            "name": "list_files",
            "description": "List files and folders at a path inside the approved workspace.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute path inside the workspace"}},
                "required": ["path"],
            },
        },
        {
            "name": "read_file",
            "description": "Read a file's contents (secret files are redacted).",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": ("Create or edit a file inside the approved workspace (Level 2). "
                            "Writes outside scope or to secret files are blocked."),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "Full new file contents"},
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
        {
            "name": "finish",
            "description": "Call when the mission is complete (or cannot proceed). Provide a summary.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "success": {"type": "boolean"},
                },
                "required": ["summary"],
            },
        },
    ]


class AgentExecutor:
    """Runs the Claude tool-use loop against the real tool runtime."""

    def __init__(self, runtime, model: str, workspace_root: Optional[str]):
        self.runtime = runtime
        self.model = model
        self.workspace_root = workspace_root
        self.iterations = 0
        self.tokens = 0

    async def run(self, mission: str, steps_per_round: int = 8,
                  max_continuations: int = 4,
                  prior_messages: Optional[List[Message]] = None,
                  start_continuation: int = 0) -> Dict[str, Any]:
        """
        Run the tool loop with AUTO-CONTINUATION. The same conversation (and thus
        every prior tool result) is preserved across continuation rounds — the
        mission is never restarted. Stops only on a real terminal state:
        finished (completed), stalled/no-tools, or the continuation cap reached
        (-> needs_continuation, with a checkpoint to resume from).
        """
        router = get_router()
        system = (
            "You are JARV, an autonomous software engineer operating a real machine. "
            "You complete the operator's mission by USING TOOLS — inspect files, edit "
            "code, run builds and tests — iterating until the mission is genuinely done. "
            f"You operate ONLY inside the approved workspace"
            + (f" rooted at `{self.workspace_root}`. " if self.workspace_root else ". ")
            + "Use absolute paths inside that workspace. You CANNOT delete, deploy, push, "
            "install packages, or access the network — those tools are blocked by policy; "
            "if the mission needs one, explain it and call finish. Make real changes with "
            "write_file and verify with run_command (build/test). Do not claim success "
            "without verifying. When the WHOLE mission is done, call the finish tool."
        )
        tools = _tool_schemas()
        # Resume: keep the prior conversation if provided (no restart, no lost work).
        messages: List[Message] = prior_messages if prior_messages else [
            Message(role="user", content=(
                f"MISSION:\n{mission}\n\n"
                + (f"Approved workspace root: {self.workspace_root}\n" if self.workspace_root else "")
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
            resp = await router.complete(CompletionRequest(
                model=self.model, messages=messages, system=system,
                tools=tools, max_tokens=4096, temperature=0.0,
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
                except Exception:  # noqa: BLE001
                    args = {}
                assistant_blocks.append({"type": "tool_use", "id": tc["id"], "name": name, "input": args})
                parsed.append({"id": tc["id"], "name": name, "args": args})
            messages.append(Message(role="assistant", content=assistant_blocks))

            result_blocks: List[Dict[str, Any]] = []
            for call in parsed:
                last_tool = call["id"]
                if call["name"] == "finish":
                    final_summary = call["args"].get("summary", "Mission complete.")
                    success = bool(call["args"].get("success", True))
                    finished = True
                    out = {"acknowledged": True}
                else:
                    out = await self._dispatch(call["name"], call["args"])
                result_blocks.append({"type": "tool_result", "tool_use_id": call["id"],
                                      "content": json.dumps(out)[:6000]})
            messages.append(Message(role="user", content=result_blocks))

        needs_continuation = not finished
        if needs_continuation:
            final_summary = (final_summary or
                             "Reached the continuation cap before the mission self-reported finish.")
            success = False

        return {
            "answer": final_summary,
            "iterations": self.iterations,
            "success": success and finished,
            "finished": finished,
            "needs_continuation": needs_continuation,
            "step_limit_reached": needs_continuation,
            "continuation_count": continuation,
            "resume_from_step": self.iterations,
            "remaining_steps": max(0, total_budget - self.iterations),
            "last_tool_call_id": last_tool,
            "tokens": self.tokens,
            "messages": messages,  # checkpoint payload for resume
        }

    async def _dispatch(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if name == "list_files":
                return await self.runtime.list_files(args.get("path", self.workspace_root or ""))
            if name == "read_file":
                return await self.runtime.read_file(args.get("path", ""))
            if name == "write_file":
                return await self.runtime.write_file(args.get("path", ""), args.get("content", ""),
                                                     overwrite=True)
            if name == "run_command":
                return await self.runtime.run_command(
                    args.get("command", ""), cwd_host=args.get("cwd") or self.workspace_root,
                    allow_build=True)
            return {"error": f"unknown tool '{name}'"}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"agent tool '{name}' failed: {exc}")
            return {"error": str(exc)}
