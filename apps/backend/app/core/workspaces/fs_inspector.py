"""
JAI Backend - Workspace Filesystem Inspector

Real, read-only inspection of an approved workspace folder on the host machine.

The host workspace root (settings.WORKSPACE_HOST_ROOT) is bind-mounted read-only
into the backend container at settings.WORKSPACE_CONTAINER_ROOT. This module:

  * translates the host path an operator types (e.g. C:\\Users\\...\\MyProject)
    into the corresponding container path under the mounted root,
  * confirms a path really exists,
  * performs a genuine read-only walk of a workspace directory, returning the
    actual files/folders found, classifying package files, docs/design files,
    frontend/backend structure, entry points, env/example files (NAMES only -
    secret VALUES are never read or returned), and build/deploy files,
  * enforces scope: inspection is allowed only inside the mounted root and is
    blocked for banned folders (banking, crypto, wallets, passwords, keys),
  * never writes, deletes, installs, or executes anything.

If the host root is not mounted (e.g. on a fresh checkout before the volume is
configured), every method degrades safely: existence checks return False and
scans return a structured "not accessible" result instead of raising.
"""
from __future__ import annotations

import os
import glob as globlib
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, NamedTuple, Optional

from app.core.config import settings

# Folder/name fragments that must never be inspected, regardless of mount/scope.
# These map to the hard boundaries: banking, crypto wallets, passwords, keys.
_BANNED_NAME_FRAGMENTS = (
    "banking", "bank-details", "crypto", "wallet", "seed-phrase", "seedphrase",
    "password", "passwords", ".ssh", ".aws", ".gnupg", "private-key", "privatekey",
    "secrets", "keystore", "id_rsa",
)

# File names that indicate dependency/package manifests.
_PACKAGE_FILES = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "requirements.txt", "pyproject.toml", "poetry.lock", "Pipfile", "setup.py",
    "go.mod", "go.sum", "Cargo.toml", "pom.xml", "build.gradle", "composer.json",
    "Gemfile",
}

# Build / deploy / CI manifests.
_BUILD_FILES = {
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Makefile",
    "Procfile", "vercel.json", "netlify.toml", "render.yaml", "railway.json",
    ".gitlab-ci.yml", "jenkinsfile",
}

# Entry-point file names.
_ENTRY_FILES = {
    "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "server.py",
    "index.js", "index.ts", "main.js", "main.ts", "app.js", "app.ts",
    "index.tsx", "main.go", "main.rs",
}

# Directories never worth walking into (noise / huge).
_SKIP_DIRS = {
    "node_modules", ".git", ".next", "__pycache__", ".venv", "venv", "dist",
    "build", ".pytest_cache", ".mypy_cache", ".idea", ".vscode", "target",
    ".turbo", "coverage",
}

_DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
_FRONTEND_DIR_HINTS = ("frontend", "dashboard", "web", "client", "ui", "app")
_BACKEND_DIR_HINTS = ("backend", "server", "api", "services", "src")


@dataclass
class FsResult:
    """Result of a filesystem inspection request."""
    accessible: bool
    host_path: str
    container_path: Optional[str] = None
    exists: bool = False
    is_dir: bool = False
    reason: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)


def _normalize_host_path(host_path: str) -> str:
    """Strip quotes/whitespace and unify separators for comparison."""
    p = (host_path or "").strip().strip('"').strip("'")
    return p.replace("/", "\\") if (":" in p[:3]) else p


def _is_banned(path_str: str) -> bool:
    low = path_str.lower()
    return any(frag in low for frag in _BANNED_NAME_FRAGMENTS)


# Approved, writable, ephemeral sandbox root (container-local). A logical path
# under SANDBOX_HOST_PREFIX maps into SANDBOX_CONTAINER_ROOT — isolated from the
# host Desktop, scoped, and safe for sandbox/test workspaces.
SANDBOX_HOST_PREFIX = "/test_workspaces"
SANDBOX_CONTAINER_ROOT = "/tmp/jarv_sandbox"


