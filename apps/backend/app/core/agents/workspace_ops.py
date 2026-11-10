"""
JAI Backend - More workspace tools for agents (Repair 12e-3a)

The design's file, command, git, memory and workspace-analysis tools that the
basic toolbox did not have: edit, create folder, move, copy, delete (approval),
metadata, build, test, install, installed-check, command log, branch, push
(approval), memory links, and project detection.

Each one runs through the agent's ``AgentToolbox``: every path is resolved
inside the mission's registered folder (anything outside is refused), the
central permission gate runs first (``ToolRuntime._enforce``), and the action
is recorded on the task, the operations feed and the audit trail. Secret files
are never opened or written, and protected locations are never touched.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9._/-]{1,100}(?<!\.lock)$")
_PACKAGE_RE = re.compile(r"^(@[a-z0-9._-]+/)?[A-Za-z0-9._-]{1,100}(==[A-Za-z0-9.*+-]+|@[A-Za-z0-9.^~*+-]+)?$")
_MAX_EDIT_BYTES = 2_000_000


def _secret_name(name: str) -> bool:
    lower = name.lower()
    return lower.startswith(".env") or lower.endswith(".env") or "secret" in lower or "id_rsa" in lower \
        or lower.endswith((".pem", ".key", ".p12", ".pfx"))


def _approved(tb, tool: str) -> bool:
    context = tb.context
    return bool(getattr(context, "approval_granted", False)) or tool in (getattr(context, "approved_tools", None) or [])


async def _resolve(tb, value: Any) -> Tuple[Optional[str], Optional[Path], Optional[Dict[str, Any]]]:
    from app.core.workspaces import fs_inspector

    host, refusal = tb._resolve_host(value)
    if refusal:
        return None, None, {"success": False, "blocked": True, "reason": refusal}
    container = tb._to_container(host)
    if fs_inspector._is_banned(host) or fs_inspector._is_banned(str(container)):
        return None, None, {"success": False, "blocked": True,
                            "reason": "Target matches a protected location (hard boundary)."}
    return host, container, None


async def _gate(tb, tool: str, host: str, *, approval: bool = False, command: Optional[str] = None,
                description: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Central permission gate; approval-gated tools pause unless this run carries approval."""
    granted = approval and _approved(tb, tool)
    return await tb.runtime._enforce(
        tool, path=host, command=command, action_description=description,
        requires_approval_flag=True if approval else None, approval_granted=granted)


# ----- files ------------------------------------------------------------------------------

