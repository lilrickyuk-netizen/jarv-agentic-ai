"""
JAI Backend - Agent toolbox

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
import re
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
# A Windows environment variable such as %USERPROFILE% or %APPDATA% (three or more characters between %).
_WINDOWS_VARIABLE = re.compile(r"%[A-Za-z_][A-Za-z0-9_]{2,}%")
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

CONSULT_TOOL = "consult_specialist_knowledge"
CREATIVE_TOOLS = ("generate_image", "make_voiceover", "make_video", "social_channels", "social_draft")
WEB_TOOLS = ("web_search", "research_web", "fetch_url", "read_mission_report")
TRACE_TOOL = "trace_artifact"
# Wave 5: understanding code through Serena's language servers (read-only), offered in a folder when Serena runs.
CODE_TOOLS = ("code_overview", "code_find_symbol", "code_references", "code_implementations", "code_diagnostics")
# Wave 6, each offered to every agent while its service is turned on.
SERVICE_TOOLS = {"read_document": "docs", "use_browser": "browser", "knowledge_graph_search": "knowledge",
                 "knowledge_graph_add": "knowledge", "recall_richard": "knowledge", "run_prompt_checks": "evals"}

# Registry categories that are reachable only through the confined workspace tools.
_UNCONFINED_CATEGORIES = {"file", "command", "terminal", "process"}
# Registry tools that change remote state or history; reachable only via
# run_command, where the command classifier and boundary chain apply.
_REGISTRY_DENY = {"git_push", "git_reset", "git_rebase", "git_clone", "git_merge", "git_config",
                  "git_revert", "git_init", "git_fetch", "git_pull", "git_stash", "git_tag",
                  "git_checkout", "git_branch", "git_commit", "git_add",
                  "command_sudo", "process_kill", "file_delete", "file_permissions",
                  "workspace_delete", "resource_terminate"}


def _service_on(name: str) -> bool:
    from app.core.config import settings

    setting = {"docs": "DOCLING_URL", "browser": "BROWSER_URL", "knowledge": "KNOWLEDGE_URL",
               "evals": "PROMPTFOO_URL"}[SERVICE_TOOLS[name]]
    return bool(str(getattr(settings, setting, "") or "").strip())


def _code_available(root_container: Optional[Path]) -> bool:
    if root_container is None:
        return False
    from app.core.code.serena import serena_url

    return bool(serena_url())


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
    "read_file": ToolSpec(
        "read_file",
        "Read a text file in the workspace (secret files are redacted), up to 16,000 characters from offset. "
        "When the result's next_offset is not null the file continues: call again with that offset until it "
        "is null, and read the whole file before relying on it.",
        _schema({"path": _PATH_PROP,
                 "offset": {"type": "integer", "description": "Character offset to read from (0 = start)"}},
                ["path"]), "workspace"),
    "search_files": ToolSpec(
        "search_files",
        "Find files in the workspace by name pattern (glob, e.g. '*.py') and/or by text they contain.",
        _schema({"pattern": {"type": "string", "description": "Glob for file names, e.g. '*.ts'"},
                 "contains": {"type": "string", "description": "Text the file must contain (case-insensitive)"},
                 "path": _PATH_PROP}), "workspace"),
    "scan_workspace": ToolSpec("scan_workspace", "Summarise the workspace: stack, package manager, entry points, build files.",
                               _schema({"path": _PATH_PROP}), "workspace"),
    "write_file": ToolSpec(
        "write_file",
        "Create or replace a file in the workspace with the full new content. Write a long file in parts: "
        "the first part without append, each further part with append=true.",
        _schema({"path": _PATH_PROP, "content": {"type": "string"},
                 "append": {"type": "boolean", "description": "Add content to the end of the file"}},
                ["path", "content"]),
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
    "fetch_url": ToolSpec("fetch_url", "Read a public web page as text (read-only; private networks are blocked). "
                          "Pages built by JavaScript are read through JAI's browser automatically; render=true "
                          "forces it.", _schema({"url": {"type": "string"}, "render": {"type": "boolean"}}, ["url"]),
                          "workspace"),
    "web_search": ToolSpec("web_search", "Search the web through JAI's own search engine (Google, Bing, Brave, "
                           "DuckDuckGo, Wikipedia, GitHub and more at once). Returns titles, links and snippets; "
                           "read a result with fetch_url. category: general, news, it or science; time_range: day, "
                           "week, month or year for recent things.",
                           _schema({"query": {"type": "string"}, "category": {"type": "string",
                                    "enum": ["general", "news", "it", "science"]},
                                    "time_range": {"type": "string", "enum": ["day", "week", "month", "year"]},
                                    "limit": {"type": "integer"}}, ["query"]), "workspace"),
    "make_voiceover": ToolSpec("make_voiceover", "Record narration in JAI's own natural British voice (on JAI's GPU, "
                               "free) and save it in the workspace as a WAV (assets/audio/ by default), recorded in "
                               "ASSET_LICENCES.md. Write the text exactly as it should be spoken.",
                               _schema({"text": {"type": "string"}, "path": _PATH_PROP}, ["text"]), "workspace"),
    "make_video": ToolSpec("make_video", "Make a short video for social media (15 to 120 seconds): JAI writes the "
                           "narration from your brief, narrates it in its own voice, makes the footage on its GPU (or "
                           "uses Pexels stock footage when set up), adds subtitles and saves the MP4 and its script "
                           "in the workspace (assets/videos/ by default). Nothing is published. Takes several "
                           "minutes. Give a full brief: the message, the facts to use, the audience, the call to "
                           "action. aspect: portrait (TikTok, Reels, Shorts), landscape or square.",
                           _schema({"brief": {"type": "string"}, "seconds": {"type": "integer"},
                                    "aspect": {"type": "string", "enum": ["portrait", "landscape", "square"]},
                                    "audience": {"type": "string"},
                                    "footage": {"type": "string", "enum": ["auto", "generated", "stock"]},
                                    "path": _PATH_PROP}, ["brief"]), "workspace"),
    "social_channels": ToolSpec("social_channels", "The social media channels Richard has connected in Postiz "
                                "(name and platform), to draft posts for.", _schema({}), "workspace"),
    "social_draft": ToolSpec("social_draft", "Draft a social post in Postiz for Richard's connected channels (all "
                             "of them unless named), with images or videos from the workspace attached. It is saved "
                             "as a draft only: Richard reviews and schedules it in Postiz himself; nothing is "
                             "published by JAI.",
                             _schema({"text": {"type": "string"},
                                      "channels": {"type": "array", "items": {"type": "string"}},
                                      "media": {"type": "array", "items": {"type": "string"},
                                                "description": "Paths in the workspace of images or videos"}},
                                     ["text"]), "workspace"),
    "read_document": ToolSpec("read_document", "Read a PDF, Word, PowerPoint, Excel, HTML or scanned document as "
                              "text with its headings and tables (Docling; scans are read with OCR): a file in "
                              "the workspace (path) or a public address (url). Long documents come in parts: pass "
                              "next_offset as offset for the next one.",
                              _schema({"path": _PATH_PROP, "url": {"type": "string"},
                                       "offset": {"type": "integer"}}), "workspace"),
    "use_browser": ToolSpec("use_browser", "Use a real web browser, one action at a time, for pages that need "
                            "clicking, typing or following links (sign-up and waitlist flows, menus, dashboards, "
                            "pages built by scripts). open a url; the answer lists what is on the page with a "
                            "number for each thing you can click, type into or choose. Then click (index), type "
                            "(index, text), select (index, text), options (index), scroll (down true/false, pages), "
                            "keys (e.g. Enter), back, find_text (text), switch_tab (tab_id), read, close. Public "
                            "pages only, no sign-ins; it never types passwords, card or bank details.",
                            _schema({"action": {"type": "string", "enum": ["open", "read", "click", "type", "select",
                                                                           "options", "scroll", "keys", "back",
                                                                           "find_text", "switch_tab", "wait", "close"]},
                                     "url": {"type": "string"}, "index": {"type": "integer"},
                                     "text": {"type": "string"}, "down": {"type": "boolean"},
                                     "pages": {"type": "number"}, "keys": {"type": "string"},
                                     "tab_id": {"type": "string"}}, ["action"]), "workspace"),
    "knowledge_graph_search": ToolSpec("knowledge_graph_search", "Search what JAI's finished work in this workspace "
                                       "has established, as facts with when they became true (and stopped being "
                                       "true): decisions, choices, prices, who uses what.",
                                       _schema({"query": {"type": "string"}}, ["query"]), "workspace"),
    "knowledge_graph_add": ToolSpec("knowledge_graph_add", "Add something learned to this workspace's knowledge "
                                    "graph (a decision, a finding, a changed fact), in a sentence or a short "
                                    "paragraph with names and dates.",
                                    _schema({"fact": {"type": "string"}, "title": {"type": "string"}}, ["fact"]),
                                    "workspace"),
    "recall_richard": ToolSpec("recall_richard", "What Richard has told JAI about himself, his projects and how he "
                               "wants things done (his preferences and decisions), on a subject.",
                               _schema({"query": {"type": "string"}}, ["query"]), "workspace"),
    "run_prompt_checks": ToolSpec("run_prompt_checks", "Check JAI's prompts with promptfoo: suite voice checks the "
                                  "voice's instructions; suite boundaries checks the given instructions never cross "
                                  "Richard's hard boundaries. Costs about a cent; takes a minute or two.",
                                  _schema({"suite": {"type": "string", "enum": ["voice", "boundaries"]},
                                           "instructions": {"type": "string"}}, ["suite"]), "workspace"),
    "code_overview": ToolSpec("code_overview", "See the classes, functions and methods in a source file (from its "
                              "language server), to understand a file before reading or changing it.",
                              _schema({"path": _PATH_PROP}, ["path"]), "workspace"),
    "code_find_symbol": ToolSpec("code_find_symbol", "Find where a class, function or method is defined, across "
                                 "the project or in one path, with its body if include_body is true. symbol is a "
                                 "name or a name path such as MyClass/method; part of a name matches.",
                                 _schema({"symbol": {"type": "string"}, "path": _PATH_PROP,
                                          "include_body": {"type": "boolean"}}, ["symbol"]), "workspace"),
    "code_references": ToolSpec("code_references", "Find every place that uses a symbol (who calls a function, "
                                "who uses a class) before changing it. symbol is its name path, path the file "
                                "that defines it.",
                                _schema({"symbol": {"type": "string"}, "path": _PATH_PROP}, ["symbol", "path"]),
                                "workspace"),
    "code_implementations": ToolSpec("code_implementations", "Find the implementations of an interface, abstract "
                                     "class or method. symbol is its name path, path the file that defines it.",
                                     _schema({"symbol": {"type": "string"}, "path": _PATH_PROP},
                                             ["symbol", "path"]), "workspace"),
    "code_diagnostics": ToolSpec("code_diagnostics", "The errors and warnings the language server finds in a "
                                 "file (type errors, unknown names, bad imports), grouped by symbol: check a file "
                                 "after changing it.",
                                 _schema({"path": _PATH_PROP}, ["path"]), "workspace"),
    "read_mission_report": ToolSpec("read_mission_report", "Read another mission's whole report in this "
                                    "workspace (its findings, recommendations and evidence): give its id or its first "
                                    "eight characters, or nothing for the latest finished mission.",
                                    _schema({"mission": {"type": "string"}}), "workspace"),
    "generate_image": ToolSpec("generate_image", "Make an image on JAI's own GPU (FLUX.1-schnell, Apache-2.0, "
                               "commercial use allowed) and save it in the workspace (assets/images/ by default), "
                               "recorded in ASSET_LICENCES.md. Describe it fully: subject, setting, style, light, "
                               "colours, composition and any words to show (in quotes). shape: square, landscape, "
                               "portrait, thumbnail (1280x720), story, wide or banner. Takes one to two minutes.",
                               _schema({"prompt": {"type": "string"},
                                        "shape": {"type": "string", "enum": ["square", "landscape", "portrait",
                                                                             "thumbnail", "story", "wide", "banner"]},
                                        "path": _PATH_PROP}, ["prompt"]), "workspace"),
    "research_web": ToolSpec("research_web", "Research a question on the web and get a cited answer: JAI plans "
                             "several searches, reads the best sources and writes what they say with [n] "
                             "citations and the source list. Use it for current facts, library and API changes, "
                             "prices, regulations, competitors and comparisons; depth deep reads about ten sources.",
                             _schema({"question": {"type": "string"},
                                      "depth": {"type": "string", "enum": ["quick", "deep"]},
                                      "time_range": {"type": "string", "enum": ["day", "week", "month", "year"]}},
                                     ["question"]), "workspace"),
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

_FILESYSTEM_TOOLS = {"generate_image", "make_voiceover", "make_video", "list_files", "read_file", "search_files", "scan_workspace", "write_file",
                     "run_command", "git_status", "git_diff", "git_log", "edit_file", "create_folder",
                     "move_file", "copy_file", "delete_file_with_boundary", "get_file_metadata",
                     "detect_workspace_type", "detect_stack", "detect_commands", "find_missing_files",
                     "run_build", "run_tests", "install_package", "check_installed", "git_create_branch",
                     "git_push_with_boundary"}


# Told to the model when a tool call's arguments were cut off (output limit) or are not valid JSON.
BROKEN_ARGUMENTS = ("Your arguments for {name} were cut off or are not valid JSON, most likely because the reply hit its output limit. Nothing was done. Write a long file in parts: the first part with write_file, then the rest with append set to true.")


# A read_file part (16,000 characters, plus JSON escaping) is passed back whole; other results are clipped.
READ_RESULT_CHARS = 32000


def _offset(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def result_limit(tool: str) -> int:
    # A file or document part, and a browser page, are passed back whole.
    return READ_RESULT_CHARS if tool in ("read_file", "read_document", "use_browser") else _RESULT_CHARS


def _clip(value: Any, limit: int = _RESULT_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"… [truncated {len(text) - limit} chars]"


class AgentToolbox:
    """Tools one agent may use for one task, confined to one workspace."""

    def __init__(self, agent: Any, context: Any, *, runtime: Any = None, root_host: Optional[str] = None):
        """``runtime``: an existing ToolRuntime to act through (a mission's own, so its calls, authority
        and boundary handling stay the mission's). ``root_host``: the folder to confine to when the mission
        works in a folder other than its workspace's registered one; it must still map into JAI's mounts."""
        self.agent = agent
        self.context = context
        self.calls: List[ToolCallRecord] = []
        self.root_host: Optional[str] = None
        self.root_container: Optional[Path] = None
        self.workspace_authority: Optional[int] = None
        self.runtime = runtime
        self._requested_root = root_host
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
        for candidate in (self._requested_root, root):
            container = fs_inspector.host_to_container(candidate) if candidate else None
            if container is not None:
                self.root_host, self.root_container = candidate, container.resolve()
                break
        if self.runtime is None:
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
                if name in CODE_TOOLS and not _code_available(self.root_container):
                    continue
                if name in SERVICE_TOOLS and not _service_on(name):
                    continue
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
        # Every agent working in a folder can make images for it (Wave 4a).
        if self.root_container is not None:
            for creative in CREATIVE_TOOLS:
                specs.setdefault(creative, WORKSPACE_TOOLS[creative])
        # Every agent working in a folder can read its code as an IDE does when Serena runs (read-only, Wave 5).
        if _code_available(self.root_container):
            for code in CODE_TOOLS:
                specs.setdefault(code, WORKSPACE_TOOLS[code])
        # Every agent can read documents, use the browser, consult the knowledge graph and Richard's memory, and
        # check prompts, while those services run (Wave 6).
        for name in SERVICE_TOOLS:
            if _service_on(name):
                specs.setdefault(name, WORKSPACE_TOOLS[name])
        # Every agent can search and research the web and read public pages (read-only, Wave 3).
        for web in WEB_TOOLS:
            specs.setdefault(web, WORKSPACE_TOOLS[web])
        # Every agent can consult its field's specialist knowledge and trace the artifact graph (both read-only).
        for always in (CONSULT_TOOL, TRACE_TOOL):
            meta = registry.get_metadata(always)
            if meta is not None and meta.is_implemented and always not in specs:
                from app.core.tools.base import ToolConfig

                schema = meta.tool_class(ToolConfig()).input_schema.model_json_schema()
                schema.pop("title", None)
                specs[always] = ToolSpec(always, (meta.description or always)[:500], schema, "registry", always)
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
        # A path copied out of a sentence keeps its punctuation: "(C:\\Users\\...\\MYCO)." is the folder itself.
        raw = (value or "").strip().strip('"').strip("'").strip("`").lstrip("([").rstrip(").,;:]").strip()
        windows_root = ":" in self.root_host[:3] or "\\" in self.root_host
        if not raw or raw in (".", "./"):
            candidate = self.root_host
        elif (windows_root and ":" in raw[:3]) or (not windows_root and raw.startswith("/")):
            candidate = raw
        elif windows_root:
            # "docs/x.md", "/docs/x.md" and "\\docs\\x.md" all mean a path inside the workspace folder.
            candidate = str(PureWindowsPath(self.root_host) / PureWindowsPath(raw.replace("/", "\\").lstrip("\\")))
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

    async def _code_call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """A Serena question about this workspace's code, with its path confined to the workspace and given to
        Serena relative to the workspace root."""
        if self.root_container is None:
            return {"success": False, "blocked": True,
                    "reason": "This workspace has no registered folder; register it before reading its code."}
        relative = ""
        if str(args.get("path") or "").strip():
            host, refusal = self._resolve_host(args.get("path"))
            if refusal:
                return {"success": False, "blocked": True, "reason": refusal}
            container = self._to_container(host)
            parts = container.relative_to(Path(os.path.normpath(str(self.root_container)))).parts
            relative = "/".join(parts)
        project = str(Path(os.path.normpath(str(self.root_container))))
        return await self.runtime.code_intel(name, project, {**args, "path": relative})

    async def _workspace_call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        from app.core.agents import workspace_ops

        rt = self.runtime
        if name in workspace_ops.HANDLERS:
            return await workspace_ops.HANDLERS[name](self, args)
        if name in ("generate_image", "make_voiceover", "make_video") and not str(args.get("path") or "").strip():
            from app.core.creative import images

            stem = images.default_path(str(args.get("prompt") or args.get("brief") or args.get("text") or ""))
            args = {**args, "path": {"generate_image": stem,
                                     "make_voiceover": stem.replace("assets/images/", "assets/audio/")[:-4] + ".wav",
                                     "make_video": stem.replace("assets/images/", "assets/videos/")[:-4] + ".mp4"}[name]}
        if name == "social_draft":
            media = []
            for item in args.get("media") or []:
                found, refusal = self._resolve_host(str(item))
                if refusal:
                    return {"success": False, "blocked": True, "reason": refusal}
                media.append(found)
            return await rt.social_draft(str(args.get("text", "")), list(args.get("channels") or []) or None, media)
        if name == "social_channels":
            return await rt.social_channels()
        if name in CODE_TOOLS:
            return await self._code_call(name, args)
        if name == "read_document":
            if str(args.get("path") or "").strip():
                host, refusal = self._resolve_host(args.get("path"))
                if refusal:
                    return {"success": False, "blocked": True, "reason": refusal}
                return await rt.read_document(host_path=host, offset=_offset(args.get("offset")))
            if not str(args.get("url") or "").strip():
                return {"success": False, "error": "read_document needs a path in the workspace or a url."}
            return await rt.read_document(url=str(args["url"]), offset=_offset(args.get("offset")))
        if name == "use_browser":
            return await rt.use_browser(str(args.get("action") or ""), args)
        if name in ("knowledge_graph_search", "knowledge_graph_add", "recall_richard"):
            return await rt.knowledge(name, args)
        if name == "run_prompt_checks":
            return await rt.prompt_checks(str(args.get("suite") or ""), args.get("instructions"))
        if name in _FILESYSTEM_TOOLS:
            key = "cwd" if name == "run_command" else "path"
            host, refusal = self._resolve_host(args.get(key))
            if refusal:
                return {"success": False, "blocked": True, "reason": refusal}
            if name == "list_files":
                return await rt.list_files(host)
            if name == "read_file":
                return await rt.read_file(host, offset=_offset(args.get("offset")))
            if name == "scan_workspace":
                return await rt.scan_workspace(host)
            if name == "make_voiceover":
                return await rt.make_voiceover(host, str(args.get("text", "")),
                                               licence_file=self._resolve_host("ASSET_LICENCES.md")[0],
                                               shown_as=str(args["path"]))
            if name == "make_video":
                return await rt.make_video(host, str(args.get("brief", "")), int(args.get("seconds") or 40),
                                           str(args.get("aspect") or "portrait"), str(args.get("audience") or ""),
                                           str(args.get("footage") or "auto"),
                                           licence_file=self._resolve_host("ASSET_LICENCES.md")[0],
                                           shown_as=str(args["path"]))
            if name == "generate_image":
                from app.core.creative import images

                width, height = images.size_of(args.get("shape"))
                return await rt.generate_image(host, str(args.get("prompt", "")), width, height,
                                               licence_file=self._resolve_host("ASSET_LICENCES.md")[0],
                                               shown_as=str(args["path"]))
            if name == "write_file":
                if not str(args.get("path") or "").strip():
                    return {"success": False, "error": "write_file needs the path of the file to write."}
                return await rt.write_file(host, str(args.get("content", "")), overwrite=True,
                                           append=bool(args.get("append")))
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
            return await rt.fetch_url(str(args.get("url", "")), args.get("render") if isinstance(args.get("render"),
                                                                                              bool) else None)
        if name == "read_mission_report":
            return await rt.read_mission_report(args.get("mission"))
        if name == "web_search":
            return await rt.web_search(str(args.get("query", "")), int(args.get("limit") or 8),
                                       args.get("category"), args.get("time_range"))
        if name == "research_web":
            return await rt.research_web(str(args.get("question", "")), str(args.get("depth") or "quick"),
                                         args.get("category"), args.get("time_range"))
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
            # A home directory, a shell variable or a Windows variable (%USERPROFILE%) points outside; the short
            # placeholders of a format string (git log --format=%h %s, date +%Y) do not.
            if value.startswith("~") or "$" in value or _WINDOWS_VARIABLE.search(value):
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
                secret = (lower.startswith(".env") or lower.endswith(".env") or "secret" in lower
                          or "key" in lower) and not fs_inspector.is_env_template(lower)
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