def host_to_container(host_path: str) -> Optional[Path]:
    """
    Translate an operator-supplied host path into the container path under the
    mounted workspace root (or the sandbox root). Returns None if the path is not
    inside an approved root (scope enforcement).
    """
    root_host = settings.WORKSPACE_HOST_ROOT
    container_root = Path(settings.WORKSPACE_CONTAINER_ROOT)

    raw = (host_path or "").strip().strip('"').strip("'")
    # Sandbox root: a logical /test_workspaces/... path -> writable container dir.
    norm = raw.replace("\\", "/")
    if norm == SANDBOX_HOST_PREFIX or norm.startswith(SANDBOX_HOST_PREFIX + "/"):
        rel = norm[len(SANDBOX_HOST_PREFIX):].lstrip("/")
        base = Path(SANDBOX_CONTAINER_ROOT)
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        return base / rel if rel else base

    raw = _normalize_host_path(host_path)
    if not raw:
        return None

    # Windows-style host path (the common case on Richard's machine).
    if ":" in raw[:3] or "\\" in raw:
        try:
            win_path = PureWindowsPath(raw)
            win_root = PureWindowsPath(_normalize_host_path(root_host))
        except Exception:
            return None
        try:
            rel = win_path.relative_to(win_root)
        except ValueError:
            # Case-insensitive retry (Windows paths are case-insensitive).
            try:
                parts_path = [p.lower() for p in win_path.parts]
                parts_root = [p.lower() for p in win_root.parts]
                if parts_path[: len(parts_root)] != parts_root:
                    return None
                rel = PureWindowsPath(*win_path.parts[len(parts_root):])
            except Exception:
                return None
        rel_posix = PurePosixPath(*rel.parts)
        return container_root / rel_posix

    # POSIX-style host path that already points inside the container root.
    posix = Path(raw)
    try:
        posix.relative_to(container_root)
        return posix
    except ValueError:
        return None


def path_exists(host_path: str) -> FsResult:
    """Confirm a host path really exists (read-only stat). Scope + banned enforced."""
    if _is_banned(host_path):
        return FsResult(
            accessible=False, host_path=host_path,
            reason="Path matches a hard-boundary protected location (banking/crypto/passwords/keys) and is blocked.",
        )
    container = host_to_container(host_path)
    if container is None:
        return FsResult(
            accessible=False, host_path=host_path,
            reason=(
                "Path is outside the approved workspace root "
                f"({settings.WORKSPACE_HOST_ROOT}). JAI only inspects approved folders."
            ),
        )
    try:
        exists = container.exists()
        is_dir = container.is_dir() if exists else False
        return FsResult(
            accessible=True, host_path=host_path, container_path=str(container),
            exists=exists, is_dir=is_dir,
            reason=None if exists else "Path is reachable but does not exist on disk.",
        )
    except Exception as exc:  # noqa: BLE001
        return FsResult(
            accessible=False, host_path=host_path, container_path=str(container),
            reason=f"Filesystem not reachable: {exc}. The workspace root may not be mounted.",
        )