async def edit_file(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    host, path, refused = await _resolve(tb, args.get("path"))
    if refused:
        return refused
    old, new = args.get("old_text"), args.get("new_text")
    if not isinstance(old, str) or not old or not isinstance(new, str):
        return {"success": False, "error": "old_text (non-empty) and new_text are required"}
    if _secret_name(path.name):
        return {"success": False, "blocked": True, "reason": "Secret-bearing files are never edited."}
    if not path.is_file():
        return {"success": False, "error": f"{args.get('path')} is not a file"}
    if path.stat().st_size > _MAX_EDIT_BYTES:
        return {"success": False, "error": "File too large to edit in place; write a new version instead."}
    content = path.read_text(encoding="utf-8", errors="strict")
    count = content.count(old)
    if count == 0:
        return {"success": False, "error": "old_text was not found; read the file and copy the exact text."}
    if count > 1 and not args.get("replace_all"):
        return {"success": False, "error": f"old_text occurs {count} times; include more surrounding text "
                                           "or set replace_all."}
    updated = content.replace(old, new) if args.get("replace_all") else content.replace(old, new, 1)
    result = await tb.runtime.write_file(host, updated, overwrite=True)
    if result.get("success"):
        result = {"success": True, "replacements": count if args.get("replace_all") else 1,
                  "bytes": len(updated.encode())}
    return result


async def create_folder(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    host, path, refused = await _resolve(tb, args.get("path"))
    if refused:
        return refused
    denied = await _gate(tb, "create_folder", host)
    if denied:
        return denied
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    await tb.runtime._record("create_folder", {"path": host}, True, "exists" if existed else "created")
    return {"success": True, "created": not existed, "path": host}


async def _transfer(tb, args: Dict[str, Any], *, move: bool) -> Dict[str, Any]:
    tool = "move_file" if move else "copy_file"
    src_host, src, refused = await _resolve(tb, args.get("source"))
    if refused:
        return refused
    dst_host, dst, refused = await _resolve(tb, args.get("destination"))
    if refused:
        return refused
    if not src.exists():
        return {"success": False, "error": f"{args.get('source')} does not exist"}
    if _secret_name(src.name) or _secret_name(dst.name):
        return {"success": False, "blocked": True, "reason": "Secret-bearing files are never moved or copied."}
    if src == Path(os.path.normpath(str(tb.root_container))):
        return {"success": False, "blocked": True, "reason": "The workspace folder itself cannot be moved."}
    if dst.exists() and not args.get("overwrite"):
        return {"success": False, "error": f"{args.get('destination')} already exists (set overwrite to replace)"}
    for host in (src_host, dst_host):
        denied = await _gate(tb, tool, host)
        if denied:
            return denied
    dst.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(src), str(dst))
    elif src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=bool(args.get("overwrite")))
    else:
        shutil.copy2(src, dst)
    await tb.runtime._record(tool, {"source": src_host, "destination": dst_host}, True,
                             f"{'moved' if move else 'copied'} to {dst_host}")
    # The artifact graph (Upgrade 3): the file at its new place, and for a move, the old place as removed.
    await tb.runtime._graph("record_file", dst_host, None, operation=tool)
    if move:
        await tb.runtime._graph("record_file", src_host, None, operation="moved_away")
    return {"success": True, "source": src_host, "destination": dst_host}


async def move_file(tb, args):
    return await _transfer(tb, args, move=True)


async def copy_file(tb, args):
    return await _transfer(tb, args, move=False)


