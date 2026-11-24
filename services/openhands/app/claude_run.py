"""
Non-development work in JAI's sandbox on the Claude Agent SDK (24 November, audit batch 3)

The audit of 23 November found JAI's creative and command work running on OpenHands through an added skill loader,
with a second rule set for files and a hung model call waiting 10 minutes. This runs that work the way Claude Code
itself works, inside this sandbox (the studio, OpenMontage, Remotion, ffmpeg, Chromium and yt-dlp live only here):

- THE SESSION is the Claude Agent SDK's (code.claude.com/docs/en/agent-sdk): Claude Code's own loop and tools
  (Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, TodoWrite, Skill), the claude_code system prompt with
  the specialist's standard and JAI's engineering rules appended, in the mission's workspace folder.
- SKILLS load natively: the run's skills (the "pack/root/skill" folders the backend names) are linked into the run's
  own Claude Code configuration folder and opened with the Skill tool; Claude Code's own disableSkillShellExecution
  setting keeps a skill's inline !`command` lines from running, as the OpenHands loader did by hand.
- THE GATE is one rule set: every Bash command and file action goes to JAI's backend (app/gate.py, the same
  /api/agent-gate/check the OpenHands tools use, decided by sandbox_policy) from a PreToolUse hook, which Anthropic
  documents runs before every other permission step, its deny holding in every mode; dontAsk mode refuses any tool
  not listed. Each action is recorded afterwards (PostToolUse, PostToolUseFailure).
- JAI'S OWN TOOLS (memory, knowledge, research, images, voiceovers, video) come from JAI's MCP server through an
  in-process SDK server in this service, so the sandbox token never leaves this process.
- THE MODEL is reached through JAI's gateway with a token of this run only, never JAI's gateway token, the sandbox
  token or an Anthropic key: the backend issues it with the run's own spending allowance, the gateway refuses it past
  that allowance or once the run ends, and it is revoked when the run ends. Claude Code runs as the unprivileged agent
  user, who cannot read this service's environment. Claude Code's credential scrub is left off: with it on, every
  Bash command runs inside Claude Code's own sandbox, which limits the network and writes to the project (it would
  stop yt-dlp, the footage sources, OpenMontage staging its projects and every install), and JAI's gate is already
  the one control over commands. The sandbox's own settings reach the shell from its settings files
  (CLAUDE_ENV_FILE), as the OpenHands login shell gets them.
- LIMITS: the run's turn and spending limits (max_turns, max_budget_usd), and Claude Code's own call timeout and
  retries (API_TIMEOUT_MS, CLAUDE_CODE_MAX_RETRIES) at what the backend sets.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("jai.sandbox.claude")

AGENT_USER = os.environ.get("JAI_AGENT_USER", "openhands")
SESSIONS = Path(os.environ.get("JAI_CLAUDE_SESSIONS", "/home/openhands/.jai-claude"))
SERVER = "jai"
PREFIX = f"mcp__{SERVER}__"
# Claude Code's own tools in the session.
TOOLS = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite", "Skill", "ToolSearch")
# Never part of the session: tools that wait for a person, edit notebooks, or start other agents (one maker).
REMOVED = ("NotebookEdit", "AskUserQuestion", "Agent", "Task", "SendMessage", "Workflow", "ExitPlanMode")
# Touch nothing on disk or the machine: allowed without asking JAI (the backend's tools gate themselves).
UNGATED = ("TodoWrite", "Skill", "ToolSearch", "WebSearch", "WebFetch")
# How a file tool's action is asked of JAI's gate (the file editor's own commands).
FILE_COMMAND = {"Read": "view", "Glob": "view", "Grep": "view", "Write": "create", "Edit": "str_replace"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _deny(reason: str) -> Dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _allow(reason: str) -> Dict[str, Any]:
    """JAI's decision is the session's: a call JAI's gate allows is allowed here explicitly, so no permission mode or
    rule of Claude Code's can turn it into a question nobody is there to answer (its deny rules still apply)."""
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                   "permissionDecisionReason": reason}}


