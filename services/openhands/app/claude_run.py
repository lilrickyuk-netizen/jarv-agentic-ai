"""
Non-development work in JAI's sandbox on the Claude Agent SDK (24 November, audit batch 3)

The audit of 23 November found JAI's creative and command work running on OpenHands through an added skill loader,
with a second rule set for files and a hung model call waiting 10 minutes. This runs that work the way Claude Code
itself works, inside this sandbox (the studio, OpenMontage, Remotion, ffmpeg, Chromium and yt-dlp live only here):

- THE SESSION is the Claude Agent SDK's (code.claude.com/docs/en/agent-sdk): Claude Code's own loop and tools
  (Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, TodoWrite, Skill), the claude_code system prompt with
  the specialist's standard and JAI's engineering rules appended, in the mission's workspace folder.
- SKILLS load natively: every skill JAI has is in the session (the specialist's own trade described in full, the
  rest by name), with Superpowers and ECC as the full Claude Code plugins their authors ship (agents, commands,
  hooks; ECC's learning kept in JAI's one learning store, shared with the business engine, across missions). Each
  mission works on its own writable copy of the skills (the originals stay read-only), so a skill that writes its
  own setup files (short-editing's engine, its music beds) works.
- A SKILL'S OWN SHELL LINES (!`command`) run when it loads, but through JAI's gate like every other command: Claude
  Code runs them itself outside every hook (tested 24 November: the gate saw nothing and the command ran), so its
  own disableSkillShellExecution stays on and JAI runs each line instead when the Skill tool opens that skill, as
  the agent user in the workspace, checked by sandbox_policy first, and hands Claude their output with the skill
  (the PreToolUse hook's additionalContext: Claude Code reads a skill's text once, when the session starts).
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
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("jai.sandbox.claude")

AGENT_USER = os.environ.get("JAI_AGENT_USER", "openhands")
SESSIONS = Path(os.environ.get("JAI_CLAUDE_SESSIONS", "/home/openhands/.jai-claude"))
# Each mission's writable copy of the skills (24 November): kept for the mission's later rounds, removed after
# COPIES_DAYS. The skill packs themselves stay read-only at /jai/skills.
COPIES = Path(os.environ.get("JAI_SKILL_COPIES", "/home/openhands/.jai-skill-copies"))
COPIES_DAYS = 7
# JAI's one learning store for ECC (the business engine's /app/.jai-learned, mounted here): ECC's lessons are kept
# across missions and shared by both engines.
LEARNED = Path(os.environ.get("JAI_LEARNED_DIR", "/jai/learned"))
# A skill's inline command, as Claude Code (and OpenHands) read it: fenced blocks, escaped commands and inline code
# are left as they are; !`command` is run.
INLINE = re.compile(r"(?P<fenced>```[\s\S]*?(?:```|$))|(?P<escaped>\\!`[^`]+`)|(?P<inline>(?<!!)`[^`]+`)"
                    r"|!`(?P<cmd>[^`]+)`")
INLINE_SECONDS = 120
# The largest single message the SDK accepts from Claude Code (a picture the Read tool opened, in base64).
MESSAGE_LIMIT = 64 * 1024 * 1024
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
    plugins = config / "plugins"
    for home in sorted(plugins.iterdir()) if plugins.is_dir() else []:  # always listed in full (skillOverrides
        for item in [*sorted((home / "skills").glob("*/SKILL.md")),       # does not reach a plugin's skills)
                     *sorted((home / "commands").glob("*.md"))]:
            front = _front(item)
            name = front.get("name") or (item.parent.name if item.name == "SKILL.md" else item.stem)
            chars += len(home.name) + 1 + len(name) + min(len(front.get("description", "")), DESCRIPTION_CAP) + 4
    return {"overrides": overrides, "budget": int(chars * LISTING_MARGIN) + LISTING_SPARE}


def _chown_tree(path: Path, owner: Optional[str]) -> None:
    if not owner or os.geteuid() != 0:
        return
    shutil.chown(path, owner, owner)
    for item in path.rglob("*"):
        if not item.is_symlink():
            shutil.chown(item, owner, owner)


def _forget_old_copies(now: Optional[float] = None) -> None:
    cutoff = (now or time.time()) - COPIES_DAYS * 86400
    for old in COPIES.iterdir() if COPIES.is_dir() else []:
        try:
            if old.is_dir() and old.stat().st_mtime < cutoff:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            continue


def writable_copy(mission_id: str, folder: str, skills_root: Path, owner: Optional[str]) -> Optional[Path]:
    """The mission's own copy of one skill folder (made on first use, kept for its later rounds); None when the
    folder is not a skill inside the packs. The pack's original is never written to."""
    root = skills_root.resolve()
    source = (root / folder).resolve()
    try:
        source.relative_to(root)
    except ValueError:
        logger.warning("skill %s is outside the skill packs; skipped", folder)
        return None
    if not (source / "SKILL.md").is_file():
        return None
    copy = COPIES / mission_id / source.relative_to(root)
    if not (copy / "SKILL.md").is_file():
        shutil.rmtree(copy, ignore_errors=True)
        shutil.copytree(source, copy, symlinks=True)
        for path in (copy, *copy.rglob("*")):
            if path.is_symlink():
                continue
            path.chmod(path.stat().st_mode | (0o700 if path.is_dir() else 0o600))
        _chown_tree(COPIES / mission_id, owner)
    return copy