async def delete_file_with_boundary(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    host, path, refused = await _resolve(tb, args.get("path"))
    if refused:
        return refused
    if path == Path(os.path.normpath(str(tb.root_container))):
        return {"success": False, "blocked": True, "reason": "The workspace folder itself is never deleted."}
    if not path.exists():
        return {"success": False, "error": f"{args.get('path')} does not exist"}
    tb.runtime.pending_tool_args = {"path": host, "reason": args.get("reason"), "root": tb.root_host}
    denied = await _gate(tb, "delete_file_with_boundary", host, approval=True,
                         description=f"Delete {'folder' if path.is_dir() else 'file'} {host}"
                                     + (f": {args.get('reason')}" if args.get("reason") else ""))
    if denied:
        return denied
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    await tb.runtime._record("delete_file_with_boundary", {"path": host}, True, "deleted (approved)")
    await tb.runtime._graph("record_file", host, None, operation="deleted")
    return {"success": True, "deleted": host}


async def get_file_metadata(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    host, path, refused = await _resolve(tb, args.get("path"))
    if refused:
        return refused
    denied = await _gate(tb, "get_file_metadata", host)
    if denied:
        return denied
    if not path.exists():
        return {"success": False, "error": f"{args.get('path')} does not exist"}
    info = path.stat()
    data = {"path": host, "type": "folder" if path.is_dir() else "file", "size_bytes": info.st_size,
            "modified": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
            "secret_bearing": _secret_name(path.name)}
    if path.is_dir():
        data["entries"] = sum(1 for _ in path.iterdir())
    else:
        data["extension"] = path.suffix.lstrip(".") or None
    await tb.runtime._record("get_file_metadata", {"path": host}, True, data["type"])
    return {"success": True, "data": data}


# ----- project detection ---------------------------------------------------------------------

def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def detect_project(root: Path) -> Dict[str, Any]:
    """Stack, package managers, and the real build/test/run commands, from the project's own files."""
    stack: List[str] = []
    managers: List[str] = []
    commands: Dict[str, str] = {}
    package = _read_json(root / "package.json") if (root / "package.json").is_file() else {}
    if package:
        deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        stack.append("node")
        for name, label in (("next", "nextjs"), ("react", "react"), ("vue", "vue"), ("svelte", "svelte"),
                            ("express", "express"), ("@nestjs/core", "nestjs"), ("expo", "expo"),
                            ("react-native", "react-native"), ("typescript", "typescript"),
                            ("tailwindcss", "tailwind"), ("prisma", "prisma"), ("vite", "vite")):
            if name in deps:
                stack.append(label)
        manager = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "npm"
        managers.append(manager)
        scripts = package.get("scripts", {})
        run = "npm run" if manager == "npm" else manager
        for key in ("build", "test", "lint", "dev", "start"):
            if key in scripts:
                commands[key] = f"npm test" if (key == "test" and manager == "npm") else f"{run} {key}"
        commands.setdefault("install", "npm ci" if manager == "npm" and (root / "package-lock.json").exists()
                            else f"{manager} install")
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() or (root / "requirements.txt").is_file() or (root / "setup.py").is_file():
        stack.append("python")
        text = pyproject.read_text(encoding="utf-8", errors="ignore") if pyproject.is_file() else ""
        req = (root / "requirements.txt").read_text(encoding="utf-8", errors="ignore") \
            if (root / "requirements.txt").is_file() else ""
        blob = (text + "\n" + req).lower()
        for name in ("fastapi", "django", "flask", "sqlalchemy", "celery", "pydantic"):
            if name in blob:
                stack.append(name)
        if "[tool.poetry]" in text:
            managers.append("poetry")
            commands.setdefault("install", "poetry install")
        else:
            managers.append("pip")
            if req:
                commands.setdefault("install", "pip install -r requirements.txt")
        if "pytest" in blob or (root / "tests").is_dir() or (root / "pytest.ini").exists():
            commands.setdefault("test", "python -m pytest -q")
        commands.setdefault("build", "python -m compileall -q .")
    if (root / "go.mod").is_file():
        stack.append("go")
        commands.setdefault("build", "go build ./...")
        commands.setdefault("test", "go test ./...")
    if (root / "Cargo.toml").is_file():
        stack.append("rust")
        commands.setdefault("build", "cargo build")
        commands.setdefault("test", "cargo test")
    if (root / "Makefile").is_file() and "build" not in commands:
        commands["build"] = "make"
    docker = [name for name in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml")
              if (root / name).exists()]
    if docker:
        stack.append("docker")
    if "expo" in stack or "react-native" in stack:
        kind = "mobile_app"
    elif {"nextjs", "react", "vue", "svelte", "vite"} & set(stack) and \
            {"fastapi", "django", "flask", "express", "nestjs"} & set(stack):
        kind = "full_stack_app"
    elif {"nextjs", "react", "vue", "svelte", "vite"} & set(stack):
        kind = "web_frontend"
    elif {"fastapi", "django", "flask", "express", "nestjs"} & set(stack):
        kind = "backend_service"
    elif stack:
        kind = "software_project"
    elif any(p.suffix.lower() in (".md", ".docx", ".pdf", ".txt") for p in root.iterdir() if p.is_file()):
        kind = "document_pack"
    else:
        kind = "general"
    return {"workspace_type": kind, "stack": sorted(set(stack), key=stack.index), "package_managers": managers,
            "commands": commands, "docker_files": docker, "git": (root / ".git").exists()}


_EXPECTED_FILES = {
    "README.md": "explains what the project is and how to run it",
    ".gitignore": "keeps build output and secrets out of git",
    "LICENSE": "states how others may use the code",
}


def missing_files(root: Path, detected: Dict[str, Any]) -> List[Dict[str, str]]:
    missing = [{"file": name, "why": why} for name, why in _EXPECTED_FILES.items() if not (root / name).exists()]
    if detected["stack"] and not any((root / n).exists() for n in (".env.example", ".env.sample", "env.example")) \
            and any((root / n).exists() for n in (".env", ".env.local")):
        missing.append({"file": ".env.example", "why": "documents the settings the app needs without the values"})
    if detected["stack"] and "test" not in detected["commands"]:
        missing.append({"file": "tests", "why": "no test command or test folder was found"})
    if detected["docker_files"] == [] and detected["workspace_type"] in ("backend_service", "full_stack_app"):
        missing.append({"file": "Dockerfile", "why": "needed to deploy the service with JAI's deploy tools"})
    return missing


async def _project_report(tb, args: Dict[str, Any], tool: str) -> Dict[str, Any]:
    host, path, refused = await _resolve(tb, args.get("path"))
    if refused:
        return refused
    denied = await _gate(tb, tool, host)
    if denied:
        return denied
    if not path.is_dir():
        return {"success": False, "error": f"{args.get('path') or 'the workspace'} is not a folder"}
    detected = detect_project(path)
    data: Dict[str, Any]
    if tool == "detect_workspace_type":
        data = {"workspace_type": detected["workspace_type"], "stack": detected["stack"]}
    elif tool == "detect_stack":
        data = {k: detected[k] for k in ("stack", "package_managers", "docker_files", "git")}
    elif tool == "detect_commands":
        data = {"commands": detected["commands"], "package_managers": detected["package_managers"]}
    else:
        data = {"missing": missing_files(path, detected), "workspace_type": detected["workspace_type"]}
    await tb.runtime._record(tool, {"path": host}, True, json.dumps(data)[:300])
    return {"success": True, "data": data}


async def detect_workspace_type(tb, args):
    return await _project_report(tb, args, "detect_workspace_type")


async def detect_stack(tb, args):
    return await _project_report(tb, args, "detect_stack")


async def detect_commands(tb, args):
    return await _project_report(tb, args, "detect_commands")


async def find_missing_files(tb, args):
    return await _project_report(tb, args, "find_missing_files")


# ----- commands ---------------------------------------------------------------------------

async def _project_command(tb, args: Dict[str, Any], kind: str) -> Dict[str, Any]:
    host, path, refused = await _resolve(tb, args.get("path"))
    if refused:
        return refused
    command = (args.get("command") or "").strip() or detect_project(path).get("commands", {}).get(kind)
    if not command:
        return {"success": False, "error": f"No {kind} command found in the project; pass one explicitly."}
    refusal = tb._command_refusal(command)
    if refusal:
        await tb.runtime._record("run_command", {"command": command}, False, refusal)
        return {"success": False, "blocked": True, "reason": refusal}
    result = await tb.runtime.run_command(command, cwd_host=host, allow_build=True,
                                          timeout=int(args.get("timeout") or 900))
    result["command"] = command
    return result


async def run_build(tb, args):
    return await _project_command(tb, args, "build")


async def run_tests(tb, args):
    return await _project_command(tb, args, "test")


async def install_package(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    name = str(args.get("name") or "").strip()
    if not _PACKAGE_RE.match(name):
        return {"success": False, "error": "Give one package name, optionally with a version (react@18, requests==2.32)."}
    host, path, refused = await _resolve(tb, args.get("path"))
    if refused:
        return refused
    detected = detect_project(path)
    ecosystem = (args.get("ecosystem") or ("npm" if "node" in detected["stack"] else "pypi")).lower()
    if ecosystem == "npm":
        manager = (detected["package_managers"] or ["npm"])[0]
        verb = {"npm": "npm install", "pnpm": "pnpm add", "yarn": "yarn add"}.get(manager, "npm install")
        command = f"{verb} {name}" + (" --save-dev" if args.get("dev") and manager == "npm" else "")
    elif ecosystem == "pypi":
        command = f"poetry add {name}" if "poetry" in detected["package_managers"] else f"pip install {name}"
    else:
        return {"success": False, "error": "ecosystem must be npm or pypi"}
    result = await tb.runtime.run_command(command, cwd_host=host, allow_build=True, allow_install=True, timeout=900)
    result["command"] = command
    return result


async def check_installed(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    name = str(args.get("name") or "").strip()
    host, path, refused = await _resolve(tb, args.get("path"))
    if refused:
        return refused
    denied = await _gate(tb, "check_installed", host)
    if denied:
        return denied
    found: Dict[str, Any] = {"name": name, "declared": None, "installed": None}
    package = _read_json(path / "package.json") if (path / "package.json").is_file() else {}
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        if name in package.get(section, {}):
            found["declared"] = {"manifest": "package.json", "section": section, "range": package[section][name]}
    installed = _read_json(path / "node_modules" / name / "package.json")
    if installed:
        found["installed"] = {"version": installed.get("version"), "where": "node_modules"}
    pattern = re.compile(rf"^\s*\"?{re.escape(name)}\"?\s*([=<>~^!].*)?$", re.I | re.M)
    for manifest in ("requirements.txt", "pyproject.toml"):
        file = path / manifest
        if file.is_file() and found["declared"] is None:
            match = pattern.search(file.read_text(encoding="utf-8", errors="ignore"))
            if match:
                found["declared"] = {"manifest": manifest, "spec": (match.group(1) or "").strip() or "any"}
    await tb.runtime._record("check_installed", {"name": name}, True,
                             f"declared={bool(found['declared'])} installed={bool(found['installed'])}")
    return {"success": True, "data": found}


async def get_command_log(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    from sqlalchemy import select

    from app.core.jarv_memory import memory_service
    from app.models.execution import CommandRun

    denied = await tb.runtime._enforce("get_command_log")
    if denied:
        return denied
    agent_id = await memory_service._agent_id(tb.context.db_session, tb.context.workspace_id)
    limit = max(1, min(int(args.get("limit") or 20), 100))
    rows = (await tb.context.db_session.execute(
        select(CommandRun).where(CommandRun.agent_id == agent_id)
        .order_by(CommandRun.started_at.desc()).limit(limit))).scalars().all()
    entries = [{"command": r.command, "exit_code": r.exit_code, "success": r.success,
                "at": r.started_at.isoformat() if r.started_at else None,
                "stdout_tail": (r.stdout or "")[-500:], "stderr_tail": (r.stderr or "")[-500:]} for r in rows]
    await tb.runtime._record("get_command_log", {"limit": limit}, True, f"{len(entries)} commands")
    return {"success": True, "commands": entries}


# ----- git ----------------------------------------------------------------------------------

async def _git(cwd: Path, *argv: str, timeout: int = 120) -> Tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", "-c", f"safe.directory={cwd}", *argv, cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", f"git {argv[0]} timed out"
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def git_create_branch(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    name = str(args.get("name") or "").strip()
    if not _BRANCH_RE.match(name):
        return {"success": False, "error": "Invalid branch name."}
    host, path, refused = await _resolve(tb, args.get("path"))
    if refused:
        return refused
    denied = await _gate(tb, "git_create_branch", host)
    if denied:
        return denied
    argv = ["switch", "-c", name] if args.get("switch", True) else ["branch", name]
    code, out, err = await _git(path, *argv)
    await tb.runtime._record("git_create_branch", {"name": name}, code == 0, (out or err).strip()[:300])
    return {"success": code == 0, "branch": name, "output": (out or err).strip()[:2000]}


async def git_push_with_boundary(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    remote = str(args.get("remote") or "origin").strip()
    host, path, refused = await _resolve(tb, args.get("path"))
    if refused:
        return refused
    if not re.match(r"^[A-Za-z0-9._-]{1,50}$", remote):
        return {"success": False, "error": "Invalid remote name."}
    code, branch, _ = await _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    branch = str(args.get("branch") or branch.strip())
    if not _BRANCH_RE.match(branch):
        return {"success": False, "error": "Invalid branch name."}
    # No shell command is run (git is called with an argument list), so the gate is
    # the tool's own approval policy rather than the shell command classifier.
    tb.runtime.pending_tool_args = {"path": host, "remote": remote, "branch": branch, "root": tb.root_host}
    denied = await _gate(tb, "git_push_with_boundary", host, approval=True,
                         description=f"Push branch {branch} to {remote} from {host}")
    if denied:
        return denied
    code, out, err = await _git(path, "push", remote, branch, timeout=300)
    await tb.runtime._record("git_push_with_boundary", {"remote": remote, "branch": branch}, code == 0,
                             (err or out).strip()[:300])
    return {"success": code == 0, "remote": remote, "branch": branch, "output": (err or out).strip()[:2000]}


# ----- memory links ------------------------------------------------------------------------

async def memory_link_to_workspace(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    from uuid import UUID

    from app.core.jarv_memory import memory_service

    denied = await tb.runtime._enforce("memory_link_to_workspace")
    if denied:
        return denied
    try:
        memory_id = UUID(str(args.get("memory_id")))
    except ValueError:
        return {"success": False, "error": "memory_id must be a memory's id"}
    record = await memory_service.link_to_workspace(tb.context.db_session, memory_id, tb.context.workspace_id)
    ok = record is not None and record.workspace_id == tb.context.workspace_id
    await tb.runtime._record("memory_link_to_workspace", {"memory_id": str(memory_id)}, ok,
                             "linked" if ok else "not linked (unknown or belongs to another workspace)")
    return {"success": ok, "memory_id": str(memory_id)}


async def memory_link_to_task(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    from uuid import UUID

    from app.core.jarv_memory import memory_service

    denied = await tb.runtime._enforce("memory_link_to_task")
    if denied:
        return denied
    try:
        memory_id = UUID(str(args.get("memory_id")))
        task_id = UUID(str(args.get("task_id") or tb.context.task_id))
    except ValueError:
        return {"success": False, "error": "memory_id and task_id must be ids"}
    record = await memory_service.link_to_task(tb.context.db_session, memory_id, tb.context.workspace_id, task_id)
    ok = record is not None
    await tb.runtime._record("memory_link_to_task", {"memory_id": str(memory_id), "task_id": str(task_id)}, ok,
                             "linked" if ok else "not linked (memory or task not in this workspace)")
    return {"success": ok, "memory_id": str(memory_id), "task_id": str(task_id)}


# ----- spreadsheets -----------------------------------------------------------------------------------------------

_SHEET_NAME_BAD = re.compile(r"[\[\]:*?/\\]")
_CELL_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
MAX_SHEET_ROWS = 5000


def _column(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _xml(text: Any) -> str:
    value = _CELL_BAD.sub("", "" if text is None else str(text))
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def xlsx_bytes(sheets: List[Dict[str, Any]]) -> bytes:
    """A real .xlsx workbook (Office Open XML) from [{"name", "rows": [[cell, ...], ...]}]: the first row bold as
    the header, numbers kept as numbers, everything else as text. Standard library only."""
    import io
    import zipfile

    names: List[str] = []
    bodies: List[str] = []
    for number, sheet in enumerate(sheets, start=1):
        name = _SHEET_NAME_BAD.sub(" ", str(sheet.get("name") or f"Sheet{number}")).strip()[:31] or f"Sheet{number}"
        while name in names:
            name = f"{name[:28]} {number}"
        names.append(name)
        rows_xml = []
        for r, row in enumerate(list(sheet.get("rows") or [])[:MAX_SHEET_ROWS], start=1):
            cells = []
            for c, value in enumerate(row if isinstance(row, (list, tuple)) else [row]):
                ref = f"{_column(c)}{r}"
                style = ' s="1"' if r == 1 else ""
                if isinstance(value, bool) or value is None or not isinstance(value, (int, float)):
                    cells.append(f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{_xml(value)}'
                                 f'</t></is></c>')
                else:
                    cells.append(f'<c r="{ref}"{style}><v>{value}</v></c>')
            rows_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
        bodies.append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                      '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                      '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane='
                      '"bottomLeft" state="frozen"/></sheetView></sheetViews>'
                      f'<sheetData>{"".join(rows_xml)}</sheetData></worksheet>')
    ns = "http://schemas.openxmlformats.org"
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Types xmlns="{ns}/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.styles+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.'
                      f'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(names) + 1))
            + "</Types>"),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{ns}/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{ns}/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>'),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{ns}/spreadsheetml/2006/main" xmlns:r="{ns}/officeDocument/2006/relationships">'
            "<sheets>" + "".join(f'<sheet name="{_xml(n)}" sheetId="{i}" r:id="rId{i}"/>'
                                 for i, n in enumerate(names, start=1)) + "</sheets></workbook>"),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{ns}/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="{ns}/officeDocument/2006/relationships/worksheet" '
                      f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1))
            + f'<Relationship Id="rId{len(names) + 1}" Type="{ns}/officeDocument/2006/relationships/styles" '
              'Target="styles.xml"/></Relationships>'),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<styleSheet xmlns="{ns}/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            "</styleSheet>"),
    }
    for i, body in enumerate(bodies, start=1):
        files[f"xl/worksheets/sheet{i}.xml"] = body
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _cell_ref_column(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    number = 0
    for ch in letters.upper():
        number = number * 26 + (ord(ch) - 64)
    return max(0, number - 1)


def xlsx_read(data: bytes) -> List[Dict[str, Any]]:
    """The sheets of an .xlsx workbook as [{"name", "rows"}], every cell as text (numbers kept as numbers): the
    workbooks JAI writes and the ones written with openpyxl or Excel (shared strings). Standard library only."""
    import io
    import xml.etree.ElementTree as ET
    import zipfile

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    archive = zipfile.ZipFile(io.BytesIO(data))
    names = set(archive.namelist())
    shared: List[str] = []
    if "xl/sharedStrings.xml" in names:
        for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in item.iter(f"{{{ns['m']}}}t")))
    targets = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels")).findall("p:Relationship", ns):
            target = rel.get("Target", "").lstrip("/")
            targets[rel.get("Id")] = target if target.startswith("xl/") else f"xl/{target}"
    sheets = []
    for sheet in ET.fromstring(archive.read("xl/workbook.xml")).findall("m:sheets/m:sheet", ns):
        part = targets.get(sheet.get(f"{{{ns['r']}}}id"), "")
        if part not in names:
            continue
        rows: List[List[Any]] = []
        for row in ET.fromstring(archive.read(part)).iter(f"{{{ns['m']}}}row"):
            values: Dict[int, Any] = {}
            for cell in row.findall("m:c", ns):
                kind, column = cell.get("t"), _cell_ref_column(cell.get("r") or "A")
                if kind == "inlineStr":
                    value: Any = "".join(t.text or "" for t in cell.iter(f"{{{ns['m']}}}t"))
                else:
                    raw = cell.findtext("m:v", default="", namespaces=ns)
                    if kind == "s":
                        value = shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else ""
                    elif kind in ("str", "b", "e"):
                        value = raw
                    else:
                        try:
                            value = int(raw) if raw.lstrip("-").isdigit() else float(raw) if raw else ""
                        except ValueError:
                            value = raw
                values[column] = value
            if values:
                rows.append([values.get(i, "") for i in range(max(values) + 1)])
        sheets.append({"name": sheet.get("name") or f"Sheet{len(sheets) + 1}", "rows": rows})
    return sheets


def xlsx_text(data: bytes, limit: int = 60000) -> str:
    """A workbook as text an agent or the Verifier can read: each sheet with its row count, then its rows."""
    parts = []
    for sheet in xlsx_read(data):
        rows = sheet["rows"]
        parts.append(f"## Sheet: {sheet['name']} ({max(0, len(rows) - 1)} rows under the header)")
        parts += [" | ".join(str(v) for v in row) for row in rows]
    return "\n".join(parts)[:limit]


def _same_header(a: List[Any], b: List[Any]) -> bool:
    return [str(x).strip().lower() for x in a] == [str(x).strip().lower() for x in b]


async def write_spreadsheet(tb, args: Dict[str, Any]) -> Dict[str, Any]:
    """An .xlsx workbook in the workspace, one sheet per list (agents doing research, sales and marketing work keep
    their deliverables as spreadsheets Richard opens in Excel). Gated and recorded as a file write.

    An existing workbook is updated, never wiped (10 November: a save that named one sheet replaced the whole
    workbook and lost two sheets of an earlier mission's work): sheets the call does not name are kept, a named
    sheet is replaced, or with mode "append" gets the new rows added under its own (a repeated header row is
    skipped). The previous copy is kept in .jai/backups/ first."""
    host, path, refused = await _resolve(tb, args.get("path"))
    if refused:
        return refused
    if path.suffix.lower() != ".xlsx":
        return {"success": False, "error": "write_spreadsheet writes .xlsx files; give a path ending in .xlsx."}
    if _secret_name(path.name):
        return {"success": False, "blocked": True, "reason": "Secret-bearing files are never written."}
    sheets = args.get("sheets")
    if isinstance(sheets, str):
        try:
            sheets = json.loads(sheets)
        except ValueError:
            sheets = None
    if not isinstance(sheets, list) or not sheets or not all(isinstance(s, dict) for s in sheets):
        return {"success": False, "error": 'sheets must be a list like [{"name": "Creators", "rows": '
                                           '[["Name", "Link"], ["...", "..."]]}].'}
    append = str(args.get("mode") or "").lower() == "append"
    denied = await _gate(tb, "write_file", host, description=f"Write spreadsheet {host}")
    if denied:
        return denied
    existed = path.exists()
    before: List[Dict[str, Any]] = []
    if existed:
        old = path.read_bytes()
        try:
            before = xlsx_read(old)
        except Exception:  # noqa: BLE001 - never overwrite what cannot be read back
            return {"success": False, "error": f"{host} exists but could not be read as a workbook, so it was not "
                                               "changed. Write to a new file name instead."}
        backups = path.parent
        for _ in range(8):  # the workspace root holds .jai/
            if (backups / ".jai").is_dir() or (backups / ".git").exists():
                break
            backups = backups.parent
        folder = backups / ".jai" / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone

        (folder / f"{path.stem}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.xlsx").write_bytes(old)
        for stale in sorted(folder.glob(f"{path.stem}-*.xlsx"))[:-10]:
            stale.unlink(missing_ok=True)
    merged = [{"name": s["name"], "rows": list(s["rows"])} for s in before]
    by_name = {s["name"].strip().lower(): s for s in merged}
    added: Dict[str, int] = {}
    for given in sheets:
        name = str(given.get("name") or f"Sheet{len(merged) + 1}")
        rows = [r if isinstance(r, (list, tuple)) else [r] for r in (given.get("rows") or [])]
        current = by_name.get(name.strip().lower())
        if current is None:
            current = {"name": name, "rows": []}
            merged.append(current)
            by_name[name.strip().lower()] = current
        if append and current["rows"]:
            if rows and _same_header(rows[0], current["rows"][0]):
                rows = rows[1:]
            current["rows"].extend(list(r) for r in rows)
            added[name] = len(rows)
        else:
            current["rows"] = [list(r) for r in rows]
            added[name] = max(0, len(rows) - 1)
    data = xlsx_bytes(merged)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    counts = {s["name"]: max(0, len(s["rows"]) - 1) for s in merged}
    kept = [s["name"] for s in before if s["name"] not in added]
    await tb.runtime._record("write_file", {"path": host}, True,
                             f"spreadsheet {'updated' if existed else 'created'}: "
                             + ", ".join(f"{n} {c} rows" for n, c in counts.items())
                             + (f"; kept unchanged: {', '.join(kept)}" if kept else ""))
    await tb.runtime._graph("record_file", host, None, operation="modified" if existed else "created")
    return {"success": True, "path": host, "rows_per_sheet": counts, "written": added, "kept_unchanged": kept,
            "bytes": len(data)}


HANDLERS = {
    "write_spreadsheet": write_spreadsheet,
    "edit_file": edit_file, "create_folder": create_folder, "move_file": move_file, "copy_file": copy_file,
    "delete_file_with_boundary": delete_file_with_boundary, "get_file_metadata": get_file_metadata,
    "detect_workspace_type": detect_workspace_type, "detect_stack": detect_stack,
    "detect_commands": detect_commands, "find_missing_files": find_missing_files,
    "run_build": run_build, "run_tests": run_tests, "install_package": install_package,
    "check_installed": check_installed, "get_command_log": get_command_log,
    "git_create_branch": git_create_branch, "git_push_with_boundary": git_push_with_boundary,
    "memory_link_to_workspace": memory_link_to_workspace, "memory_link_to_task": memory_link_to_task,
}
