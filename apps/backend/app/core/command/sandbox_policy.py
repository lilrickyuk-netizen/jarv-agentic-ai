"""
JAI Backend - What a specialist may do in JAI's engineering sandbox

A specialist working through the OpenHands sandbox has a full shell, so the old one-plain-command rule does not
apply there: chaining, pipes and redirection are how engineers work. What still holds, for every command and every
file action, before it runs:

- Scope: the mission's workspace folder is the whole world. A command may not work in, or name, another project or
  the folder above it; the file editor may not read or write outside it; with a work package, files are changed only
  inside the paths the package owns.
- Authority: a sub-agent never has more than its lead. Changing files needs level 2, running commands level 3.
- Hard boundaries (they wait for Richard; the specialist reports them and the integration lead asks him): pushing,
  publishing packages, deploying or changing cloud resources, logging in to registries, reaching other machines.
- Never: running another account (sudo, su), piping a download into a shell, reading secret stores or another
  process's environment, deleting the workspace itself or the system.
"""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, List, Optional, Tuple

from app.core.workspaces import fs_inspector

# Waits for Richard: the specialist says so in its report, the integration lead opens the boundary.
_BOUNDARIES: Tuple[Tuple[str, str], ...] = (
    (r"\bgit\b[^;&|\n]*\bpush\b", "pushing to a remote"),
    (r"\b(npm|pnpm|yarn|bun)\b[^;&|\n]*\bpublish\b", "publishing a package"),
    (r"\b(twine\s+upload|poetry\s+publish|uv\s+publish|cargo\s+publish|gem\s+push)\b", "publishing a package"),
    (r"\b(vercel|netlify|flyctl|fly|railway|heroku|firebase|wrangler|serverless|sls)\b[^;&|\n]*\b(deploy|--prod)\b",
     "deploying"),
    (r"\bterraform\b[^;&|\n]*\b(apply|destroy|import)\b", "changing real infrastructure"),
    (r"\bhelm\b[^;&|\n]*\b(install|upgrade|uninstall|rollback)\b", "changing a cluster"),
    (r"\bkubectl\b[^;&|\n]*\b(apply|create|delete|replace|patch|scale|rollout|edit)\b", "changing a cluster"),
    (r"\b(docker|podman)\b[^;&|\n]*\b(push|login)\b", "pushing to a registry"),
    (r"\bgh\b[^;&|\n]*\b(release|repo\s+(create|delete|edit)|pr\s+(create|merge)|secret)\b",
     "acting on GitHub as Richard"),
    (r"(^|[;&|\s(])(aws|gcloud|az|doctl|oci)\s", "using a cloud account"),
    (r"\b(ssh|scp|sftp)\b\s", "reaching another machine"),
    (r"\b(rsync)\b[^;&|\n]*@", "reaching another machine"),
)
# Never run, whoever asks.
_NEVER: Tuple[Tuple[str, str], ...] = (
    (r"(^|[;&|\s(])(sudo|su|doas|chroot|nsenter)\s", "running as another account"),
    (r"\b(curl|wget)\b[^|;\n]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "running a downloaded script unseen"),
    (r"(^|[;&|\s(])(docker|podman)\s", "using containers (the sandbox has none)"),
    (r"\bgit\b[^;&|\n]*\bconfig\b[^;&|\n]*\b(credential|url\.)", "changing git's credentials"),
)
# Checked on the whole line, quotes and all: a secret's path is a secret's path inside quotes too.
_SECRET_STORES = re.compile(r"/proc/[^\s/]*/environ|/run/secrets|\bid_rsa\b|/\.ssh\b|/\.aws\b|/\.gnupg\b|"
                            r"password-store", re.IGNORECASE)
_RM = re.compile(r"(^|[;&|\s(])rm\s+((-[a-zA-Z]+\s+)*)(.+?)(?=$|[;&|])")
_DANGEROUS_RM_TARGETS = {"/", "/*", "~", "~/", "~/*", ".", "./", "./*", "..", "../", "*", ".git"}


# Scratch space for fresh-clone checks and throwaway builds; nothing of another project is there.
SCRATCH = "/tmp"


@dataclass
class Scope:
    root: str                       # the workspace folder, as the sandbox sees it
    owns: Tuple[str, ...] = ()      # paths the work package owns (absolute, inside root); empty: all of root
    authority: int = 3
    home: str = "/home/openhands"


def _norm(path: str) -> str:
    return os.path.normpath(path)


def _inside(path: str, folder: str) -> bool:
    path, folder = _norm(path), _norm(folder)
    return path == folder or path.startswith(folder.rstrip("/") + "/")


def _workspaces() -> List[str]:
    from app.core.config import settings

    return [_norm(str(settings.WORKSPACE_CONTAINER_ROOT)), _norm(fs_inspector.SANDBOX_CONTAINER_ROOT)]


def _resolve(word: str, cwd: str, home: str) -> Optional[str]:
    """The absolute path a word names, when it looks like a path at all."""
    word = word.strip().strip("'\"")
    if "=" in word and not word.startswith(("/", ".", "~")):  # --out=dist/x, KEY=/some/path
        word = word.split("=", 1)[1]
    if not word or word.startswith("-") or "://" in word:
        return None
    if word.startswith("~"):
        word = home + word[1:]
    if word.startswith("/"):
        return _norm(word)
    if word.startswith("..") or "/../" in word or word.endswith("/.."):
        return _norm(str(PurePosixPath(cwd) / word))
    return None


def _outside(path: str, scope: Scope) -> bool:
    """A path in JAI's workspaces that is not this mission's folder (another project, or the folder above)."""
    if _inside(path, scope.root):
        return False
    return any(_inside(path, ws) or _inside(ws, path) for ws in _workspaces())


def _words(command: str) -> Iterable[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:  # an unfinished quote: split on spaces
        return command.split()


_QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")
_INNER = re.compile(r"\b(?:(?:ba|z|da)?sh\s+-c|eval|xargs(?:\s+-\S+)*)\s+('([^']*)'|\"((?:[^\"\\]|\\.)*)\")")


def _commands_in(text: str, depth: int = 0) -> List[str]:
    """The command line with quoted text (commit messages, echo strings) set aside, plus the commands quoted
    for a shell to run (bash -c '...', eval "..."), so a word inside a message is not taken for a command."""
    parts = [_QUOTED.sub("''", text)]
    if depth < 3:
        for match in _INNER.finditer(text):
            parts += _commands_in(match.group(2) if match.group(2) is not None else match.group(3), depth + 1)
    return parts


def check_command(command: str, cwd: str, scope: Scope) -> Optional[str]:
    """Why ``command`` may not run in the sandbox, or None."""
    if scope.authority < 3:
        return f"Not run: running commands needs authority 3; this specialist has {scope.authority}."
    if not (_inside(cwd or scope.root, scope.root) or _inside(cwd, SCRATCH)):
        return (f"Not run: the terminal is in {cwd}, outside this mission's workspace ({scope.root}) and the "
                f"scratch space (/tmp). Run cd {scope.root} first.")
    text = " ".join(command.split())
    if _SECRET_STORES.search(text):
        return "Not run: reading a secret store is never done from JAI's sandbox."
    for part in _commands_in(text):
        for pattern, what in _NEVER:
            if re.search(pattern, part, re.IGNORECASE):
                return f"Not run: {what} is never done from JAI's sandbox."
        for pattern, what in _BOUNDARIES:
            if re.search(pattern, part, re.IGNORECASE):
                return (f"Not run: {what} waits for Richard's approval. Leave it, finish the rest, and say in your "
                        f"final report exactly what should be done; the mission's lead asks Richard.")
    for match in _RM.finditer(text):
        flags = match.group(2) or ""
        if "r" in flags.lower() or "R" in flags:
            for target in match.group(4).split():
                resolved = _resolve(target, cwd or scope.root, scope.home) or _norm(
                    str(PurePosixPath(cwd or scope.root) / target.strip("'\"")))
                if target.strip("'\"") in _DANGEROUS_RM_TARGETS or resolved in ("/", _norm(scope.root)) \
                        or _inside(scope.root, resolved):
                    return f"Not run: deleting {target} would delete the workspace or more."
    for word in _words(command):
        resolved = _resolve(word, cwd or scope.root, scope.home)
        if resolved and _outside(resolved, scope):
            return (f"Not run: {word} is outside this mission's workspace ({scope.root}). Work only inside it; "
                    f"other projects are not this mission's.")
    return None


def check_file(command: str, path: str, scope: Scope) -> Optional[str]:
    """Why the file editor may not do ``command`` on ``path``, or None."""
    if not path.startswith("/"):
        path = str(PurePosixPath(scope.root) / path)
    path = _norm(path)
    if not _inside(path, scope.root):
        return f"Not done: {path} is outside this mission's workspace ({scope.root})."
    if fs_inspector._is_banned(path[len(scope.root):]):
        return f"Not done: {path} looks like a secret or credential store, which JAI's agents never open."
    if command != "view":
        if scope.authority < 2:
            return f"Not done: changing files needs authority 2; this specialist has {scope.authority}."
        if scope.owns and not any(_inside(path, owned) for owned in scope.owns):
            return (f"Not done: {path} is outside your work package. You write only in "
                    f"{', '.join(scope.owns)}; another specialist owns the rest. Put what that file needs in "
                    f"your final report for the integration lead.")
    return None
