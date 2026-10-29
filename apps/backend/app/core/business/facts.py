"""
JARV Backend - Workspace facts for business work

Everything JARV writes for a product (posts, docs, emails, plans, scripts) is
grounded in what the workspace actually contains: its name and mission, the
detected stack and commands, the README, recent commits, the API routes and
app pages found in the code, the live URL, completed work, KPIs, plan
objectives, roadmap, FAQs and support themes. Nothing here is invented; a fact
that is not available is simply absent.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.models.workspace import Workspace

_ROUTE_PATTERNS = (
    re.compile(r"@(?:app|router|api)\.(get|post|put|patch|delete)\(\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete)\(\s*[\"'`]([^\"'`]+)[\"'`]"),
)
_CODE_SUFFIXES = {".py", ".js", ".ts", ".mjs", ".cjs"}
_SKIP_DIRS = {"node_modules", ".git", ".next", "dist", "build", "__pycache__", ".venv", "venv", "coverage"}
_MAX_FILES = 600


@dataclass
class Facts:
    product: str
    description: str = ""
    company: str = ""
    mission: str = ""
    workspace_type: str = ""
    stack: List[str] = field(default_factory=list)
    commands: Dict[str, str] = field(default_factory=dict)
    readme: str = ""
    features: List[str] = field(default_factory=list)
    commits: List[Dict[str, str]] = field(default_factory=list)
    routes: List[Dict[str, str]] = field(default_factory=list)
    pages: List[str] = field(default_factory=list)
    live_url: Optional[str] = None
    completed: List[str] = field(default_factory=list)
    objectives: List[str] = field(default_factory=list)
    roadmap: List[str] = field(default_factory=list)
    faqs: List[Dict[str, str]] = field(default_factory=list)
    kpis: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self, limit: int = 6000) -> str:
        """Plain-text fact sheet given to the model."""
        lines = [f"Product: {self.product}"]
        for label, value in (("Description", self.description), ("Company", self.company), ("Mission", self.mission),
                             ("Type", self.workspace_type), ("Stack", ", ".join(self.stack)),
                             ("Live URL", self.live_url)):
            if value:
                lines.append(f"{label}: {value}")
        if self.commands:
            lines.append("Commands: " + "; ".join(f"{k}: {v}" for k, v in self.commands.items()))
        if self.features:
            lines.append("Features (from the README):\n- " + "\n- ".join(self.features[:15]))
        if self.completed:
            lines.append("Recently completed work:\n- " + "\n- ".join(self.completed[:15]))
        if self.commits:
            lines.append("Recent commits:\n- " + "\n- ".join(f"{c['date']} {c['subject']}" for c in self.commits[:20]))
        if self.routes:
            lines.append("API routes:\n- " + "\n- ".join(f"{r['method']} {r['path']}" for r in self.routes[:30]))
        if self.pages:
            lines.append("App pages: " + ", ".join(self.pages[:30]))
        if self.objectives:
            lines.append("Plan objectives: " + "; ".join(self.objectives[:10]))
        if self.roadmap:
            lines.append("Roadmap: " + "; ".join(self.roadmap[:10]))
        if self.kpis:
            lines.append("KPIs: " + "; ".join(f"{k['name']}={k['value']:g}{k.get('unit') or ''}" for k in self.kpis[:10]))
        if self.faqs:
            lines.append("FAQ:\n" + "\n".join(f"Q: {f['q']}\nA: {f['a']}" for f in self.faqs[:10]))
        if self.readme:
            lines.append("README excerpt:\n" + self.readme[:2500])
        return "\n".join(lines)[:limit]

    def known(self) -> List[str]:
        return [name for name in ("description", "mission", "stack", "commands", "readme", "features", "commits",
                                  "routes", "pages", "live_url", "completed", "objectives", "roadmap", "faqs", "kpis")
                if getattr(self, name)]


def _container(workspace: Workspace) -> Optional[Path]:
    from app.core.workspaces import fs_inspector

    root = (workspace.config or {}).get("root_path") if isinstance(workspace.config, dict) else None
    if not root:
        return None
    container = fs_inspector.host_to_container(root)
    return container if container is not None and container.is_dir() else None


def _readme(root: Path) -> str:
    for name in ("README.md", "README.rst", "README.txt", "readme.md"):
        path = root / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace")[:20000]
            except OSError:
                return ""
    return ""


def _features(readme: str) -> List[str]:
    """Bullet points under a Features / What it does heading, else the first bullets in the README."""
    lines = readme.splitlines()
    out: List[str] = []
    in_section = False
    for line in lines:
        heading = line.lstrip("#").strip().lower()
        if line.startswith("#"):
            in_section = any(k in heading for k in ("feature", "what it does", "highlights", "capabilities"))
            continue
        if in_section and line.strip().startswith(("-", "*")):
            out.append(line.strip().lstrip("-* ").strip())
    if not out:
        out = [l.strip().lstrip("-* ").strip() for l in lines if l.strip().startswith(("- ", "* "))][:10]
    return [f for f in out if f][:20]


def _commits(root: Path, limit: int = 30) -> List[Dict[str, str]]:
    if not (root / ".git").exists():
        return []
    try:
        out = subprocess.run(["git", "-c", f"safe.directory={root}", "log", f"-n{limit}", "--date=short",
                              "--pretty=format:%h\x1f%ad\x1f%s"], cwd=root, capture_output=True, text=True,
                             timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    commits = []
    for line in out.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            commits.append({"hash": parts[0], "date": parts[1], "subject": parts[2]})
    return commits


def _scan_code(root: Path) -> tuple[List[Dict[str, str]], List[str]]:
    routes: List[Dict[str, str]] = []
    pages: List[str] = []
    seen = 0
    for path in root.rglob("*"):
        if seen >= _MAX_FILES:
            break
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        parts = rel.split("/")
        if path.name in ("page.tsx", "page.jsx", "page.js") and "app" in parts[:-1]:
            segments = parts[parts.index("app") + 1:-1]
            pages.append("/" + "/".join(p for p in segments if not (p.startswith("(") and p.endswith(")"))))
        if path.suffix not in _CODE_SUFFIXES:
            continue
        seen += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:200000]
        except OSError:
            continue
        for pattern in _ROUTE_PATTERNS:
            for method, route in pattern.findall(text):
                routes.append({"method": method.upper(), "path": route, "file": rel})
    unique = {(r["method"], r["path"]): r for r in routes}
    return sorted(unique.values(), key=lambda r: (r["path"], r["method"]))[:200], sorted(set(pages))[:100]


async def gather(db: AsyncSession, workspace_id: UUID) -> Facts:
    from app.core.company_ops.service import company_ops
    from app.models.content import ContentItem

    ws = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
    if ws is None:
        raise LookupError("Workspace not found")
    cfg = ws.config or {}
    detected = cfg.get("detected") or {}
    facts = Facts(product=ws.company_name or ws.name, description=ws.description or "", company=ws.company_name or "",
                  mission=ws.company_mission or "", workspace_type=ws.workspace_type or "",
                  stack=list(detected.get("stack") or []), commands=dict(detected.get("commands") or {}),
                  live_url=cfg.get("live_url"),
                  roadmap=[f"{m.get('title')} ({m.get('status', 'open')})" for m in cfg.get("roadmap") or []])
    root = _container(ws)
    if root is not None:
        facts.readme = await asyncio.to_thread(_readme, root)
        facts.features = _features(facts.readme)
        facts.commits = await asyncio.to_thread(_commits, root)
        facts.routes, facts.pages = await asyncio.to_thread(_scan_code, root)
        if not facts.stack:
            from app.core.agents.workspace_ops import detect_project

            found = await asyncio.to_thread(detect_project, root)
            facts.stack, facts.commands = list(found.get("stack") or []), dict(found.get("commands") or {})
    since = datetime.now(timezone.utc) - timedelta(days=30)
    done = (await db.execute(select(Task.title).where(Task.workspace_id == workspace_id, Task.status == "completed",
                                                      Task.updated_at >= since)
                             .order_by(Task.updated_at.desc()).limit(30))).scalars().all()
    facts.completed = list(done)
    plan = await company_ops.active_plan(db, workspace_id)
    if plan is not None:
        facts.objectives = [f"{o.get('title')} ({o.get('status', 'open')})" for o in plan.objectives or []]
    facts.kpis = [{"name": k["name"], "value": k["value"], "unit": k.get("unit")}
                  for k in await company_ops.kpi_dashboard(db, workspace_id)]
    faqs = (await db.execute(select(ContentItem).where(ContentItem.workspace_id == workspace_id,
                                                       ContentItem.content_type == "faq")
                             .order_by(ContentItem.updated_at.desc()).limit(30))).scalars().all()
    facts.faqs = [{"q": f.title, "a": f.content_body} for f in faqs]
    return facts