def _text(value: Any, limit: int = 2000) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, dict):
        parts = [str(value.get(k) or "") for k in ("stdout", "stderr", "output", "content", "result") if value.get(k)]
        text = "\n".join(parts) if parts else json.dumps(value, default=str)
    else:
        text = json.dumps(value, default=str)
    return text[-limit:]


def rules_for_claude(rules: str) -> str:
    """JAI's engineering rules as a Claude Code session reads them: its Skill tool, not OpenHands' invoke_skill."""
    return (rules.replace("call invoke_skill with its name and follow it", "open it with the Skill tool and follow it")
            .replace("invoke_skill", "the Skill tool"))


# Claude Code drops skill descriptions past its listing's character budget, which removes the words it chooses a skill
# by (code.claude.com/docs/en/skills); the business engine lists its trade in full and the rest by name for the same
# reason (backend claude_engine.skill_listing). Its cap on one description, and room for its own bundled skills.
DESCRIPTION_CAP, LISTING_SPARE, LISTING_MARGIN = 1536, 6000, 1.25


def _front(skill_md: Path) -> Dict[str, str]:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    head = text[3:].split("\n---", 1)[0]
    try:
        import yaml

        data = yaml.safe_load(head) or {}
    except Exception:  # noqa: BLE001 - Claude Code lists it by its folder name
        data = {}
    if not isinstance(data, dict):
        return {}
    return {"name": str(data.get("name") or ""),
            "description": " ".join(str(data.get(k) or "") for k in ("description", "when_to_use")).strip()}


def listing(config: Path, in_full: List[str]) -> Dict[str, Any]:
    """skillOverrides (name-only for skills outside the specialist's own) and the budget that fits the listing whole."""
    keep = set(in_full)
    overrides: Dict[str, str] = {}
    chars = 0
    for link in sorted((config / "skills").iterdir()):
        front = _front(link / "SKILL.md")
        name = front.get("name") or link.name
        if not keep or link.name in keep or name in keep:
            chars += len(name) + min(len(front.get("description", "")), DESCRIPTION_CAP) + 4
        else:
            for key in {link.name, name}:
                overrides[key] = "name-only"
            chars += len(name) + 4
    return {"overrides": overrides, "budget": int(chars * LISTING_MARGIN) + LISTING_SPARE}


def prepare_config(run_id: str, skills: List[str], skills_root: Path, refused: set,
                   owner: Optional[str] = "", in_full: Optional[List[str]] = None) -> Path:
    """The run's own Claude Code configuration folder: its skills linked in, Claude Code's settings (skills' inline
    shell commands off) and the shell's settings file. Owned by the agent user, who runs Claude Code."""
    base = SESSIONS / run_id
    shutil.rmtree(base, ignore_errors=True)
    (base / "skills").mkdir(parents=True)
    root = skills_root.resolve()
    seen = set()
    for folder in skills:
        if folder.strip("/") in refused:
            logger.warning("skill %s was flagged by AgentShield; skipped", folder)
            continue
        source = (root / folder).resolve()
        try:
            source.relative_to(root)
        except ValueError:
            logger.warning("skill %s is outside the skill packs; skipped", folder)
            continue
        name = source.name
        if not (source / "SKILL.md").is_file() or name in seen:
            continue
        seen.add(name)
        os.symlink(source, base / "skills" / name, target_is_directory=True)
    listed = listing(base, list(in_full or []))
    settings = {"disableSkillShellExecution": True}
    if listed["overrides"]:
        settings["skillOverrides"] = listed["overrides"]
    (base / "settings.json").write_text(json.dumps(settings, indent=1))
    (base / "listing-budget").write_text(str(listed["budget"]))
    # Run before every Bash command, after Claude Code has scrubbed JAI's credentials: the sandbox's own settings
    # (the studio, the voice, Playwright, MYCO's dev stack, the footage key), as the OpenHands login shell has them.
    (base / "shell-env.sh").write_text(
        'for f in /etc/profile.d/jai-*.sh; do [ -r "$f" ] && . "$f"; done\nunset f\n')
    if owner and os.geteuid() == 0:
        shutil.chown(base, owner, owner)
        for path in base.rglob("*"):
            if not path.is_symlink():
                shutil.chown(path, owner, owner)
    return base


