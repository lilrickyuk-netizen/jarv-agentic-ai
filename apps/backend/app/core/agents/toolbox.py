"""
JARV Backend - Agent toolbox

The single way a specialist agent touches the world. Every call is
authority-checked, permission-checked (hard boundaries pause only the blocked
action), logged to the task, the operations feed, and the audit trail, and
confined to the mission's workspace.

Two execution paths, one rulebook:

- Workspace tools (list/read/search/write files, run commands, git, memory,
  web reads, package/CVE checks) run through ``ToolRuntime``: approved-root
  scope, secret redaction, command classification, FileChange and CommandRun
  records, and the Richard boundary chain for approval-gated actions. On top
  of that, the toolbox confines every path to the workspace's own registered
  folder, so an agent working on one project cannot read another project or
  anything else on the machine.
- Registry tools (code analysis, CRM, calendar, Slack, email, experience,
  approval/boundary/checkpoint, HTTP, backups, ...) run through
  ``ToolBase.execute``: authority, central permission policy, and a ToolRun.
  Any path argument is resolved inside the workspace folder first; a path
  outside it is refused before the tool runs.

Authority: the effective level is the lower of the agent's level (mapped onto
the design's 1-7 scale) and the workspace's authority level. A sub-agent's
config carries its parent's ceiling, so it can never exceed it.
"""
from __future__ import annotations

import fnmatch
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

logger = logging.getLogger(__name__)

# AgentBase.AuthorityLevel (0-10) -> design authority (1-7). Level 7 (live
# release) is never reachable automatically; it needs a Richard approval window.
_AUTHORITY_MAP = {0: 1, 1: 1, 2: 2, 3: 3, 4: 4, 5: 4, 6: 4, 7: 5, 8: 6, 9: 6, 10: 6}

_PATH_KEYS = ("path", "repo_path", "file_path", "directory", "dir", "cwd", "source",
              "destination", "target_path", "root", "project_path")

# Command arguments that would reach outside the workspace even with the working
# directory set to it: inline interpreter code, home/env-var paths, traversal.
_INLINE_CODE_FLAGS = {"-c", "-e", "--eval", "-p", "--print", "-r"}
_INTERPRETERS = {"python", "python3", "node", "deno", "bun", "ruby", "perl", "php", "bash", "sh", "zsh", "pwsh", "powershell"}

_SEARCH_SKIP = {".git", "node_modules", ".next", "dist", "build", "__pycache__", ".venv", "venv",
                ".mypy_cache", ".pytest_cache", "coverage"}
_SEARCH_MAX_FILES = 4000
_SEARCH_MAX_BYTES = 200_000
_RESULT_CHARS = 8000

# Spec / legacy tool names -> toolbox tool. Registry file and command tools are
# never exposed directly (they are not workspace-confined); their names map to
# the confined workspace equivalents.
ALIASES: Dict[str, str] = {
    "file_read": "read_file", "file_write": "write_file", "file_patch": "edit_file",
    "file_list": "list_files", "file_tree": "list_files", "file_search": "search_files",
    "file_grep": "search_files", "file_metadata": "get_file_metadata", "file_move": "move_file",
    "file_copy": "copy_file", "file_delete": "delete_file_with_boundary",
    "command_run": "run_command", "command_timeout": "run_command",
    "run_safe_readonly_command": "run_command",
    "git_branch": "git_create_branch", "git_push": "git_push_with_boundary",
    "memory_store": "memory_add", "memory_retrieve": "memory_search", "memory": "memory_search",
    "http_get": "fetch_url", "scan_workspace": "scan_workspace",
}

# Registry categories that are reachable only through the confined workspace tools.
_UNCONFINED_CATEGORIES = {"file", "command", "terminal", "process"}
# Registry tools that change remote state or history; reachable only via
# run_command, where the command classifier and boundary chain apply.
_REGISTRY_DENY = {"git_push", "git_reset", "git_rebase", "git_clone", "git_merge", "git_config",
                  "git_revert", "git_init", "git_fetch", "git_pull", "git_stash", "git_tag",
                  "git_checkout", "git_branch", "git_commit", "git_add",
                  "command_sudo", "process_kill", "file_delete", "file_permissions",
                  "workspace_delete", "resource_terminate"}


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    kind: str                      # "workspace" | "registry"
    registry_name: Optional[str] = None