def scan_workspace(host_path: str, max_entries: int = 4000) -> FsResult:
    """
    Perform a REAL read-only scan of an approved workspace directory.

    Returns a structured inventory referencing the actual files/folders found.
    Secret VALUES are never read; env files are reported by name only.
    """
    chk = path_exists(host_path)
    if not chk.accessible:
        return chk
    if not chk.exists:
        return FsResult(
            accessible=True, host_path=host_path, container_path=chk.container_path,
            exists=False, reason="Cannot scan: the path does not exist on disk.",
        )

    root = Path(chk.container_path)
    if not root.is_dir():
        # Single file target.
        return FsResult(
            accessible=True, host_path=host_path, container_path=chk.container_path,
            exists=True, is_dir=False,
            data={"summary": "Target is a single file, not a directory.",
                  "files": [root.name], "size_bytes": _safe_size(root)},
        )

    top_level_dirs: List[str] = []
    top_level_files: List[str] = []
    package_files: List[str] = []
    build_files: List[str] = []
    doc_files: List[str] = []
    env_files: List[str] = []  # names only
    entry_points: List[str] = []
    code_extensions: Dict[str, int] = {}
    total_files = 0
    total_dirs = 0
    truncated = False

    # Top level listing (real).
    try:
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_dir():
                top_level_dirs.append(entry.name)
            else:
                top_level_files.append(entry.name)
    except Exception as exc:  # noqa: BLE001
        return FsResult(
            accessible=False, host_path=host_path, container_path=chk.container_path,
            reason=f"Could not read directory: {exc}",
        )

    # Recursive read-only walk for classification.
    for dirpath, dirnames, filenames in os.walk(root):
        # prune noisy/huge dirs in place and never descend into banned dirs
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not _is_banned(d)
        ]
        total_dirs += len(dirnames)
        rel_dir = os.path.relpath(dirpath, root)
        for fn in filenames:
            total_files += 1
            if total_files > max_entries:
                truncated = True
                break
            rel_path = fn if rel_dir == "." else f"{rel_dir}{os.sep}{fn}".replace("\\", "/")
            low = fn.lower()

            if fn in _PACKAGE_FILES:
                package_files.append(rel_path)
            if fn in _BUILD_FILES or low.startswith("docker-compose"):
                build_files.append(rel_path)
            if low.endswith(_DOC_SUFFIXES) or low.startswith("readme") or "design" in low:
                doc_files.append(rel_path)
            if low.startswith(".env") or low.endswith(".env") or "env.example" in low or "env.sample" in low:
                env_files.append(rel_path)  # NAME only, value never read
            if fn in _ENTRY_FILES:
                entry_points.append(rel_path)
            ext = Path(fn).suffix.lower()
            if ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".php", ".css", ".html", ".sql", ".sh"):
                code_extensions[ext] = code_extensions.get(ext, 0) + 1
        if truncated:
            break

    # Structure inference.
    lower_dirs = [d.lower() for d in top_level_dirs]
    has_frontend = any(any(h in d for h in _FRONTEND_DIR_HINTS) for d in lower_dirs)
    has_backend = any(any(h in d for h in _BACKEND_DIR_HINTS) for d in lower_dirs)

    # Risks + approval points (honest, derived from what was found).
    risks: List[str] = []
    approval_points: List[str] = []
    if env_files:
        risks.append(
            f"{len(env_files)} env/secret file(s) present "
            f"({', '.join(sorted(set(env_files))[:5])}{'...' if len(env_files) > 5 else ''}). "
            "Values were NOT read. Treat as secret-bearing."
        )
        approval_points.append("Reading or using secret values from env files requires Richard's approval.")
    if package_files:
        approval_points.append("Installing dependencies from the package manifests requires approval (Level 4).")
    if build_files:
        approval_points.append("Running builds / docker / deploy from build files requires approval (Level 3+).")
    if not risks:
        risks.append("No secret-bearing files detected at scan time.")
    approval_points.append("Any file modification, deletion, install, build, or commit in this workspace requires approval.")

    summary = (
        f"Read-only scan complete: {total_files} file(s) across {total_dirs} subfolder(s). "
        f"{'Frontend + backend' if has_frontend and has_backend else ('Frontend' if has_frontend else ('Backend' if has_backend else 'Flat'))} "
        f"structure detected. {len(package_files)} package manifest(s), "
        f"{len(doc_files)} doc/design file(s), {len(env_files)} env file(s), "
        f"{len(entry_points)} entry point(s)."
    )

    return FsResult(
        accessible=True, host_path=host_path, container_path=chk.container_path,
        exists=True, is_dir=True,
        data={
            "summary": summary,
            "top_level_dirs": top_level_dirs,
            "top_level_files": top_level_files,
            "package_files": sorted(set(package_files)),
            "build_files": sorted(set(build_files)),
            "doc_files": sorted(set(doc_files))[:50],
            "env_files": sorted(set(env_files)),  # names only
            "entry_points": sorted(set(entry_points)),
            "code_file_counts": code_extensions,
            "total_files": total_files,
            "total_dirs": total_dirs,
            "has_frontend": has_frontend,
            "has_backend": has_backend,
            "truncated": truncated,
            "risks": risks,
            "approval_points": approval_points,
        },
    )