def session_env(request, config: Path, backend_url: str) -> Dict[str, str]:
    """Claude Code's environment for one run: JAI's gateway with this run's token, its configuration folder, the
    shell's settings file, and the backend's call timeout and retries."""
    token = request.model_token.get_secret_value() if request.model_token is not None else ""
    return {
        "ANTHROPIC_BASE_URL": f"{backend_url}/api/gateway/anthropic",
        "ANTHROPIC_AUTH_TOKEN": token,
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": request.light_model or request.model,
        "CLAUDE_CONFIG_DIR": str(config),
        "HOME": str(Path(os.environ.get("JAI_AGENT_HOME", "/home/openhands"))),
        "CLAUDE_ENV_FILE": str(config / "shell-env.sh"),
        # Every command starts in the workspace (so JAI's gate reads its paths from there); `cd x && ...` still works.
        "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR": "1",
        "API_TIMEOUT_MS": str(int(request.api_timeout_ms)),
        "CLAUDE_CODE_MAX_RETRIES": str(int(request.max_retries)),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1", "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_AGENT_SDK_CLIENT_APP": "jai-sandbox",
        # The skill listing's budget, so every description in it reaches Claude whole (listing above).
        "SLASH_COMMAND_TOOL_CHAR_BUDGET": _budget(config),
    }


def _budget(config: Path) -> str:
    try:
        return str(int((config / "listing-budget").read_text().strip()))
    except (OSError, ValueError):
        return str(LISTING_SPARE * 4)


async def _mcp(client: httpx.AsyncClient, url: str, token: str, run_id: str, method: str,
               params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                                 headers={"Authorization": f"Bearer {token}", "X-JAI-Run": run_id})
    response.raise_for_status()
    answer = response.json()
    if answer.get("error"):
        raise RuntimeError(str(answer["error"].get("message") or answer["error"]))
    return answer.get("result") or {}


async def jai_server(sdk, run_id: str, backend_url: str, token: str,
                     transport: Optional[httpx.AsyncBaseTransport] = None
                     ) -> Tuple[Optional[Dict[str, Any]], Optional[httpx.AsyncClient], str]:
    """JAI's own tools for the session, served in this process from JAI's MCP server (its calls checked and recorded
    by JAI, at this run's authority): (server, its client, ""), or (None, None, why) when they cannot be reached, and
    the session works without them."""
    url = f"{backend_url}/api/agent-tools/mcp"
    client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=5.0), transport=transport)
    try:
        listed = (await _mcp(client, url, token, run_id, "tools/list")).get("tools") or []
    except Exception as exc:  # noqa: BLE001
        await client.aclose()
        return None, None, (f"JAI's own tools could not be reached ({type(exc).__name__}); worked with Claude "
                            "Code's own.")

    def handler(name: str):
        async def call(args: Dict[str, Any]) -> Dict[str, Any]:
            try:
                result = await _mcp(client, url, token, run_id, "tools/call", {"name": name, "arguments": args or {}})
            except Exception as exc:  # noqa: BLE001
                return {"content": [{"type": "text", "text": f"JAI's {name} could not be reached: {exc}"}],
                        "is_error": True}
            return {"content": result.get("content") or [{"type": "text", "text": ""}],
                    "is_error": bool(result.get("isError"))}
        return call

    tools = [sdk.tool(t["name"], str(t.get("description") or t["name"])[:1000],
                      t.get("inputSchema") or {"type": "object", "properties": {}})(handler(t["name"]))
             for t in listed if t.get("name")]
    if not tools:
        await client.aclose()
        return None, None, ""
    return sdk.create_sdk_mcp_server(name=SERVER, version="1.0.0", tools=tools), client, ""


