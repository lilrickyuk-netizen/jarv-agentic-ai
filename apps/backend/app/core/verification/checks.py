"""
JARV Backend - Hard conformance checks for the Verifier (Upgrade 1a)

Deterministic checks that read the workspace's files and compare them with the workspace's authority documents.
They run before the Verifier agent forms its view and any failure is an unmet requirement whatever the agent
concludes, so a mission cannot be accepted while its own files contradict the specification. Read-only: these
checks open files and never run commands or change anything.

The checks:

* ``spec_pins``: every exact version in the authority documents' tables (``| Python | 3.14.7 |``) against the
  files that pin it: ``.python-version``, ``.nvmrc``/``.node-version``, ``requires-python`` in pyproject.toml and
  uv.lock, ``packageManager`` and dependency versions in every package.json, Terraform ``required_version``.
* ``lockfile``: every dependency a workspace package.json declares is recorded, with the same specifier, in
  pnpm-lock.yaml's importers.
* ``document_claims``: a document that says a component was pinned, aligned or locked at a version, when the
  files show a different one.
* ``open_blockers``: an ADR whose status is Open, Blocked or Blocking.
* ``superseded_authority``: a file that calls a superseded document authoritative.
* ``stray_files`` (repositories with authority documents): scripts in the repository root or scripts/ that nothing
  in the repository refers to (conventional entry points such as main.py and manage.py excepted).

Configuration (the workspace's config): ``authority_docs`` (paths of the governing specification, e.g.
["MYCO_V3_SPEC.md"]) and ``superseded_docs`` (documents it replaced, e.g. ["Myco_design.md"]).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".turbo", "dist", "build", ".next",
             ".terraform", "coverage", ".pytest_cache", ".mypy_cache", "target", ".cache"}
MAX_FILE_BYTES = 1_500_000
MAX_FILES = 6000
SPEC_LIKE_PINS = 5
# Files a runtime or tool starts by convention, never strays.
ENTRY_POINTS = {"main", "app", "manage", "wsgi", "asgi", "server", "index", "cli", "run", "dodo", "fabfile"}
SCRIPT_SUFFIXES = {".py", ".sh", ".ps1", ".js", ".mjs", ".cjs", ".ts", ".bash"}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".py", ".sh", ".ps1", ".js", ".mjs", ".cjs",
                 ".ts", ".tsx", ".tf", ".hcl", ".cfg", ".ini", ".lock", ".rego", ".bash", ".dockerfile", ""}

_VERSION = re.compile(r"(?<![\w.])v?(\d+\.\d+(?:\.\d+)?)(?![\w.]*\d)")
_EXACT_CELL = re.compile(r"^\s*v?(\d+\.\d+(?:\.\d+)?)\b")

# Components named in specification tables -> how the files pin them. "npm" lists package names checked in
# package.json files; "py" lists distribution names checked in pyproject.toml dependencies.
COMPONENTS: Dict[str, Dict[str, Sequence[str]]] = {
    "node": {"aliases": ("node.js", "node", "nodejs"), "probe": ("node",)},
    "python": {"aliases": ("python", "cpython"), "probe": ("python",)},
    "pnpm": {"aliases": ("pnpm",), "probe": ("pnpm",)},
    "terraform": {"aliases": ("terraform",), "probe": ("terraform",)},
    "typescript": {"aliases": ("typescript",), "npm": ("typescript",)},
    "vitest": {"aliases": ("vitest",), "npm": ("vitest",)},
    "turborepo": {"aliases": ("turborepo", "turbo"), "npm": ("turbo",)},
    "biome": {"aliases": ("biome",), "npm": ("@biomejs/biome",)},
    "react": {"aliases": ("react",), "npm": ("react", "react-dom")},
    "vite": {"aliases": ("vite",), "npm": ("vite",)},
    "react router": {"aliases": ("react router",), "npm": ("react-router", "react-router-dom")},
    "tanstack react query": {"aliases": ("tanstack react query", "tanstack query"), "npm": ("@tanstack/react-query",)},
    "zustand": {"aliases": ("zustand",), "npm": ("zustand",)},
    "tailwind css": {"aliases": ("tailwind css", "tailwind"), "npm": ("tailwindcss",)},
    "fastify": {"aliases": ("fastify",), "npm": ("fastify",)},
    "drizzle orm": {"aliases": ("drizzle orm", "drizzle"), "npm": ("drizzle-orm",)},
    "node-redis": {"aliases": ("node-redis",), "npm": ("redis",)},
    "neo4j js driver": {"aliases": ("neo4j js driver",), "npm": ("neo4j-driver",)},
    "strykerjs": {"aliases": ("strykerjs", "stryker"), "npm": ("@stryker-mutator/core",)},
    "xterm.js": {"aliases": ("xterm.js",), "npm": ("@xterm/xterm",)},
    "pytest": {"aliases": ("pytest",), "py": ("pytest",)},
    "hypothesis": {"aliases": ("hypothesis",), "py": ("hypothesis",)},
    "mutmut": {"aliases": ("mutmut",), "py": ("mutmut",)},
    "pydanticai": {"aliases": ("pydanticai", "pydantic ai", "pydantic-ai"), "py": ("pydantic-ai", "pydantic-ai-slim")},
    "temporal python sdk": {"aliases": ("temporal python sdk",), "py": ("temporalio",)},
    "transformers": {"aliases": ("transformers",), "py": ("transformers",)},
    "trl": {"aliases": ("trl",), "py": ("trl",)},
    "vllm": {"aliases": ("vllm",), "py": ("vllm",)},
}

_CLAIM_VERBS = re.compile(r"\b(aligned|pinned|locked|set to|updated to|upgraded to|bumped to|moved to|now uses|"
                          r"uses|is at|are at|runs on)\b", re.IGNORECASE)
_SUPERSEDED_SAFE = re.compile(r"supersed|replac|historical|no longer|not authoritative|deprecated|retired|"
                              r"obsolete|archiv|does not govern|non-authoritative", re.IGNORECASE)
_AUTHORITY_WORDS = re.compile(r"authoritative|the authority|source of truth|governs|governing|takes precedence|"
                              r"is canonical|are canonical", re.IGNORECASE)
_ADR_STATUS = re.compile(r"^\s*[-*]?\s*\**status\**\s*:?\**\s*:?\s*(.+)$", re.IGNORECASE)


@dataclass
class Finding:
    check: str
    file: str
    detail: str

    def text(self) -> str:
        return f"[{self.check}] {self.file}: {self.detail}"


# ----------------------------------------------------------------------------------------------- file access

class Repo:
    """A read-only view of the workspace folder, walked once."""

    def __init__(self, root: Path):
        self.root = root
        self.files: List[Path] = []
        for path in sorted(self._walk(root)):
            self.files.append(path)
            if len(self.files) >= MAX_FILES:
                break
        self._text: Dict[Path, Optional[str]] = {}

    def _walk(self, folder: Path) -> Iterable[Path]:
        try:
            entries = list(folder.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in SKIP_DIRS:
                    yield from self._walk(entry)
            elif entry.is_file():
                yield entry

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def text(self, path: Path) -> Optional[str]:
        if path not in self._text:
            try:
                self._text[path] = (path.read_text(encoding="utf-8", errors="replace")
                                    if path.stat().st_size <= MAX_FILE_BYTES else None)
            except OSError:
                self._text[path] = None
        return self._text[path]

    def named(self, *names: str) -> List[Path]:
        wanted = set(names)
        return [p for p in self.files if p.name in wanted]

    def get(self, relative: str) -> Optional[Path]:
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root.resolve())
        except ValueError:
            return None
        return path if path.is_file() else None


# ------------------------------------------------------------------------------------------ the spec's pins

def spec_pins(repo: Repo, authority_docs: Sequence[str]) -> Dict[str, Tuple[str, str]]:
    """{component: (version, document)} from the authority documents' Markdown tables. When a component appears in
    more than one table row, the last row wins (later sections of a specification revise earlier ones)."""
    pins: Dict[str, Tuple[str, str]] = {}
    for doc in authority_docs:
        path = repo.get(doc)
        body = repo.text(path) if path else None
        if not body:
            continue
        for line in body.splitlines():
            if not line.lstrip().startswith("|"):
                continue
            cells = [c.strip().strip("*`") for c in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            name = cells[0].lower()
            match = _EXACT_CELL.match(cells[1])
            if not match:
                continue
            for component, spec in COMPONENTS.items():
                if name in spec["aliases"]:
                    pins[component] = (match.group(1), doc)
    return pins


def _version_of(spec: str) -> Optional[str]:
    """The version a declaration fixes: "==3.12.8", "= 1.16.3", "5.8.2", "^5.8.2", "pnpm@12.5.1", ">=3.12"."""
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", spec or "")
    return match.group(1) if match else None


def _matches(found: str, locked: str) -> bool:
    return found == locked or found.startswith(locked + ".")


def _is_exact(spec: str) -> bool:
    spec = (spec or "").strip()
    return bool(re.fullmatch(r"(==|=)?\s*v?\d+\.\d+\.\d+", spec)) or bool(re.fullmatch(r"[\w@/.-]+@\d+\.\d+\.\d+",
                                                                                         spec))


def _pyproject_deps(data: dict) -> Dict[str, str]:
    deps: Dict[str, str] = {}
    lists = list((data.get("project") or {}).get("dependencies") or [])
    for group in ((data.get("project") or {}).get("optional-dependencies") or {}).values():
        lists.extend(group or [])
    for group in (data.get("dependency-groups") or {}).values():
        lists.extend(item for item in (group or []) if isinstance(item, str))
    for item in lists:
        match = re.match(r"\s*([A-Za-z0-9_.\-]+)\s*(?:\[[^\]]*\])?\s*(.*)", str(item))
        if match:
            deps[match.group(1).lower().replace("_", "-")] = match.group(2).split(";")[0].strip()
    return deps


def declared_versions(repo: Repo) -> Dict[str, List[Tuple[str, str, str]]]:
    """{component: [(file, declaration, version)]} for every place the files pin a component."""
    import tomllib

    found: Dict[str, List[Tuple[str, str, str]]] = {}

    def add(component: str, path: Path, declaration: str) -> None:
        version = _version_of(declaration)
        if version:
            found.setdefault(component, []).append((repo.rel(path), declaration.strip(), version))

    for path in repo.named(".python-version"):
        add("python", path, (repo.text(path) or "").strip().splitlines()[0] if (repo.text(path) or "").strip() else "")
    for path in repo.named(".nvmrc", ".node-version"):
        body = (repo.text(path) or "").strip()
        if body:
            add("node", path, body.splitlines()[0])
    for path in repo.named("pyproject.toml"):
        try:
            data = tomllib.loads(repo.text(path) or "")
        except Exception:  # noqa: BLE001 - an unreadable file is reported by the tests, not here
            continue
        requires = (data.get("project") or {}).get("requires-python")
        if requires:
            add("python", path, f"requires-python = {requires}")
        deps = _pyproject_deps(data)
        for component, spec in COMPONENTS.items():
            for dist in spec.get("py", ()):
                if dist in deps and deps[dist]:
                    add(component, path, f"{dist} {deps[dist]}")
    for path in repo.named("uv.lock"):
        match = re.search(r'^requires-python\s*=\s*"([^"]+)"', repo.text(path) or "", re.MULTILINE)
        if match:
            add("python", path, f"requires-python = {match.group(1)}")
    for path in repo.named("package.json"):
        try:
            data = json.loads(repo.text(path) or "{}")
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        manager = str(data.get("packageManager") or "")
        if manager.startswith("pnpm@"):
            add("pnpm", path, f"packageManager {manager}")
        node = (data.get("engines") or {}).get("node") if isinstance(data.get("engines"), dict) else None
        if node:
            add("node", path, f"engines.node {node}")
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            block = data.get(section) or {}
            if not isinstance(block, dict):
                continue
            for component, spec in COMPONENTS.items():
                for package in spec.get("npm", ()):
                    value = str(block.get(package) or "")
                    if value and not value.startswith(("workspace:", "catalog:", "link:", "file:")):
                        add(component, path, f"{section}.{package} {value}")
    for path in repo.files:
        if path.suffix == ".tf":
            for match in re.finditer(r'required_version\s*=\s*"([^"]+)"', repo.text(path) or ""):
                add("terraform", path, f"required_version {match.group(1)}")
    return found


def check_spec_pins(repo: Repo, pins: Dict[str, Tuple[str, str]],
                    found: Dict[str, List[Tuple[str, str, str]]]) -> List[Finding]:
    findings = []
    for component, (locked, doc) in sorted(pins.items()):
        for file, declaration, version in found.get(component, []):
            if not _matches(version, locked):
                findings.append(Finding("spec_pins", file,
                                        f"{component} is {declaration!r} but {doc} locks {locked}"))
    return findings


# ------------------------------------------------------------------------------------------------ lockfile

def pnpm_importers(text: str) -> Dict[str, Dict[str, str]]:
    """{importer path: {package: specifier}} from pnpm-lock.yaml (v6 to v9 layout), read by indentation."""
    importers: Dict[str, Dict[str, str]] = {}
    in_importers = False
    current: Optional[str] = None
    section: Optional[str] = None
    package: Optional[str] = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if indent == 0:
            in_importers = line == "importers:"
            current = section = package = None
            continue
        if not in_importers:
            continue
        key, _, value = line.partition(":")
        key = key.strip().strip("'\"")
        if indent == 2:
            current, section, package = key, None, None
            importers.setdefault(current, {})
        elif indent == 4 and current is not None:
            section = key if key in ("dependencies", "devDependencies", "optionalDependencies",
                                     "peerDependencies") else None
            package = None
        elif indent == 6 and current is not None and section:
            package = key
            if value.strip():
                importers[current][package] = value.strip().strip("'\"")
        elif indent == 8 and current is not None and section and package and key == "specifier":
            importers[current][package] = value.strip().strip("'\"")
    return importers


def check_lockfile(repo: Repo) -> List[Finding]:
    lock = repo.get("pnpm-lock.yaml")
    if lock is None:
        return []
    importers = pnpm_importers(repo.text(lock) or "")
    findings = []
    for path in repo.named("package.json"):
        try:
            data = json.loads(repo.text(path) or "{}")
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        rel_dir = repo.rel(path.parent) if path.parent != repo.root else "."
        if rel_dir != "." and not _is_workspace_member(repo, rel_dir):
            continue
        recorded = importers.get(rel_dir, {})
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            for package, specifier in (data.get(section) or {}).items():
                if package not in recorded:
                    findings.append(Finding("lockfile", repo.rel(path),
                                            f"{section}.{package} {specifier} is not in pnpm-lock.yaml (importer "
                                            f"{rel_dir!r}); the lockfile does not match the manifests"))
                elif recorded[package] != str(specifier):
                    findings.append(Finding("lockfile", repo.rel(path),
                                            f"{section}.{package} is {specifier} but pnpm-lock.yaml records "
                                            f"{recorded[package]}"))
    return findings


def _is_workspace_member(repo: Repo, rel_dir: str) -> bool:
    spec = repo.get("pnpm-workspace.yaml")
    if spec is None:
        return False
    patterns = re.findall(r"^\s*-\s*['\"]?([^'\"\s#]+)", _packages_block(repo.text(spec) or ""), re.MULTILINE)
    from fnmatch import fnmatch

    return any(fnmatch(rel_dir, pattern.rstrip("/")) for pattern in patterns if not pattern.startswith("!"))


def _packages_block(text: str) -> str:
    lines, inside = [], False
    for raw in text.splitlines():
        if raw.startswith("packages:"):
            inside = True
            continue
        if inside:
            if raw and not raw.startswith((" ", "-", "\t")):
                break
            lines.append(raw)
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------- document claims

def _sentences(text: str, *, keep_code: bool = False) -> Iterable[str]:
    """Prose sentences: fenced code and table rows are skipped (a table is a specification, not a claim about the
    files), each list item is its own sentence, and inline code is dropped unless ``keep_code`` (a file name in
    backticks is still a reference to that file)."""
    prose: List[str] = []
    fenced = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
            prose.append("")
            continue
        if fenced or stripped.startswith("|"):
            prose.append("")
            continue
        if re.match(r"^([-*+]|\d+\.)\s+", stripped) or stripped.startswith("#"):
            prose.append("")
        prose.append(stripped)
    # Inline code is a command or a path, not a statement of what the files pin.
    body = "\n".join(prose)
    if not keep_code:
        body = re.sub(r"`[^`\n]*`", " (code) ", body)
    for paragraph in re.split(r"\n\s*\n", body):
        joined = " ".join(paragraph.split())
        for sentence in re.split(r"(?<=[.;!?])\s+(?=[A-Z`*])", joined):
            if sentence:
                yield sentence


_ALIAS_INDEX: List[Tuple[str, str]] = sorted(
    ((alias, component) for component, spec in COMPONENTS.items() for alias in spec["aliases"]),
    key=lambda pair: -len(pair[0]))


def _mentions(sentence: str) -> List[Tuple[int, int, str]]:
    """(start, end, component) for each component named in the sentence, longest names first, no overlaps."""
    low = sentence.lower()
    taken: List[Tuple[int, int, str]] = []
    for alias, component in _ALIAS_INDEX:
        for match in re.finditer(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", low):
            if not any(a < match.end() and match.start() < b for a, b, _c in taken):
                taken.append((match.start(), match.end(), component))
    return sorted(taken)


def claimed_versions(sentence: str) -> List[Tuple[str, str]]:
    """(component, version) pairs a sentence states: the first version after each component's name, before the
    next component is named, at most 14 words on; for "A -> B" the version after the arrow."""
    pairs = []
    mentions = _mentions(sentence)
    for index, (_start, end, component) in enumerate(mentions):
        stop = mentions[index + 1][0] if index + 1 < len(mentions) else len(sentence)
        window = " ".join(sentence[end:stop].split()[:14])
        match = _VERSION.search(window)
        if not match:
            continue
        version = match.group(1)
        after = window[match.end():]
        arrow = re.match(r"\s*(?:→|->|=>|to)\s*v?(\d+\.\d+(?:\.\d+)?)", after)
        pairs.append((component, arrow.group(1) if arrow else version))
    return pairs


def check_document_claims(repo: Repo, found: Dict[str, List[Tuple[str, str, str]]],
                          exclude: Set[str]) -> List[Finding]:
    findings = []
    for path in repo.files:
        if path.suffix.lower() != ".md" or repo.rel(path) in exclude:
            continue
        if len(spec_pins(repo, [repo.rel(path)])) >= SPEC_LIKE_PINS:
            continue  # another copy or draft of a specification: it states targets, not what the files hold
        for sentence in _sentences(repo.text(path) or ""):
            if not _CLAIM_VERBS.search(sentence):
                continue
            for component, claimed in claimed_versions(sentence):
                actual = {version for _f, _d, version in found.get(component, [])}
                if actual and not any(_matches(version, claimed) or _matches(claimed, version)
                                      for version in actual):
                    findings.append(Finding("document_claims", repo.rel(path),
                                            f"says {component} is {claimed} (\"{sentence[:160]}\") but the files "
                                            f"pin {', '.join(sorted(actual))}"))
    return findings


# ------------------------------------------------------------------------------------------ open blockers

def check_open_blockers(repo: Repo) -> List[Finding]:
    findings = []
    for path in repo.files:
        rel = repo.rel(path)
        if path.suffix.lower() != ".md" or "template" in path.name.lower():
            continue
        if "/adr/" not in f"/{rel.lower()}" and not re.match(r"(adr[-_ ]?)?\d{3,4}[-_]", path.name.lower()):
            continue
        for line in (repo.text(path) or "").splitlines()[:25]:
            match = _ADR_STATUS.match(line)
            if not match:
                continue
            status = match.group(1).strip().strip("*").strip()
            if re.match(r"(open|blocked|blocking)\b", status, re.IGNORECASE) or re.search(r"\bblocking\b", status,
                                                                                          re.IGNORECASE):
                findings.append(Finding("open_blockers", rel, f"status is \"{status[:120]}\"; an open blocker "
                                                              f"must be resolved, or closed with its evidence"))
            break
    return findings


# ---------------------------------------------------------------------------------- superseded authority

def check_superseded(repo: Repo, superseded: Sequence[str], exclude: Set[str]) -> List[Finding]:
    findings = []
    names = [s for s in superseded if s]
    if not names:
        return findings
    for path in repo.files:
        rel = repo.rel(path)
        if rel in exclude or path.suffix.lower() not in {".md", ".txt", ".yaml", ".yml", ".json", ".toml"}:
            continue
        body = repo.text(path) or ""
        if not any(Path(n).name in body for n in names):
            continue
        for sentence in _sentences(body, keep_code=True):
            if (any(Path(n).name in sentence for n in names) and _AUTHORITY_WORDS.search(sentence)
                    and not _SUPERSEDED_SAFE.search(sentence)):
                findings.append(Finding("superseded_authority", rel,
                                        f"treats a superseded document as authoritative: \"{sentence[:200]}\""))
    return findings


# ------------------------------------------------------------------------------------------- stray files

def check_stray_files(repo: Repo) -> List[Finding]:
    candidates = [p for p in repo.files if p.suffix.lower() in SCRIPT_SUFFIXES
                  and (p.parent == repo.root or (repo.rel(p).startswith("scripts/") and repo.rel(p).count("/") == 1))
                  and not p.name.startswith(("eslint.config", "vitest.config", "vite.config", "tailwind.config",
                                             "postcss.config", "next.config", "jest.config", "babel.config",
                                             "conftest", "setup.", "noxfile", "__init__"))
                  and p.stem not in ENTRY_POINTS]
    if not candidates:
        return []
    corpus: List[Tuple[Path, str]] = [(p, repo.text(p) or "") for p in repo.files
                                      if p.suffix.lower() in TEXT_SUFFIXES and p.name not in (
                                          "pnpm-lock.yaml", "uv.lock", "package-lock.json", "yarn.lock")]
    findings = []
    for script in candidates:
        stem = script.stem
        dotted = repo.rel(script.with_suffix("")).replace("/", ".")
        referenced = any(other != script and (script.name in body or dotted in body
                                              or re.search(rf"\b{re.escape(stem)}\b", body))
                         for other, body in corpus)
        if not referenced:
            findings.append(Finding("stray_files", repo.rel(script),
                                    "nothing in the repository runs or refers to this script; remove it or wire "
                                    "it into a task, workflow or document"))
    return findings


# ---------------------------------------------------------------------------------------------- entry point

def run_hard_checks(root: Path, config: Optional[dict] = None) -> Dict[str, object]:
    """All checks on the folder at ``root``. Returns {"ran": [...], "findings": [...], "pins": {...}}."""
    config = config or {}
    authority = [str(d) for d in (config.get("authority_docs") or []) if str(d).strip()]
    superseded = [str(d) for d in (config.get("superseded_docs") or []) if str(d).strip()]
    repo = Repo(root)
    exclude = set(authority) | set(superseded)
    found = declared_versions(repo)
    findings: List[Finding] = []
    ran = ["lockfile", "open_blockers"]
    pins = spec_pins(repo, authority) if authority else {}
    if authority:
        # A repository governed by a specification is held to it in full, stray files included.
        ran += ["spec_pins", "document_claims", "stray_files"]
        findings += check_spec_pins(repo, pins, found)
        findings += check_document_claims(repo, found, exclude)
        findings += check_stray_files(repo)
    if superseded:
        ran.append("superseded_authority")
        findings += check_superseded(repo, superseded, exclude)
    findings += check_lockfile(repo)
    findings += check_open_blockers(repo)
    return {"ran": ran, "findings": [asdict(f) for f in findings], "authority_docs": authority,
            "superseded_docs": superseded,
            "pins": {component: version for component, (version, _doc) in pins.items()},
            "files_scanned": len(repo.files)}


def render_findings(result: Dict[str, object], limit: int = 40) -> str:
    findings = result.get("findings") or []
    if not findings:
        return f"All hard checks passed ({', '.join(result.get('ran') or [])})."
    lines = [Finding(**f).text() for f in findings[:limit]]  # type: ignore[arg-type]
    if len(findings) > limit:
        lines.append(f"... and {len(findings) - limit} more")
    return "\n".join(lines)