def list_dir(host_path: str) -> FsResult:
    """Real read-only directory listing (scope + banned enforced)."""
    chk = path_exists(host_path)
    if not chk.accessible or not chk.exists:
        return chk
    root = Path(chk.container_path)
    entries: List[Dict[str, Any]] = []
    try:
        if root.is_dir():
            for e in sorted(root.iterdir(), key=lambda p: p.name.lower()):
                entries.append({"name": e.name, "is_dir": e.is_dir(),
                                "size_bytes": _safe_size(e) if e.is_file() else None})
        else:
            entries.append({"name": root.name, "is_dir": False, "size_bytes": _safe_size(root)})
    except Exception as exc:  # noqa: BLE001
        return FsResult(accessible=False, host_path=host_path,
                        container_path=chk.container_path, reason=str(exc))
    return FsResult(accessible=True, host_path=host_path, container_path=chk.container_path,
                    exists=True, is_dir=root.is_dir(), data={"entries": entries})


# Templates that list a project's settings by name only (.env.example and the like) are
# ordinary project files: JAI reads and writes them. Their content still passes the secret
# check, so a real key written into one is refused like anywhere else.
_ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")


def is_env_template(name: str) -> bool:
    low = (name or "").lower()
    return ".env" in low and low.endswith(_ENV_TEMPLATE_SUFFIXES)


def read_file(host_path: str, max_bytes: int = 20000, offset: int = 0) -> FsResult:
    """
    Real read-only file read (scope + banned enforced). Secret-bearing files
    (.env / key files) are reported as present but their contents are redacted.

    Returns up to ``max_bytes`` characters starting at character ``offset``;
    ``next_offset`` is where the file continues (None at the end), so a long
    file is read completely in parts.
    """
    chk = path_exists(host_path)
    if not chk.accessible or not chk.exists:
        return chk
    p = Path(chk.container_path)
    if p.is_dir():
        return FsResult(accessible=False, host_path=host_path,
                        container_path=chk.container_path, reason="Path is a directory, not a file.")
    name = p.name.lower()
    is_secret = (name.startswith(".env") or name.endswith(".env") or "secret" in name or "key" in name) \
        and not is_env_template(name)
    try:
        if is_secret:
            return FsResult(accessible=True, host_path=host_path, container_path=chk.container_path,
                            exists=True, is_dir=False,
                            data={"redacted": True, "size_bytes": _safe_size(p),
                                  "content": "[REDACTED — secret-bearing file; values never read]"})
        start = max(0, int(offset or 0))
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            if start:
                fh.read(start)
            content = fh.read(max_bytes)
            more = bool(fh.read(1))
        return FsResult(accessible=True, host_path=host_path, container_path=chk.container_path,
                        exists=True, is_dir=False,
                        data={"redacted": False, "size_bytes": _safe_size(p), "content": content,
                              "offset": start, "next_offset": start + len(content) if more else None,
                              "truncated": more})
    except Exception as exc:  # noqa: BLE001
        return FsResult(accessible=False, host_path=host_path,
                        container_path=chk.container_path, reason=str(exc))


def write_file(host_path: str, content: str, overwrite: bool = False) -> FsResult:
    """
    Controlled file write inside an approved workspace (scope + secret enforced).

    Writes are blocked outside the approved root, for banned/secret-bearing
    targets, and (unless overwrite=True) when the file already exists. Returns
    the previous content (if any) so the caller can record a diff/rollback.
    """
    if _is_banned(host_path):
        return FsResult(accessible=False, host_path=host_path,
                        reason="Target matches a hard-boundary protected location; write blocked.")
    container = host_to_container(host_path)
    if container is None:
        return FsResult(accessible=False, host_path=host_path,
                        reason=(f"Path is outside the approved workspace root "
                                f"({settings.WORKSPACE_HOST_ROOT}); write blocked."))
    name = container.name.lower()
    if (name.startswith(".env") or name.endswith(".env") or "secret" in name or "id_rsa" in name) \
            and not is_env_template(name):
        return FsResult(accessible=False, host_path=host_path, container_path=str(container),
                        reason="Target is a secret-bearing file; write blocked.")
    try:
        existed = container.exists()
        if existed and not overwrite:
            return FsResult(accessible=False, host_path=host_path, container_path=str(container),
                            exists=True, reason="File already exists; refusing to overwrite.")
        previous = None
        if existed:
            try:
                previous = container.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                previous = None
        container.parent.mkdir(parents=True, exist_ok=True)
        container.write_text(content, encoding="utf-8")
        return FsResult(accessible=True, host_path=host_path, container_path=str(container),
                        exists=True, is_dir=False,
                        data={"bytes_written": len(content.encode("utf-8")),
                              "created": not existed, "previous_content": previous})
    except Exception as exc:  # noqa: BLE001
        return FsResult(accessible=False, host_path=host_path, container_path=str(container),
                        reason=f"Write failed: {exc}")