def assemble_plugins(base: Path, plugins: List[Dict[str, Any]], mission_id: str, skills_root: Path,
                     refused: set, owner: Optional[str]) -> List[Dict[str, str]]:
    """Superpowers and ECC as Claude Code plugins, as the business engine assembles them (claude_engine._plugins):
    their agents, commands, hooks (and ECC's scripts) linked from the pinned, AgentShield-scanned clone, a part it
    blocked left out; every skill of the pack from the mission's writable copies (Superpowers' whole workflow)."""
    out: List[Dict[str, str]] = []
    root = skills_root.resolve()
    for plugin in plugins or []:
        name = str(plugin.get("name") or "")
        source = root / name
        if not name or "/" in name or not source.is_dir():
            continue
        try:
            blocked_parts = {line.strip().strip("/") for line in
                             (source / ".jai-blocked-parts").read_text(encoding="utf-8").splitlines() if line.strip()}
        except OSError:
            blocked_parts = set()
        home = base / "plugins" / name
        shutil.rmtree(home, ignore_errors=True)
        (home / ".claude-plugin").mkdir(parents=True)
        (home / ".claude-plugin" / "plugin.json").write_text(json.dumps({
            "name": name, "description": f"{plugin.get('title') or name} by {plugin.get('publisher') or ''}",
            "version": str(plugin.get("commit") or "")[:7]}))
        for part in plugin.get("parts") or []:
            part = str(part)
            part_source = source / part
            if part == "skills" or part in blocked_parts or not part_source.is_dir():
                continue
            if part == "hooks":
                os.symlink(part_source, home / "hooks", target_is_directory=True)
                continue
            (home / part).mkdir()
            for item in sorted(part_source.iterdir()):
                if f"{part}/{item.name}" not in blocked_parts and not item.name.startswith("."):
                    os.symlink(item, home / part / item.name, target_is_directory=item.is_dir())
        (home / "skills").mkdir()
        folders = list(plugin.get("skills") or [])
        if plugin.get("whole_root"):
            skills_dir = source / str(plugin.get("root") or "skills")
            folders += [f"{name}/{plugin.get('root') or 'skills'}/{d.name}" for d in sorted(skills_dir.iterdir())
                        if d.is_dir() and (d / "SKILL.md").is_file()] if skills_dir.is_dir() else []
        for folder in dict.fromkeys(folders):
            if folder.strip("/") in refused:
                continue
            copy = writable_copy(mission_id, folder, skills_root, owner)
            if copy is not None and not (home / "skills" / copy.name).exists():
                os.symlink(copy, home / "skills" / copy.name, target_is_directory=True)
        out.append({"type": "local", "path": str(home)})
    return out