@dataclass
class ToolCallRecord:
    name: str
    args: Dict[str, Any]
    success: bool
    blocked: bool = False
    requires_approval: bool = False
    summary: str = ""


def effective_authority(agent_level: int, workspace_level: Optional[int]) -> int:
    mapped = _AUTHORITY_MAP.get(int(agent_level), 1)
    if workspace_level is None:
        return mapped
    return max(1, min(mapped, int(workspace_level)))


def _schema(properties: Dict[str, Any], required: Sequence[str] = ()) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required)}


_PATH_PROP = {"type": "string", "description": "Path inside the workspace (relative paths are resolved from the workspace root)"}

WORKSPACE_TOOLS: Dict[str, ToolSpec] = {
    "list_files": ToolSpec("list_files", "List files and folders at a path in the workspace.",
                           _schema({"path": _PATH_PROP}), "workspace"),
    "read_file": ToolSpec("read_file", "Read a text file in the workspace (secret files are redacted).",
                          _schema({"path": _PATH_PROP}, ["path"]), "workspace"),
    "search_files": ToolSpec(
        "search_files",
        "Find files in the workspace by name pattern (glob, e.g. '*.py') and/or by text they contain.",
        _schema({"pattern": {"type": "string", "description": "Glob for file names, e.g. '*.ts'"},
                 "contains": {"type": "string", "description": "Text the file must contain (case-insensitive)"},
                 "path": _PATH_PROP}), "workspace"),
    "scan_workspace": ToolSpec("scan_workspace", "Summarise the workspace: stack, package manager, entry points, build files.",
                               _schema({"path": _PATH_PROP}), "workspace"),
    "write_file": ToolSpec("write_file", "Create or replace a file in the workspace with the full new content.",
                           _schema({"path": _PATH_PROP, "content": {"type": "string"}}, ["path", "content"]),
                           "workspace"),
    "run_command": ToolSpec(
        "run_command",
        "Run ONE command in the workspace (no &&, ;, |, > or $(...)). Read-only, build and test commands "
        "run; installs need trusted local package managers; destructive, deploy, push, and network "
        "commands are blocked or need approval.",
        _schema({"command": {"type": "string"}, "cwd": _PATH_PROP}, ["command"]), "workspace"),
    "git_status": ToolSpec("git_status", "Show git status of the workspace repository.",
                           _schema({"path": _PATH_PROP}), "workspace"),
    "git_diff": ToolSpec("git_diff", "Show uncommitted changes in the workspace repository.",
                         _schema({"path": _PATH_PROP}), "workspace"),
    "git_log": ToolSpec("git_log", "Show recent commits in the workspace repository.",
                        _schema({"path": _PATH_PROP, "count": {"type": "integer"}}), "workspace"),
    "memory_add": ToolSpec("memory_add", "Store a durable fact or lesson in this workspace's memory.",
                           _schema({"content": {"type": "string"},
                                    "memory_type": {"type": "string", "description": "e.g. decision, incident, customer, task"}},
                                   ["content"]), "workspace"),
    "memory_search": ToolSpec("memory_search", "Search this workspace's memory.",
                              _schema({"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
                              "workspace"),
    "fetch_url": ToolSpec("fetch_url", "Fetch a public web page (read-only; private networks are blocked).",
                          _schema({"url": {"type": "string"}}, ["url"]), "workspace"),
    "check_package_registry": ToolSpec("check_package_registry", "Look up a package on its official registry.",
                                       _schema({"name": {"type": "string"},
                                                "ecosystem": {"type": "string", "enum": ["npm", "pypi"]}}, ["name"]),
                                       "workspace"),
    "check_cve": ToolSpec("check_cve", "Check a package version for known vulnerabilities (OSV).",
                          _schema({"name": {"type": "string"}, "ecosystem": {"type": "string"},
                                   "version": {"type": "string"}}, ["name"]), "workspace"),
    "asset_licence_check": ToolSpec("asset_licence_check", "Check an asset's licence on an approved source.",
                                    _schema({"query": {"type": "string"}, "source": {"type": "string"}},
                                            ["query", "source"]), "workspace"),
}

_P = {"path": _PATH_PROP}
WORKSPACE_TOOLS.update({
    "edit_file": ToolSpec("edit_file", "Replace exact text in a workspace file (old_text must occur once unless "
                          "replace_all). Prefer this to rewriting a whole file.",
                          _schema({"path": _PATH_PROP, "old_text": {"type": "string"}, "new_text": {"type": "string"},
                                   "replace_all": {"type": "boolean"}}, ["path", "old_text", "new_text"]), "workspace"),
    "create_folder": ToolSpec("create_folder", "Create a folder (and parents) in the workspace.",
                              _schema(_P, ["path"]), "workspace"),
    "move_file": ToolSpec("move_file", "Move or rename a file or folder inside the workspace.",
                          _schema({"source": _PATH_PROP, "destination": _PATH_PROP, "overwrite": {"type": "boolean"}},
                                  ["source", "destination"]), "workspace"),
    "copy_file": ToolSpec("copy_file", "Copy a file or folder inside the workspace.",
                          _schema({"source": _PATH_PROP, "destination": _PATH_PROP, "overwrite": {"type": "boolean"}},
                                  ["source", "destination"]), "workspace"),
    "delete_file_with_boundary": ToolSpec(
        "delete_file_with_boundary", "Delete a file or folder in the workspace. Pauses for Richard's approval.",
        _schema({"path": _PATH_PROP, "reason": {"type": "string"}}, ["path", "reason"]), "workspace"),
    "get_file_metadata": ToolSpec("get_file_metadata", "Size, type and modification time of a workspace path.",
                                  _schema(_P, ["path"]), "workspace"),
    "detect_workspace_type": ToolSpec("detect_workspace_type", "What kind of project this is (web app, backend, "
                                      "mobile, document pack, ...).", _schema(_P), "workspace"),
    "detect_stack": ToolSpec("detect_stack", "Languages, frameworks, package managers and Docker files in use.",
                             _schema(_P), "workspace"),
    "detect_commands": ToolSpec("detect_commands", "The project's real install/build/test/run commands, from its "
                                "own files.", _schema(_P), "workspace"),
    "find_missing_files": ToolSpec("find_missing_files", "Files a project of this kind should have but does not "
                                   "(README, .gitignore, tests, Dockerfile, .env.example ...).", _schema(_P), "workspace"),
    "run_build": ToolSpec("run_build", "Build the project with its detected build command (or the given one).",
                          _schema({"path": _PATH_PROP, "command": {"type": "string"}}), "workspace"),
    "run_tests": ToolSpec("run_tests", "Run the project's tests with its detected test command (or the given one).",
                          _schema({"path": _PATH_PROP, "command": {"type": "string"}}), "workspace"),
    "install_package": ToolSpec("install_package", "Install one package into the project with its own package "
                                "manager (npm/pnpm/yarn or poetry/pip).",
                                _schema({"name": {"type": "string"}, "ecosystem": {"type": "string", "enum": ["npm", "pypi"]},
                                         "dev": {"type": "boolean"}, "path": _PATH_PROP}, ["name"]), "workspace"),
    "check_installed": ToolSpec("check_installed", "Whether a package is declared in the project's manifests and "
                                "installed, with versions.", _schema({"name": {"type": "string"}, "path": _PATH_PROP},
                                                                       ["name"]), "workspace"),
    "get_command_log": ToolSpec("get_command_log", "Recent commands run in this workspace with exit codes and output tails.",
                                _schema({"limit": {"type": "integer"}}), "workspace"),
    "git_create_branch": ToolSpec("git_create_branch", "Create a git branch in the workspace and switch to it.",
                                  _schema({"name": {"type": "string"}, "path": _PATH_PROP, "switch": {"type": "boolean"}},
                                          ["name"]), "workspace"),
    "git_push_with_boundary": ToolSpec("git_push_with_boundary", "Push the current branch to a remote. Pauses for "
                                       "Richard's approval.",
                                       _schema({"remote": {"type": "string"}, "branch": {"type": "string"},
                                                "path": _PATH_PROP}), "workspace"),
    "memory_link_to_workspace": ToolSpec("memory_link_to_workspace", "Adopt a global memory into this workspace.",
                                         _schema({"memory_id": {"type": "string"}}, ["memory_id"]), "workspace"),
    "memory_link_to_task": ToolSpec("memory_link_to_task", "Attach a memory to a task in this workspace.",
                                    _schema({"memory_id": {"type": "string"}, "task_id": {"type": "string"}},
                                            ["memory_id"]), "workspace"),
})

_FILESYSTEM_TOOLS = {"list_files", "read_file", "search_files", "scan_workspace", "write_file",
                     "run_command", "git_status", "git_diff", "git_log", "edit_file", "create_folder",
                     "move_file", "copy_file", "delete_file_with_boundary", "get_file_metadata",
                     "detect_workspace_type", "detect_stack", "detect_commands", "find_missing_files",
                     "run_build", "run_tests", "install_package", "check_installed", "git_create_branch",
                     "git_push_with_boundary"}


def _clip(value: Any, limit: int = _RESULT_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + f"… [truncated {len(text) - limit} chars]"


class AgentToolbox:
    """Tools one agent may use for one task, confined to one workspace."""

    def __init__(self, agent: Any, context: Any):
        self.agent = agent
        self.context = context
        self.calls: List[ToolCallRecord] = []
        self.root_host: Optional[str] = None
        self.root_container: Optional[Path] = None
        self.workspace_authority: Optional[int] = None
        self.runtime = None
        self._specs: Dict[str, ToolSpec] = {}
        self._prepared = False

    # ----- setup ---------------------------------------------------------------

    async def prepare(self) -> "AgentToolbox":
        if self._prepared:
            return self
        from sqlalchemy import select

        from app.core.command.tool_runtime import ToolRuntime
        from app.core.workspaces import fs_inspector
        from app.models.workspace import Workspace

        db = self.context.db_session
        if db is None or self.context.workspace_id is None:
            raise RuntimeError("Agent tools need a database session and a workspace")
        workspace = (await db.execute(
            select(Workspace).where(Workspace.id == self.context.workspace_id)
        )).scalar_one_or_none()
        if workspace is None:
            raise RuntimeError("Workspace not found")
        self.workspace_authority = workspace.authority_level
        root = (workspace.config or {}).get("root_path") if isinstance(workspace.config, dict) else None
        if root:
            container = fs_inspector.host_to_container(root)
            if container is not None:
                self.root_host, self.root_container = root, container.resolve()
        level = effective_authority(int(self.agent.config.authority_level), self.workspace_authority)
        self.runtime = ToolRuntime(
            db, workspace.id, self.context.task_id,
            operator=f"agent:{self.agent.name}", authority_level=level,
            user_id=self.context.user_id, session_id=self.context.session_id,
            agent_id=self.agent.config.agent_id,
        )
        self._specs = self._resolve_specs()
        self._prepared = True
        return self

    def _resolve_specs(self) -> Dict[str, ToolSpec]:
        from app.core.tools.registry import get_registry

        registry = get_registry()
        specs: Dict[str, ToolSpec] = {}
        for requested in self.agent.get_allowed_tools():
            name = ALIASES.get(requested, requested)
            if name in WORKSPACE_TOOLS:
                if name in _FILESYSTEM_TOOLS and self.root_container is None:
                    continue  # no registered folder: no filesystem access at all
                specs[name] = WORKSPACE_TOOLS[name]
                continue
            if name in _REGISTRY_DENY:
                continue
            meta = registry.get_metadata(name)
            if meta is None or not meta.is_implemented or meta.category in _UNCONFINED_CATEGORIES:
                continue
            if meta.category == "agent":
                continue
            try:
                from app.core.tools.base import ToolConfig

                model = meta.tool_class(ToolConfig()).input_schema
                json_schema = model.model_json_schema()
            except Exception as exc:  # noqa: BLE001 - a tool without a usable schema is not offered
                logger.warning(f"tool {name} has no usable input schema: {exc}")
                continue
            json_schema.pop("title", None)
            specs[name] = ToolSpec(name, (meta.description or name)[:500], json_schema, "registry", name)
        return specs

    # ----- public ---------------------------------------------------------------

    @property
    def available(self) -> List[str]:
        return sorted(self._specs)

    def withhold(self, names) -> List[str]:
        """Remove tools for this run (approved tool-selection rules can only narrow, never add)."""
        removed = [n for n in names if self._specs.pop(n, None) is not None]
        return removed

    def model_tools(self) -> List[Dict[str, Any]]:
        return [{"name": spec.name, "description": spec.description, "input_schema": spec.input_schema}
                for spec in self._specs.values()]

    async def call(self, name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run one tool. Never raises; failures and blocks come back as results."""
        await self.prepare()
        args = dict(args or {})
        name = ALIASES.get(name, name)
        spec = self._specs.get(name)
        if spec is None:
            result = {"success": False, "blocked": True,
                      "reason": f"Tool '{name}' is not available to {self.agent.name} in this workspace."}
        else:
            try:
                if spec.kind == "workspace":
                    result = await self._workspace_call(name, args)
                else:
                    result = await self._registry_call(spec, args)
            except Exception as exc:  # noqa: BLE001 - reported to the agent, logged here
                logger.warning(f"{self.agent.name} tool {name} failed: {exc}", exc_info=True)
                result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        self.calls.append(ToolCallRecord(
            name=name, args={k: (v if len(str(v)) < 200 else str(v)[:200] + "…") for k, v in args.items()},
            success=bool(result.get("success")), blocked=bool(result.get("blocked")),
            requires_approval=bool(result.get("requires_approval")),
            summary=str(result.get("reason") or result.get("error") or "")[:300],
        ))
        return result

    # ----- path confinement --------------------------------------------------

    def _resolve_host(self, value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """(host_path, refusal). Relative paths resolve from the workspace root."""
        from app.core.workspaces import fs_inspector

        if self.root_host is None or self.root_container is None:
            return None, "This workspace has no registered folder; register it before using file tools."
        raw = (value or "").strip().strip('"').strip("'")
        windows_root = ":" in self.root_host[:3] or "\\" in self.root_host
        if not raw or raw in (".", "./"):
            candidate = self.root_host
        elif (windows_root and (":" in raw[:3] or raw.startswith("\\"))) or raw.startswith("/"):
            candidate = raw
        elif windows_root:
            candidate = str(PureWindowsPath(self.root_host) / PureWindowsPath(raw.replace("/", "\\")))
        else:
            candidate = str(PurePosixPath(self.root_host) / raw)
        container = fs_inspector.host_to_container(candidate)
        if container is None:
            return None, f"Path '{raw}' is outside this workspace ({self.root_host})."
        resolved = Path(os.path.normpath(str(container)))
        root = Path(os.path.normpath(str(self.root_container)))
        if resolved != root and root not in resolved.parents:
            return None, f"Path '{raw}' is outside this workspace ({self.root_host})."
        return candidate, None

    def _to_container(self, host: str) -> Path:
        from app.core.workspaces import fs_inspector

        return Path(os.path.normpath(str(fs_inspector.host_to_container(host))))

    def _to_host(self, container: Path) -> str:
        rel = container.relative_to(Path(os.path.normpath(str(self.root_container))))
        if ":" in self.root_host[:3] or "\\" in self.root_host:
            return str(PureWindowsPath(self.root_host) / PureWindowsPath(*rel.parts)) if rel.parts else self.root_host
        return str(PurePosixPath(self.root_host) / PurePosixPath(*rel.parts)) if rel.parts else self.root_host

    # ----- workspace tools ---------------------------------------------------

    async def _workspace_call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        from app.core.agents import workspace_ops

        rt = self.runtime
        if name in workspace_ops.HANDLERS:
            return await workspace_ops.HANDLERS[name](self, args)
        if name in _FILESYSTEM_TOOLS:
            key = "cwd" if name == "run_command" else "path"
            host, refusal = self._resolve_host(args.get(key))
            if refusal:
                return {"success": False, "blocked": True, "reason": refusal}
            if name == "list_files":
                return await rt.list_files(host)
            if name == "read_file":
                return await rt.read_file(host)
            if name == "scan_workspace":
                return await rt.scan_workspace(host)
            if name == "write_file":
                return await rt.write_file(host, str(args.get("content", "")), overwrite=True)
            if name == "search_files":
                return await self._search(host, args.get("pattern"), args.get("contains"))
            if name == "run_command":
                command = str(args.get("command", ""))
                refusal = self._command_refusal(command)
                if refusal:
                    await rt._record("run_command", {"command": command}, False, refusal)
                    return {"success": False, "blocked": True, "reason": refusal}
                return await rt.run_command(command, cwd_host=host, allow_build=True)
            if name == "git_status":
                return await rt.run_command("git status --short --branch", cwd_host=host, allow_build=True)
            if name == "git_diff":
                return await rt.run_command("git diff --stat", cwd_host=host, allow_build=True)
            if name == "git_log":
                count = max(1, min(int(args.get("count") or 10), 50))
                return await rt.run_command(f"git log --oneline -n {count}", cwd_host=host, allow_build=True)
        if name == "memory_add":
            return await rt.memory_add(str(args.get("content", "")), memory_type=str(args.get("memory_type") or "fact"))
        if name == "memory_search":
            return await rt.memory_search(str(args.get("query", "")), limit=int(args.get("limit") or 5))
        if name == "fetch_url":
            return await rt.fetch_url(str(args.get("url", "")))
        if name == "check_package_registry":
            return await rt.check_package_registry(str(args.get("name", "")), str(args.get("ecosystem") or "npm"))
        if name == "check_cve":
            return await rt.check_cve(str(args.get("name", "")), str(args.get("ecosystem") or "npm"),
                                      args.get("version"))
        if name == "asset_licence_check":
            return await rt.asset_licence_check(str(args.get("query", "")), str(args.get("source", "")))
        return {"success": False, "error": f"unknown workspace tool '{name}'"}

    def _command_refusal(self, command: str) -> Optional[str]:
        """Refuse commands whose arguments point outside the workspace."""
        import shlex

        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            return "Command could not be parsed; use one simple command."
        if not tokens:
            return "Empty command."
        program = os.path.basename(tokens[0]).lower()
        if program in _INTERPRETERS and any(t in _INLINE_CODE_FLAGS for t in tokens[1:]):
            return ("Inline interpreter code is not allowed for agents; write the script into the "
                    "workspace with write_file and run that file.")
        for token in tokens[1:]:
            value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
            if value.startswith("~") or "$" in value or "%" in value:
                return f"Argument '{token}' refers to a location outside the workspace."
            parts = value.replace("\\", "/").split("/")
            if ".." in parts:
                return f"Argument '{token}' leaves the workspace ('..' is not allowed)."
            absolute = value.startswith("/") or value.startswith("\\") or (len(value) > 2 and value[1] == ":")
            if absolute:
                _, refusal = self._resolve_host(value)
                if refusal:
                    return refusal
        return None

    async def _search(self, host: str, pattern: Optional[str], contains: Optional[str]) -> Dict[str, Any]:
        """Name/content search confined to the workspace; secret files are never opened."""
        from app.core.workspaces import fs_inspector

        denied = await self.runtime._enforce("search_files", path=host)
        if denied:
            return denied
        base = self._to_container(host)
        needle = (contains or "").lower()
        glob = pattern or "*"
        hits: List[Dict[str, Any]] = []
        scanned = 0
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SEARCH_SKIP and not fs_inspector._is_banned(d)]
            for filename in filenames:
                scanned += 1
                if scanned > _SEARCH_MAX_FILES or len(hits) >= 50:
                    break
                if not fnmatch.fnmatch(filename.lower(), glob.lower()):
                    continue
                path = Path(dirpath) / filename
                lower = filename.lower()
                secret = lower.startswith(".env") or lower.endswith(".env") or "secret" in lower or "key" in lower
                if fs_inspector._is_banned(str(path)) or (needle and secret):
                    continue
                line_hits: List[str] = []
                if needle:
                    try:
                        if path.stat().st_size > _SEARCH_MAX_BYTES:
                            continue
                        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                            if needle in line.lower():
                                line_hits.append(f"{number}: {line.strip()[:200]}")
                                if len(line_hits) >= 5:
                                    break
                    except OSError:
                        continue
                    if not line_hits:
                        continue
                hits.append({"path": self._to_host(path), "matches": line_hits})
        await self.runtime._record("search_files", {"path": host, "pattern": glob, "contains": contains},
                                   True, f"{len(hits)} matches", output={"count": len(hits)})
        return {"success": True, "matches": hits, "scanned": min(scanned, _SEARCH_MAX_FILES),
                "truncated": scanned > _SEARCH_MAX_FILES or len(hits) >= 50}

    # ----- registry tools ----------------------------------------------------

    async def _registry_call(self, spec: ToolSpec, args: Dict[str, Any]) -> Dict[str, Any]:
        from app.core.agents.base import AuthorityLevel
        from app.core.tools.base import ToolConfig, ToolContext
        from app.core.tools.registry import create_tool

        for key in _PATH_KEYS:
            if key in args and isinstance(args[key], str):
                host, refusal = self._resolve_host(args[key])
                if refusal:
                    return {"success": False, "blocked": True, "reason": refusal}
                args[key] = str(self._to_container(host))
        ctx = self.context
        level = self.agent.config.authority_level
        tool = create_tool(spec.registry_name, ToolConfig(
            workspace_id=ctx.workspace_id, user_id=ctx.user_id, agent_id=self.agent.config.agent_id,
            task_id=ctx.task_id, session_id=ctx.session_id,
            authority_level=level if isinstance(level, AuthorityLevel) else AuthorityLevel(int(level)),
        ))
        if tool is None:
            return {"success": False, "error": f"tool {spec.registry_name} could not be created"}
        approved = [str(self.root_container)] if self.root_container else []
        result = await tool.execute(args, ToolContext(
            workspace_id=ctx.workspace_id, user_id=ctx.user_id, agent_id=self.agent.config.agent_id,
            task_id=ctx.task_id, session_id=ctx.session_id, approved_folders=approved,
            approval_granted=bool(getattr(ctx, "approval_granted", False)),
            approved_tools=list(getattr(ctx, "approved_tools", []) or []),
            db_session=ctx.db_session, metadata={"via": "agent_toolbox", "agent": self.agent.name},
        ))
        data = result.result_data or {}
        return {"success": bool(result.success), "data": data, "output": result.output_text,
                "error": result.error_message, "blocked": bool(data.get("blocked")),
                "requires_approval": bool(data.get("requires_approval") or data.get("approvable"))}

    def summary(self) -> Dict[str, Any]:
        return {
            "workspace_root": self.root_host,
            "tools_available": self.available,
            "calls": [c.__dict__ for c in self.calls],
            "blocked": [c.name for c in self.calls if c.blocked],
            "approval_needed": [c.name for c in self.calls if c.requires_approval],
        }