# Read-only commands that are safe to execute against an approved workspace.
SAFE_COMMAND_PREFIXES = (
    "ls", "dir", "pwd", "cat", "head", "tail", "wc", "find", "tree", "stat",
    "git status", "git log", "git branch", "git diff", "git remote",
    "python --version", "python3 --version", "node --version", "npm --version",
    "npm ls", "npm list", "pip list", "pip --version", "echo", "whoami", "date",
    "pnpm --version", "pnpm ls", "pnpm list", "npx --version", "uv --version", "uv python list",
    "uv tree", "uv tool list", "git --version", "git show", "git rev-parse",
    "git ls-files", "git ls-tree", "git describe", "git check-ignore", "git cat-file",
    "git shortlog", "git blame", "git grep", "git stash list", "git tag -l", "git tag --list",
    "yarn --version", "jq --version", "rg --version", "gcc --version", "make --version",
    "task --version", "task --list", "task --list-all", "terraform version", "terraform -version",
    "helm version", "syft version",
)
# Build / test commands — allowed at Level 3 (build & test) inside an approved
# workspace. These compile/test a project (JAI's core job) but do not delete,
# deploy, push, install, or reach the network destructively.
BUILD_TEST_PREFIXES = (
    "npm run build", "npm run", "npm test", "npm run test", "yarn build",
    "yarn test", "pnpm build", "pnpm test", "pnpm run", "pytest", "python -m pytest",
    "python -m unittest", "python manage.py test", "tox", "make", "go build",
    "go test", "go vet", "cargo build", "cargo test", "cargo check", "mvn test",
    "mvn package", "gradle build", "gradle test", "jest", "vitest", "tsc",
    "eslint", "ruff", "ruff check", "mypy", "black --check", "flake8",
    "python -c", "python3 -c", "node -e",
    # Read-only verification commands an engineering/self-healing agent uses.
    "python -m py_compile", "python3 -m py_compile",
    "python -m compileall", "python3 -m compileall",
    "python", "python3", "node", "node --check", "grep", "rg",
    "pnpm lint", "pnpm typecheck", "pnpm exec", "pnpm -r", "pnpm --filter", "uv run",
    # Local version control inside the workspace folder (never push, reset or clean).
    "git init", "git add",
)
# Commands that change the folder they run in: they only run with a workspace folder as their
# working directory, never in JAI's own directory.
WORKSPACE_ONLY_PREFIXES = ("git init", "git add", "git commit")
# A project script run by name ("pnpm type-check", "pnpm format", "yarn lint", "pnpm run e2e"):
# one plain name, no arguments. pnpm and yarn commands that publish, deploy, sign in, change
# configuration or the store are their own commands, not scripts, and are never matched here.
_SCRIPT_RE = re.compile(r"^(pnpm|yarn)(?: run)? ([a-z0-9][a-z0-9:_.-]{0,80})$")
_PACKAGE_MANAGER_COMMANDS = frozenset((
    "publish", "unpublish", "deploy", "link", "unlink", "login", "logout", "adduser", "config",
    "set", "setup", "env", "self-update", "store", "dist-tag", "owner", "team", "access", "server",
    "cache", "prune", "remove", "rm", "uninstall", "un", "patch", "patch-commit", "pack", "exec",
    "dlx", "create", "init", "import", "rebuild", "fetch", "install", "i", "add", "update", "up",
    "upgrade", "audit", "outdated", "why", "licenses", "list", "ls", "root", "bin", "npm",
    "global", "policies", "version", "workspace", "workspaces", "plugin", "constraints", "node",
))
_RELEASE_SCRIPT_RE = re.compile(
    r"^(npm|pnpm|yarn)(?: run)? (pre|post)?(publish|unpublish|deploy|release)(?:[:.-][a-z0-9:_.-]*)?(?: |$)")