def prepare_config(run_id: str, skills: List[str], skills_root: Path, refused: set,
                   owner: Optional[str] = "", in_full: Optional[List[str]] = None, mission_id: str = "",
                   plugins: Optional[List[Dict[str, Any]]] = None) -> Path:
    """The run's own Claude Code configuration folder: every skill (from the mission's writable copies), the
    plugins, Claude Code's settings and the shell's settings file. Owned by the agent user, who runs Claude Code
    ("": the agent user; None: left as it is)."""
    owner = AGENT_USER if owner == "" else owner
    mission_id = mission_id or run_id
    base = SESSIONS / run_id
    shutil.rmtree(base, ignore_errors=True)
    (base / "skills").mkdir(parents=True)
    COPIES.mkdir(parents=True, exist_ok=True)
    if owner and os.geteuid() == 0:
        shutil.chown(COPIES, owner, owner)
    _forget_old_copies()
    seen = set()
    for folder in skills:
        if folder.strip("/") in refused:
            logger.warning("skill %s was flagged by AgentShield; skipped", folder)
            continue
        copy = writable_copy(mission_id, folder, skills_root, owner)
        if copy is None or copy.name in seen:
            continue
        seen.add(copy.name)
        os.symlink(copy, base / "skills" / copy.name, target_is_directory=True)
    (base / "plugins.json").write_text(json.dumps(
        assemble_plugins(base, list(plugins or []), mission_id, skills_root, refused, owner)))
    listed = listing(base, list(in_full or []))
    settings = {"disableSkillShellExecution": True}  # JAI runs skills' own shell lines itself (resolve_inline)
    if listed["overrides"]:
        settings["skillOverrides"] = listed["overrides"]
    (base / "settings.json").write_text(json.dumps(settings, indent=1))
    (base / "listing-budget").write_text(str(listed["budget"]))
    (base / "mission").write_text(mission_id)
    # Run before every Bash command: the sandbox's own settings (the studio, the voice, Playwright, MYCO's dev stack,
    # the footage key), as the OpenHands login shell has them.
    (base / "shell-env.sh").write_text(
        'for f in /etc/profile.d/jai-*.sh; do [ -r "$f" ] && . "$f"; done\nunset f\n')
    _chown_tree(base, owner)
    return base


def ecc_env(request) -> Dict[str, str]:
    """ECC's learning system in the session as its authors ship it, in JAI's one learning store (the switches ECC
    reads: scripts/lib/agent-data-home.js, skills/continuous-learning-v2), as the business engine sets them
    (claude_engine.ecc_learning_env)."""
    if not request.ecc_learning:
        return {"ECC_HOOK_PROFILE": "minimal", "ECC_SKIP_OBSERVE": "1"}
    env = {"CLAUDE_CODE_ENTRYPOINT": "sdk-ts", "ECC_AGENT_DATA_HOME": str(LEARNED / "ecc"),
           "CLV2_HOMUNCULUS_DIR": str(LEARNED / "homunculus"), "ECC_DISABLED_HOOKS": request.ecc_disabled_hooks,
           "ECC_OBSERVER_MODEL": request.light_model or request.model,
           "OBSERVER_ACTIVE_HOURS_START": "0", "OBSERVER_ACTIVE_HOURS_END": "0", "OBSERVER_MAX_IDLE_SECONDS": "0"}
    config = LEARNED / "homunculus" / "config.json"
    try:
        config.parent.mkdir(parents=True, exist_ok=True)
        (LEARNED / "ecc").mkdir(parents=True, exist_ok=True)
        wanted = {"version": "2.1", "observer": {"enabled": True, "run_interval_minutes": 5,
                                                 "min_observations_to_analyze": 20}}
        if not config.is_file() or json.loads(config.read_text(encoding="utf-8")) != wanted:
            config.write_text(json.dumps(wanted, indent=2), encoding="utf-8")
        if os.geteuid() == 0:  # ECC's hooks write here as the agent user (uid 1000, as the worker's own user)
            for path in (LEARNED, LEARNED / "ecc", config.parent, config):
                if path.stat().st_uid == 0:
                    shutil.chown(path, AGENT_USER, AGENT_USER)
        env["CLV2_CONFIG"] = str(config)
    except (OSError, ValueError, LookupError) as exc:
        logger.info("ECC's observer stays off this session: %s", exc)
    try:  # the Claude Code program the SDK ships, for ECC's observer's own short sessions
        import claude_agent_sdk

        bundled = Path(claude_agent_sdk.__file__).parent / "_bundled"
        if (bundled / "claude").is_file():
            env["PATH"] = f"{bundled}{os.pathsep}{os.environ.get('PATH', '')}"
    except (ImportError, AttributeError, TypeError):
        pass
    return env


def _agent_kwargs(user: str) -> Dict[str, Any]:
    if os.geteuid() != 0:
        return {}
    import pwd

    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        return {}
    return {"user": entry.pw_uid, "group": entry.pw_gid, "extra_groups": [],
            "env": {**os.environ, "HOME": entry.pw_dir, "USER": entry.pw_name, "LOGNAME": entry.pw_name}}


def find_skill(config: Path, name: str) -> Optional[Path]:
    """The folder of the skill the Skill tool is opening ("name" or "plugin:name"), in the run's configuration."""
    plain = name.split(":", 1)[-1].strip().strip("/")
    if not plain:
        return None
    for candidate in [config / "skills" / plain, *sorted((config / "plugins").glob(f"*/skills/{plain}"))]:
        if (candidate / "SKILL.md").exists():
            return candidate.resolve()
    return None