class Hooks:
    """JAI's gate before every tool call and its record after (PreToolUse, PostToolUse, PostToolUseFailure)."""

    def __init__(self, run, gate, workspace: str):
        self.run, self.gate, self.workspace = run, gate, workspace
        self.pending: Dict[str, Tuple[str, Dict[str, Any]]] = {}

    def _ask(self, tool: str, args: Dict[str, Any]) -> Tuple[Optional[str], Optional[Tuple[str, Dict[str, Any]]]]:
        """(refusal or None, the action as JAI's gate knows it)."""
        if tool == "Bash":
            payload = {"command": str(args.get("command") or ""), "cwd": self.workspace, "is_input": False}
            return self.gate.check("terminal", payload), ("terminal", payload)
        if tool in FILE_COMMAND:
            path = str(args.get("file_path") or args.get("path") or self.workspace)
            payload = {"command": FILE_COMMAND[tool], "path": path}
            return self.gate.check("file_editor", payload), ("file_editor", payload)
        return f"Not run: {tool} is not part of this session.", None

    async def pre(self, hook_input, tool_use_id, context) -> Dict[str, Any]:
        tool = str((hook_input or {}).get("tool_name") or "")
        args = (hook_input or {}).get("tool_input") or {}
        if self.run.status == "stopped":
            return _deny("This run was stopped. Do nothing further.")
        if tool in UNGATED or tool.startswith(PREFIX):
            return _allow("Touches nothing on this machine; JAI's own tools check themselves.")
        refusal, action = await asyncio.to_thread(self._ask, tool, args)
        if refusal:
            self.run.steps += 1  # an action the agent took, refused (OpenHands counts it the same way)
            if action is not None:
                await asyncio.to_thread(self.gate.record, action[0], action[1], False, refusal, refused=True)
            return _deny(refusal)
        if action is not None and tool_use_id:
            self.pending[str(tool_use_id)] = action
        return _allow("Allowed by JAI's sandbox rules.")

    def _count(self, tool: str, args: Dict[str, Any]) -> None:
        self.run.steps += 1
        if tool:
            self.run.tools_used[tool] = self.run.tools_used.get(tool, 0) + 1
        if tool == "Skill":
            name = str(args.get("skill") or args.get("name") or args.get("command") or "").strip()
            if name and name not in self.run.skills_used:
                self.run.skills_used.append(name)

    async def _after(self, hook_input, tool_use_id, ok: bool, text: str) -> Dict[str, Any]:
        tool = str((hook_input or {}).get("tool_name") or "")
        args = (hook_input or {}).get("tool_input") or {}
        self._count(tool, args)
        action = self.pending.pop(str(tool_use_id or ""), None)
        if action is not None:
            kind, payload = action
            if kind == "terminal":
                await asyncio.to_thread(self.gate.record, kind, payload, ok, text, exit_code=0 if ok else 1)
            elif payload.get("command") != "view":  # as the OpenHands editor: views are not recorded
                await asyncio.to_thread(self.gate.record, kind, payload, ok, text[-500:])
        return {}

    async def post(self, hook_input, tool_use_id, context) -> Dict[str, Any]:
        return await self._after(hook_input, tool_use_id, True, _text((hook_input or {}).get("tool_response")))

    async def failed(self, hook_input, tool_use_id, context) -> Dict[str, Any]:
        return await self._after(hook_input, tool_use_id, False, str((hook_input or {}).get("error") or "failed"))