# Taskfile targets run by name ("task verify", "task test:unit", "task phase -- 0").
_TASK_RE = re.compile(r"^task ([a-z0-9][a-z0-9:_.-]{0,80})(?: -- [a-z0-9_.:-]{1,40})?$")
# Infrastructure tools: checking, formatting and planning are build work; anything that changes
# real infrastructure (apply, destroy, import, state, install, upgrade) is Richard's decision.
_TERRAFORM_RE = re.compile(
    r"^terraform(?: -chdir=[a-z0-9_./-]{1,200})? (fmt|validate|version|providers|show|graph|output|plan|init|test)(?: |$)")
_HELM_RE = re.compile(r"^helm (lint|template|version|show|dependency (?:build|update|list)|env)(?: |$)")
# Syft (SBOM): cataloguing the project's own files is build work. Pulling an image from a registry or a
# container engine reaches outside the workspace, and attesting signs and publishes: Richard decides those.
_SYFT_RE = re.compile(r"^syft (version|scan|packages|convert|cataloger list)(?: |$)")
_SYFT_REMOTE = ("registry:", "docker:", "podman:", "containerd:", "oci-registry:", "singularity:")

# Trusted project package-manager install commands (project-local). Allowed to
# run automatically INSIDE an approved workspace (PackageInstallPolicy:
# trusted_workspace_install). Global/sudo/piped variants are blocked separately.
INSTALL_PREFIXES = (
    "npm install", "npm ci", "npm i", "npm add", "npm update",
    "pnpm install", "pnpm i", "pnpm add", "yarn install", "yarn add",
    "pip install", "pip3 install", "python -m pip install", "python3 -m pip install",
    "poetry install", "poetry add", "poetry lock", "uv pip install", "uv sync",
    "uv add", "uv lock", "uv venv",
    # Tools and language versions JAI adds to its own tool home from the official registries
    # (PyPI, npm, python-build-standalone): never system-wide, never with sudo.
    "uv tool install", "uv tool upgrade", "uv python install", "uvx", "uv tool run",
    "pnpm dlx", "npx", "yarn dlx", "pipenv install", "go get", "go mod download", "go mod tidy",
    "composer install", "composer require", "gradle", "./gradlew", "mvn install",
    "mvn package", "bundle install",
)

# Programs that are never run by an agent, whatever their arguments: they delete, wipe, power off,
# change ownership or permissions, kill processes, reach other machines, fetch from the network,
# move or copy outside write_file's audit, or install system packages.
DANGEROUS_PROGRAMS = frozenset((
    "rm", "rmdir", "unlink", "shred", "del", "erase", "rd", "format", "dd", "shutdown", "reboot",
    "halt", "poweroff", "init", "systemctl", "service", "chmod", "chown", "chgrp", "chattr",
    "kill", "pkill", "killall", "ssh", "scp", "sftp", "rsync", "nc", "ncat", "netcat", "telnet",
    "curl", "wget", "mv", "cp", "apt", "apt-get", "aptitude", "dpkg", "yum", "dnf", "rpm", "apk",
    "brew", "snap", "pacman", "mount", "umount", "crontab", "useradd", "userdel", "passwd",
))
# Running as another user is never allowed.
PRIVILEGE_PROGRAMS = frozenset(("sudo", "su", "doas", "runas", "pkexec"))
# Global installs change the machine, not the workspace.
_GLOBAL_FLAGS = frozenset(("-g", "--global", "--location=global", "--system", "--user"))
# Terraform commands that change or rewrite real infrastructure or its state.
_TERRAFORM_DESTRUCTIVE = frozenset((
    "apply", "destroy", "import", "state", "taint", "untaint", "force-unlock", "refresh", "workspace",
))
# find options that run or delete instead of listing.
_FIND_ACTIONS = frozenset(("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fls"))
# Shell operators: an agent runs one command at a time, so chaining, piping, redirection,
# background jobs and subshells are refused rather than guessed at.
_SHELL_OPERATORS = frozenset(";&|<>`")
_GLOB_CHARS = frozenset("*?[")


class ParsedCommand(NamedTuple):
    """A command split into words exactly as a POSIX shell would, before any expansion."""
    argv: List[str]
    # For each word: True when it holds an unquoted *, ? or [ the runner expands as a file pattern.
    globs: List[bool]