def resolve_inline(skill: Path, gate, workspace: str, user: str) -> str:
    """Run a skill's own shell lines as it loads, each through JAI's gate (sandbox_policy) as the agent user in the
    workspace; returns what Claude is told with the skill: each line and its output (a refused line says why)."""
    try:
        text = (skill / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    results: List[str] = []
    for match in INLINE.finditer(text):
        command = match.group("cmd")
        if command is None:
            continue
        payload = {"command": command, "cwd": workspace, "is_input": False}
        refusal = gate.check("terminal", payload)
        if refusal:
            gate.record("terminal", payload, False, refusal, refused=True)
            results.append(f"$ {command}\n[not run: {refusal}]")
            continue
        try:
            done = subprocess.run(["bash", "-lc", command], cwd=workspace, capture_output=True, text=True,
                                  timeout=INLINE_SECONDS, stdin=subprocess.DEVNULL, **_agent_kwargs(user))
            output, code = ((done.stdout or "") + (done.stderr or "")).strip(), done.returncode
        except subprocess.TimeoutExpired:
            output, code = f"[stopped after {INLINE_SECONDS} seconds]", 124
        gate.record("terminal", payload, code == 0, output[-2000:], exit_code=code)
        results.append(f"$ {command}\n{output[-4000:]}" + (f"\n[exit code {code}]" if code else ""))
    if not results:
        return ""
    return (f"JAI ran the shell lines of the skill {skill.name} through its gate, in {workspace}; each shown as "
            "[shell command execution disabled by policy] in the skill is, in order:\n\n" + "\n\n".join(results))


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

    def __init__(self, run, gate, workspace: str, config: Optional[Path] = None):
        self.run, self.gate, self.workspace, self.config = run, gate, workspace, config
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
        if tool == "Skill" and self.config is not None:
            skill = find_skill(self.config, str(args.get("skill") or args.get("name") or args.get("command") or ""))
            told = await asyncio.to_thread(resolve_inline, skill, self.gate, self.workspace, AGENT_USER) \
                if skill is not None else ""  # its own shell lines run now, through JAI's gate
            if told:
                decision = _allow("A skill; its own shell lines went through JAI's gate.")
                decision["hookSpecificOutput"]["additionalContext"] = told
                return decision
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
        plugins=json.loads((config / "plugins.json").read_text()) if (config / "plugins.json").is_file() else [],
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
        env={**session_env(request, config, backend_url), **ecc_env(request)},
        stderr=lambda line: logger.debug("claude %s: %s", request.run_id, line),
        # One message from Claude Code can carry a whole picture: the Read tool returns an image as a message of
        # its own, and a 1080x1920 still is over the SDK's 1 MB default (24 November: episode 2 stopped on
        # CLIJSONDecodeError at the first still it opened, twice). The SDK's own setting for it.
        max_buffer_size=MESSAGE_LIMIT,
    )


STATUS = {"success": "finished", "error_max_turns": "stopped", "error_max_budget_usd": "stopped",
          "error_during_execution": "error"}


async def execute(run, gate, rules: str, backend_url: str, sandbox_token: str, skills_root: Path,
                  refused: set) -> None:
    """One run, start to end: sets run.status, final_message, error, tokens and cost as the OpenHands path does."""
    import claude_agent_sdk as sdk

    request = run.request
    config = prepare_config(request.run_id, list(request.skills), skills_root, refused,
                            in_full=list(request.skills_in_full), mission_id=request.mission_id,
                            plugins=list(request.plugins))
    server, tools_client, note = (await jai_server(sdk, request.run_id, backend_url, sandbox_token)
                                  if request.jai_tools else (None, None, ""))
    if note:
        run.notes = note
    hooks = Hooks(run, gate, request.workspace, config)
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
                if kind == "AssistantMessage" and getattr(message, "model", None):
                    # Every reply names the model that wrote it, the session's workers' included.
                    seen = run.models.setdefault(str(message.model), {"replies": 0, "cost_usd": 0.0})
                    seen["replies"] += 1
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
                    for name, used in (getattr(message, "model_usage", None) or {}).items():
                        # The session's own account of each model it used, with what each cost.
                        seen = run.models.setdefault(str(name), {"replies": 0, "cost_usd": 0.0})
                        seen["cost_usd"] = round(float((used or {}).get("costUSD") or 0.0), 6)
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