def options_for(sdk, run, config: Path, hooks: Hooks, server: Optional[Dict[str, Any]], rules: str,
                backend_url: str):
    request = run.request
    effort = request.reasoning_effort if request.reasoning_effort in EFFORTS else None
    return sdk.ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code",
                       "append": "\n\n".join(part for part in (request.standard, rules_for_claude(rules)) if part)},
        model=request.model,
        cwd=request.workspace,
        user=AGENT_USER if os.geteuid() == 0 else None,
        setting_sources=["user"],                 # the run's configuration folder: its skills and settings
        skills="all",
        mcp_servers={SERVER: server} if server else {},
        allowed_tools=list(TOOLS) + ([f"{PREFIX}*"] if server else []),
        disallowed_tools=list(REMOVED),
        permission_mode="dontAsk",
        hooks={"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[hooks.pre])],
               "PostToolUse": [sdk.HookMatcher(matcher=None, hooks=[hooks.post])],
               "PostToolUseFailure": [sdk.HookMatcher(matcher=None, hooks=[hooks.failed])]},
        max_turns=int(request.max_iterations),
        max_budget_usd=request.max_cost_usd,
        effort=effort,
        env=session_env(request, config, backend_url),
        stderr=lambda line: logger.debug("claude %s: %s", request.run_id, line),
    )


STATUS = {"success": "finished", "error_max_turns": "stopped", "error_max_budget_usd": "stopped",
          "error_during_execution": "error"}


async def execute(run, gate, rules: str, backend_url: str, sandbox_token: str, skills_root: Path,
                  refused: set) -> None:
    """One run, start to end: sets run.status, final_message, error, tokens and cost as the OpenHands path does."""
    import claude_agent_sdk as sdk

    request = run.request
    config = prepare_config(request.run_id, list(request.skills), skills_root, refused,
                            in_full=list(request.skills_in_full))
    server, tools_client, note = (await jai_server(sdk, request.run_id, backend_url, sandbox_token)
                                  if request.jai_tools else (None, None, ""))
    if note:
        run.notes = note
    hooks = Hooks(run, gate, request.workspace)
    run.status = "running"
    subtype = ""
    try:
        async with sdk.ClaudeSDKClient(options=options_for(sdk, run, config, hooks, server, rules,
                                                           backend_url)) as client:
            loop = asyncio.get_running_loop()
            run.interrupt = lambda: asyncio.run_coroutine_threadsafe(client.interrupt(), loop)
            await client.query(request.brief)
            async for message in client.receive_response():
                kind = type(message).__name__
                if kind == "AssistantMessage" and not getattr(message, "parent_tool_use_id", None):
                    said = " ".join(str(getattr(b, "text", "") or "") for b in getattr(message, "content", [])
                                    if type(b).__name__ == "TextBlock").strip()
                    if said:
                        run.thought = said[-600:]
                        run.final_message = said
                elif kind == "ResultMessage":
                    subtype = str(getattr(message, "subtype", "") or "")
                    run.cost_usd = float(getattr(message, "total_cost_usd", None) or 0.0)
                    usage = getattr(message, "usage", None) or {}
                    run.tokens = {"input": int(usage.get("input_tokens") or 0)
                                  + int(usage.get("cache_read_input_tokens") or 0)
                                  + int(usage.get("cache_creation_input_tokens") or 0),
                                  "output": int(usage.get("output_tokens") or 0),
                                  "cached": int(usage.get("cache_read_input_tokens") or 0)}
                    if getattr(message, "result", None):
                        run.final_message = str(message.result)
    except Exception as exc:  # noqa: BLE001 - reported to JAI, which carries on with the rest of the mission
        logger.exception("claude run %s failed", request.run_id)
        if run.status != "stopped":
            run.status, run.error = "error", f"{type(exc).__name__}: {exc}"[:1000]
        return
    finally:
        run.interrupt = None
        if tools_client is not None:
            await tools_client.aclose()
    if run.status == "stopped":
        return
    run.status = STATUS.get(subtype, "error" if subtype else "stopped")
    if subtype == "error_max_budget_usd":
        run.error = "Stopped at its budget limit before it said it had finished."
    elif subtype == "error_max_turns":
        run.error = f"Stopped at its limit ({run.steps} steps) before it said it had finished."
    elif run.status == "error":
        run.error = run.error or f"The session ended with {subtype or 'no result'}."


def forget(run_id: str) -> None:
    """Remove a finished run's Claude Code folder (its skill links and session transcript)."""
    shutil.rmtree(SESSIONS / run_id, ignore_errors=True)