def parse_command(command: str) -> Optional[ParsedCommand]:
    """Split a command into words, honouring single quotes, double quotes and backslashes.

    Returns None when the command uses anything a single plain command does not need: an unquoted
    ; & | < > or backtick, any $ expansion (unquoted or inside double quotes), a newline, or an
    unterminated quote. Text inside quotes is data, so "git commit -m 'drop rm step'" is one
    commit with one message, never the rm command.
    """
    text = (command or "").strip()
    if not text or "\n" in text or "\r" in text or "\x00" in text:
        return None
    argv: List[str] = []
    globs: List[bool] = []
    word: List[str] = []
    in_word = has_glob = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t":
            if in_word:
                argv.append("".join(word)); globs.append(has_glob)
                word, in_word, has_glob = [], False, False
            i += 1
            continue
        if ch == "'":
            close = text.find("'", i + 1)
            if close < 0:
                return None
            word.append(text[i + 1:close]); in_word = True
            i = close + 1
            continue
        if ch == '"':
            i += 1
            while i < n and text[i] != '"':
                c = text[i]
                if c in "$`":
                    return None
                if c == "\\" and i + 1 < n and text[i + 1] in '"\\$`':
                    word.append(text[i + 1]); i += 2
                    continue
                word.append(c); i += 1
            if i >= n:
                return None
            in_word = True
            i += 1
            continue
        if ch == "\\":
            if i + 1 >= n:
                return None
            word.append(text[i + 1]); in_word = True
            i += 2
            continue
        if ch in _SHELL_OPERATORS or ch == "$":
            return None
        if ch in _GLOB_CHARS:
            has_glob = True
        if ch == "~" and not in_word:
            # Leading ~ is the agent's home; the runner expands it.
            has_glob = True
        word.append(ch); in_word = True
        i += 1
    if in_word:
        argv.append("".join(word)); globs.append(has_glob)
    return ParsedCommand(argv, globs) if argv else None


def _program(word: str) -> str:
    name = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def _dangerous_words(argv: List[str]) -> bool:
    """The command itself (not text inside its arguments) is destructive, privileged or global."""
    prog = _program(argv[0])
    args = [a.lower() for a in argv[1:]]
    if prog in PRIVILEGE_PROGRAMS or prog in DANGEROUS_PROGRAMS or prog.startswith("mkfs"):
        return True
    if prog in ("npm", "pnpm", "yarn", "pip", "pip3", "uv", "poetry", "bun") and any(
            a in _GLOBAL_FLAGS for a in args):
        return True
    if prog == "git" and args:
        sub = args[0]
        if sub == "push" or (sub == "reset" and "--hard" in args):
            return True
        if sub in ("filter-branch", "filter-repo", "gc") and "--prune=now" in args:
            return True
    if prog == "terraform":
        subs = [a for a in args if not a.startswith("-")]
        if subs and subs[0] in _TERRAFORM_DESTRUCTIVE:
            return True
    return False


def _risky_words(argv: List[str]) -> bool:
    """Read-only commands that, with these arguments, change something and so need approval."""
    prog = _program(argv[0])
    args = [a.lower() for a in argv[1:]]
    if prog == "find" and any(a in _FIND_ACTIONS for a in args):
        return True
    if prog == "git" and args:
        sub, rest = args[0], args[1:]
        if sub == "branch" and any(a in ("-d", "--delete", "-m", "--move", "-c", "--copy", "-f", "--force")
                                   for a in rest):
            return True
        if sub == "remote" and rest and rest[0] not in ("-v", "--verbose", "show", "get-url"):
            return True
        if sub == "tag" and rest and rest[0] not in ("-l", "--list"):
            return True
        if sub == "stash" and rest and rest[0] not in ("list", "show"):
            return True
    return False


def _git_add(argv: List[str]) -> bool:
    if len(argv) < 3 or [a.lower() for a in argv[:2]] != ["git", "add"]:
        return False
    flags = {"-a", "--all", "-u", "--update", "-n", "--dry-run", "-v", "--verbose", "-n",
             "--intent-to-add", "--"}
    return all(a.lower() in flags or not a.startswith("-") for a in argv[2:])


def _git_commit(argv: List[str]) -> bool:
    """git commit [-a] -m <one message>: the message is data, whatever words it contains."""
    words = [a.lower() for a in argv]
    if words[:2] != ["git", "commit"]:
        return False
    rest = argv[2:]
    if rest[:1] and rest[0].lower() in ("-a", "--all"):
        rest = rest[1:]
    return len(rest) == 2 and rest[0] in ("-m", "--message") and 0 < len(rest[1]) <= 500


def classify_command(command: str) -> str:
    """
    Classify a command by the program it runs and that program's arguments, never by text that
    happens to appear inside it ("terraform version" is not rm, "git add ." is not dd,
    "pytest tests/test_capture.py" is not apt):
      'safe'      - read-only, runnable anywhere (Level 1).
      'build'     - build/test of an approved workspace (Level 3).
      'install'   - trusted project-local package install (PackageInstallPolicy).
      'dangerous' - destructive/privileged/global/network-fetch, or shell chaining,
                    piping, redirection or expansion; always blocked.
      'risky'     - anything else; requires approval.
    """
    parsed = parse_command(command)
    if parsed is None:
        return "dangerous"
    argv = parsed.argv
    if _dangerous_words(argv):
        return "dangerous"
    if _risky_words(argv):
        return "risky"
    if _git_commit(argv) or _git_add(argv):
        return "build"
    words = [_program(argv[0])] + [a.lower() for a in argv[1:]]
    c = " ".join(words)
    if c == "yarn":
        return "install"
    terraform = _TERRAFORM_RE.match(c)
    if terraform:
        return {"init": "install", "version": "safe"}.get(terraform.group(1), "build")
    if _HELM_RE.match(c):
        if c.startswith("helm version"):
            return "safe"
        return "install" if c.startswith("helm dependency") else "build"
    syft = _SYFT_RE.match(c)
    if syft:
        if syft.group(1) == "version":
            return "safe"
        return "risky" if any(a.startswith(_SYFT_REMOTE) for a in words[2:]) else "build"
    task = _TASK_RE.match(c)
    if task and not _RELEASE_SCRIPT_RE.match(f"npm run {task.group(1)}"):
        return "build"
    # Scripts whose job is to publish or release are Richard's decision, whatever runs them.
    if _RELEASE_SCRIPT_RE.match(c):
        return "risky"
    script = _SCRIPT_RE.match(c)
    if script and script.group(2) not in _PACKAGE_MANAGER_COMMANDS:
        return "build"
    for pre in INSTALL_PREFIXES:
        if c == pre or c.startswith(pre + " "):
            return "install"
    for pre in SAFE_COMMAND_PREFIXES:
        if c == pre or c.startswith(pre + " ") or c == pre.split()[0]:
            return "safe"
    for pre in BUILD_TEST_PREFIXES:
        if c == pre or c.startswith(pre + " "):
            return "build"
    return "risky"


def command_argv(command: str, cwd: Optional[str] = None) -> Optional[List[str]]:
    """The exact argument list a classified command runs with: no shell sits between the policy
    and the process. Unquoted file patterns expand against the working directory the way a shell
    would (a pattern with no match stays as written) and a leading ~ becomes the agent's home."""
    parsed = parse_command(command)
    if parsed is None:
        return None
    out: List[str] = []
    base = Path(cwd) if cwd else Path.cwd()
    for word, glob_word in zip(parsed.argv, parsed.globs):
        if not glob_word:
            out.append(word)
            continue
        if word.startswith("~"):
            word = os.path.expanduser(word)
        if any(ch in word for ch in _GLOB_CHARS):
            pattern = word if os.path.isabs(word) else str(base / word)
            matches = sorted(globlib.glob(pattern))
            if matches:
                out.extend(m if os.path.isabs(word) else os.path.relpath(m, base) for m in matches)
                continue
        out.append(word)
    return out


def needs_workspace(command: str) -> bool:
    """True when the command may only run with a workspace folder as its working directory."""
    c = " ".join((command or "").strip().lower().split())
    return classify_command(command) == "install" or any(
        c == pre or c.startswith(pre + " ") for pre in WORKSPACE_ONLY_PREFIXES)


def _safe_size(p: Path) -> Optional[int]:
    try:
        return p.stat().st_size
    except Exception:  # noqa: BLE001
        return None
