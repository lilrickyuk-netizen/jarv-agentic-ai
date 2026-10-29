"""
JARV Backend - Workspace lifecycle (persisted)

Creating, importing, planning, archiving and deleting workspaces for their
owner. Folders are only ever registered, scanned or created inside the
approved workspace root (fs_inspector scope rules); a new workspace never
receives more authority than the workspace that created it; deleting a
workspace removes JARV's records only and never touches files on disk.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.workspace_rules import WorkspaceRule, WorkspaceRuleVersion, WorkspaceScan

logger = logging.getLogger(__name__)

PROTECTED_RULE_TYPES = {"safety", "boundary", "authority", "security", "logging", "audit", "verification",
                        "secrets"}
ACTIVE_TASK_STATES = ("queued", "running", "recovering", "waiting_on_approval")
_FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,99}$")
_DOC_SUFFIXES = {".md", ".txt", ".rst", ".adoc", ".json", ".yaml", ".yml", ".csv", ".html"}
MAX_DOC_BYTES = 1_000_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def join_host(parent: str, name: str) -> str:
    if ":" in parent[:3] or "\\" in parent:
        return str(PureWindowsPath(parent) / name)
    return str(PurePosixPath(parent) / name)


def check_repository_url(url: str) -> Tuple[bool, Optional[str]]:
    """Repositories are cloned over public https only (no ssh, file or internal hosts)."""
    from app.core.internet import _ssrf_ok

    parsed = urlparse(url or "")
    if parsed.scheme != "https":
        return False, "only https repository URLs are accepted"
    if parsed.username or parsed.password:
        return False, "credentials must not be embedded in the URL"
    return _ssrf_ok(url)


class WorkspaceLifecycle:
    # ----- lookups -------------------------------------------------------------------------

    async def owned(self, db: AsyncSession, workspace_id: Any, owner: UUID) -> Workspace:
        try:
            key = workspace_id if isinstance(workspace_id, UUID) else UUID(str(workspace_id))
        except (TypeError, ValueError):
            raise ValueError(f"'{workspace_id}' is not a valid workspace id") from None
        row = (await db.execute(select(Workspace).where(Workspace.id == key, Workspace.owner_id == owner))
               ).scalar_one_or_none()
        if row is None:
            raise LookupError("Workspace not found")
        return row

    async def _slug(self, db: AsyncSession, name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:90] or "workspace"
        slug, n = base, 1
        while (await db.execute(select(Workspace.id).where(Workspace.slug == slug))).scalar_one_or_none():
            n += 1
            slug = f"{base[:85]}-{n}"
        return slug

    async def by_root(self, db: AsyncSession, owner: UUID, root: str) -> Optional[Workspace]:
        rows = (await db.execute(select(Workspace).where(Workspace.owner_id == owner))).scalars().all()
        norm = root.replace("\\", "/").rstrip("/").lower()
        for row in rows:
            existing = (row.config or {}).get("root_path") if isinstance(row.config, dict) else None
            if existing and existing.replace("\\", "/").rstrip("/").lower() == norm:
                return row
        return None

    # ----- create / register ------------------------------------------------------------------

    async def create(self, db: AsyncSession, owner: UUID, *, name: str, ceiling: int,
                     description: Optional[str] = None, workspace_type: str = "project",
                     root_path: Optional[str] = None, authority_level: Optional[int] = None,
                     config: Optional[Dict[str, Any]] = None, company_mode: bool = False) -> Workspace:
        from app.core.workspaces import fs_inspector

        if not name.strip():
            raise ValueError("A workspace needs a name")
        cfg: Dict[str, Any] = dict(config or {})
        if root_path:
            check = fs_inspector.path_exists(root_path)
            if not check.accessible:
                raise PermissionError(check.reason or "The folder is outside the approved workspace root")
            if not check.exists or not check.is_dir:
                raise ValueError(f"'{root_path}' is not an existing folder")
            existing = await self.by_root(db, owner, root_path)
            if existing is not None:
                raise ValueError(f"That folder is already registered as workspace '{existing.name}' ({existing.id})")
            cfg.update({"root_path": root_path, "container_path": check.container_path})
        level = min(int(authority_level if authority_level is not None else 2), int(ceiling))
        now = _now()
        row = Workspace(id=uuid4(), owner_id=owner, name=name.strip()[:255], slug=await self._slug(db, name),
                        description=description, workspace_type=workspace_type[:50], authority_level=max(level, 1),
                        is_active=True, is_archived=False, config=cfg, company_mode_enabled=company_mode,
                        created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
        return row

    async def scan(self, db: AsyncSession, workspace: Workspace, triggered_by: Optional[UUID] = None) -> Dict[str, Any]:
        """Read-only scan of the workspace folder, recorded as a WorkspaceScan with the detected project."""
        from app.core.agents.workspace_ops import detect_project, missing_files
        from app.core.workspaces import fs_inspector

        root = (workspace.config or {}).get("root_path")
        if not root:
            raise ValueError("This workspace has no folder to scan")
        started = _now()
        result = await asyncio.to_thread(fs_inspector.scan_workspace, root)
        container = fs_inspector.host_to_container(root)
        detected: Dict[str, Any] = {"stack": [], "package_managers": [], "commands": {}}
        missing: List[Dict[str, str]] = []
        if result.accessible and result.exists and container is not None and container.is_dir():
            detected = await asyncio.to_thread(detect_project, container)
            missing = await asyncio.to_thread(missing_files, container, detected)
        data = result.data or {}
        ok = bool(result.accessible and result.exists)
        health = None
        if ok:
            health = max(0.0, round(100.0 - 12.5 * len(missing), 1))
        scan = WorkspaceScan(
            id=uuid4(), workspace_id=workspace.id, scan_type="structure", scan_status="completed" if ok else "failed",
            findings=[{"kind": "detected", **detected}], issues=[{"missing": m["file"], "why": m["why"]} for m in missing],
            recommendations=[f"Add {m['file']}: {m['why']}" for m in missing], health_score=health,
            metrics={k: data.get(k) for k in ("total_files", "total_dirs", "code_file_counts") if k in data},
            started_at=started, completed_at=_now(), triggered_by=triggered_by,
            meta_data={"reason": result.reason} if not ok else {}, created_at=started, updated_at=_now())
        db.add(scan)
        cfg = dict(workspace.config or {})
        cfg["detected"] = detected
        cfg["last_scan_id"] = str(scan.id)
        workspace.config = cfg
        if detected.get("workspace_type") and workspace.workspace_type in ("project", "general"):
            workspace.workspace_type = detected["workspace_type"][:50]
        await db.flush()
        return {"scan_id": str(scan.id), "status": scan.scan_status, "health_score": health, "detected": detected,
                "missing_files": missing, "summary": data.get("summary"), "reason": result.reason}

    async def import_folder(self, db: AsyncSession, owner: UUID, *, path: str, ceiling: int,
                            name: Optional[str] = None, description: Optional[str] = None,
                            authority_level: Optional[int] = None) -> Tuple[Workspace, Dict[str, Any]]:
        label = name or PurePosixPath(path.replace("\\", "/")).name or "Workspace"
        row = await self.create(db, owner, name=label, ceiling=ceiling, description=description or f"Imported from {path}",
                                root_path=path, authority_level=authority_level,
                                config={"imported_from": "folder"})
        return row, await self.scan(db, row, owner)

    def _destination(self, parent: Optional[str], folder: str) -> Tuple[str, Path]:
        from app.core.workspaces import fs_inspector

        if not _FOLDER_RE.match(folder or "") or ".." in folder:
            raise ValueError("folder_name may use letters, digits, spaces, dot, dash and underscore only")
        parent = parent or settings.WORKSPACE_HOST_ROOT
        host = join_host(parent, folder)
        container = fs_inspector.host_to_container(host)
        if container is None or fs_inspector._is_banned(host):
            raise PermissionError(f"'{host}' is outside the approved workspace root")
        if container.exists():
            raise ValueError(f"'{host}' already exists; import it as a folder instead")
        return host, container

    async def import_repository(self, db: AsyncSession, owner: UUID, *, url: str, folder_name: str, ceiling: int,
                                branch: Optional[str] = None, parent_folder: Optional[str] = None,
                                name: Optional[str] = None, authority_level: Optional[int] = None
                                ) -> Tuple[Workspace, Dict[str, Any]]:
        allowed, reason = check_repository_url(url)
        if not allowed:
            raise PermissionError(f"Repository URL refused: {reason}")
        if branch and not re.match(r"^[A-Za-z0-9._/-]{1,100}$", branch):
            raise ValueError("Invalid branch name")
        host, container = self._destination(parent_folder, folder_name)
        args = ["git", "clone", "--depth", "50"] + (["--branch", branch] if branch else []) + ["--", url, str(container)]
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, env=env)
        try:
            _out, err = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            raise ValueError("git clone took longer than 5 minutes and was stopped") from None
        if proc.returncode != 0:
            raise ValueError(f"git clone failed: {err.decode(errors='replace')[-500:]}")
        row = await self.create(db, owner, name=name or folder_name, ceiling=ceiling,
                                description=f"Cloned from {url}", root_path=host, authority_level=authority_level,
                                config={"imported_from": "repository", "repository_url": url, "branch": branch})
        return row, await self.scan(db, row, owner)

    async def import_document_pack(self, db: AsyncSession, owner: UUID, *, folder_name: str,
                                   documents: Sequence[Dict[str, Any]], ceiling: int, parent_folder: Optional[str] = None,
                                   name: Optional[str] = None, description: Optional[str] = None,
                                   authority_level: Optional[int] = None) -> Tuple[Workspace, Dict[str, Any]]:
        """Write a pack of specs/docs into a new folder's docs/ and register it as a workspace."""
        from app.core.workspaces import fs_inspector

        if not documents:
            raise ValueError("A document pack needs at least one document")
        host, container = self._destination(parent_folder, folder_name)
        planned = []
        for doc in documents:
            filename = PurePosixPath(str(doc.get("filename") or "").replace("\\", "/")).name
            content = str(doc.get("content") or "")
            if not filename or PurePosixPath(filename).suffix.lower() not in _DOC_SUFFIXES:
                raise ValueError(f"'{doc.get('filename')}' is not a document file ({', '.join(sorted(_DOC_SUFFIXES))})")
            if len(content.encode("utf-8")) > MAX_DOC_BYTES:
                raise ValueError(f"{filename} is larger than 1 MB")
            planned.append((filename, content))
        written = []
        for filename, content in planned:
            result = fs_inspector.write_file(join_host(join_host(host, "docs"), filename), content)
            if not result.accessible:
                raise PermissionError(result.reason or f"Could not write {filename}")
            written.append({"file": f"docs/{filename}", "bytes": result.data.get("bytes_written")})
        index = "# " + (name or folder_name) + "\n\n" + "\n".join(f"- [{w['file']}]({w['file']})" for w in written) + "\n"
        fs_inspector.write_file(join_host(host, "README.md"), index)
        headings = []
        for filename, content in planned:
            for line in content.splitlines():
                if line.startswith("#"):
                    headings.append({"file": filename, "heading": line.lstrip("# ").strip()[:200]})
        row = await self.create(db, owner, name=name or folder_name, ceiling=ceiling,
                                description=description or "Document pack", root_path=host,
                                authority_level=authority_level, workspace_type="document_pack",
                                config={"imported_from": "document_pack", "documents": written,
                                        "outline": headings[:200]})
        scan = await self.scan(db, row, owner)
        return row, {**scan, "documents": written, "outline": headings[:50]}

    async def check_live(self, url: str) -> Dict[str, Any]:
        import time

        import httpx

        from app.core.internet import _ssrf_ok

        allowed, reason = _ssrf_ok(url)
        if not allowed:
            raise PermissionError(f"URL refused: {reason}")
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            return {"url": url, "up": False, "error": f"{type(exc).__name__}: {exc}", "checked_at": _now().isoformat()}
        return {"url": url, "up": response.status_code < 500, "status_code": response.status_code,
                "response_ms": round((time.perf_counter() - started) * 1000), "final_url": str(response.url),
                "https": str(response.url).startswith("https://"),
                "server": response.headers.get("server"), "checked_at": _now().isoformat()}

    async def import_live_platform(self, db: AsyncSession, owner: UUID, *, name: str, url: str, ceiling: int,
                                   health_path: Optional[str] = None, root_path: Optional[str] = None,
                                   description: Optional[str] = None, authority_level: Optional[int] = None
                                   ) -> Tuple[Workspace, Dict[str, Any]]:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("The platform URL must be an http(s) address")
        check = await self.check_live(url)
        health = None
        if health_path:
            health = await self.check_live(url.rstrip("/") + "/" + health_path.lstrip("/"))
        row = await self.create(db, owner, name=name, ceiling=ceiling, description=description or f"Live platform at {url}",
                                workspace_type="live_platform", root_path=root_path, authority_level=authority_level,
                                config={"imported_from": "live_platform", "live_url": url, "health_path": health_path,
                                        "last_check": check, "last_health_check": health})
        return row, {"check": check, "health": health}

    # ----- planning ------------------------------------------------------------------------

    async def generate_task_plan(self, db: AsyncSession, workspace: Workspace, *, goal: str,
                                 steps: Optional[Sequence[Any]] = None, model: Optional[str] = None
                                 ) -> Dict[str, Any]:
        """Create one pending task per plan step. Steps come from the caller, the model, or the project's files."""
        source = "provided"
        items = self._steps(steps)
        if not items:
            items, source = await self._model_steps(goal, workspace, model), "model"
        if not items:
            items, source = self._project_steps(workspace, goal), "project files"
        if not items:
            raise ValueError("No steps could be planned: give steps, configure a model provider, or link a folder")
        plan_id = str(uuid4())
        now = _now()
        created = []
        for n, item in enumerate(items[:30], start=1):
            task = Task(id=uuid4(), title=item["title"][:500], description=item.get("description") or goal,
                        task_type=str(item.get("type") or "plan_step")[:50], workspace_id=workspace.id, status="pending",
                        priority=int(item.get("priority") or max(1, 10 - n // 3)),
                        context={"plan_id": plan_id, "step": n, "goal": goal, "agent": item.get("agent")},
                        meta_data={"source": f"task plan ({source})"}, created_at=now, updated_at=now)
            db.add(task)
            created.append({"task_id": str(task.id), "step": n, "title": task.title, "agent": item.get("agent")})
        cfg = dict(workspace.config or {})
        plans = list(cfg.get("task_plans") or [])
        plans.append({"plan_id": plan_id, "goal": goal, "source": source, "created_at": now.isoformat(),
                      "tasks": [c["task_id"] for c in created]})
        cfg["task_plans"] = plans[-20:]
        workspace.config = cfg
        workspace.total_tasks = int(workspace.total_tasks or 0) + len(created)
        await db.flush()
        return {"plan_id": plan_id, "goal": goal, "source": source, "tasks": created}

    @staticmethod
    def _steps(steps: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
        out = []
        for step in steps or []:
            if isinstance(step, str) and step.strip():
                out.append({"title": step.strip()})
            elif isinstance(step, dict) and str(step.get("title") or "").strip():
                out.append({**step, "title": str(step["title"]).strip()})
        return out

    async def _model_steps(self, goal: str, workspace: Workspace, model: Optional[str]) -> List[Dict[str, Any]]:
        from app.core.agents.specialists import _helpers as helpers

        if not helpers.provider_configured():
            return []
        detected = (workspace.config or {}).get("detected") or {}
        prompt = (f"Goal: {goal}\nWorkspace: {workspace.name} ({workspace.workspace_type}); detected stack: "
                  f"{', '.join(detected.get('stack') or []) or 'unknown'}; commands: {json.dumps(detected.get('commands') or {})}\n"
                  "Break the goal into 3-12 ordered, concrete, verifiable steps. Reply with JSON only: "
                  '[{"title": "...", "description": "...", "agent": "coding|debugging|qa|documentation|devops|research"}]')
        reply = await helpers.llm_complete(model or "claude-sonnet-4-6", prompt,
                                           system="You plan software and business work as small verifiable steps.",
                                           temperature=0.2, max_tokens=1500)
        if not reply:
            return []
        text = reply["text"]
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            return self._steps(json.loads(text[start:end + 1]))
        except (ValueError, TypeError):
            return []

    @staticmethod
    def _project_steps(workspace: Workspace, goal: str) -> List[Dict[str, Any]]:
        detected = (workspace.config or {}).get("detected") or {}
        commands = detected.get("commands") or {}
        if not (workspace.config or {}).get("root_path"):
            return []
        steps = [{"title": f"Review the workspace and confirm the approach for: {goal}"[:500], "agent": "research"}]
        if commands.get("install"):
            steps.append({"title": f"Install dependencies ({commands['install']})", "agent": "devops"})
        steps.append({"title": f"Implement: {goal}"[:500], "agent": "coding"})
        if commands.get("build"):
            steps.append({"title": f"Build the project ({commands['build']}) and fix errors", "agent": "debugging"})
        steps.append({"title": f"Run the tests ({commands['test']})" if commands.get("test")
                      else "Add tests for the change and run them", "agent": "qa"})
        steps.append({"title": "Verify the result against the goal", "agent": "verifier"})
        steps.append({"title": "Update the documentation", "agent": "documentation"})
        return steps

    # ----- roadmap and launch checklist ----------------------------------------------------

    async def update_roadmap(self, db: AsyncSession, workspace: Workspace, milestones: Sequence[Any]) -> List[Dict[str, Any]]:
        from app.core.company_ops.service import _merge

        cfg = dict(workspace.config or {})
        roadmap = _merge(list(cfg.get("roadmap") or []), milestones)
        for item in roadmap:
            item.setdefault("status", "open")
        cfg["roadmap"] = roadmap
        cfg["roadmap_updated_at"] = _now().isoformat()
        workspace.config = cfg
        workspace.updated_at = _now()
        await db.flush()
        return roadmap

    def _auto_checks(self, workspace: Workspace) -> Dict[str, Tuple[bool, str]]:
        from app.core.workspaces import fs_inspector

        root = (workspace.config or {}).get("root_path")
        container = fs_inspector.host_to_container(root) if root else None
        checks: Dict[str, Tuple[bool, str]] = {}
        if container is not None and container.is_dir():
            def has(*names):
                return next((n for n in names if (container / n).exists()), None)

            checks["README"] = (bool(has("README.md", "README.rst", "README.txt")), "README present")
            checks["Environment template"] = (bool(has(".env.example", ".env.sample", "env.example")),
                                              ".env.example documents the settings")
            checks["Tests"] = (bool(has("tests", "test", "__tests__", "spec")), "a test folder exists")
            checks["Container build"] = (bool(has("Dockerfile", "docker-compose.yml", "compose.yaml")),
                                         "Dockerfile or compose file present")
            checks["CI pipeline"] = (bool(has(".github/workflows", ".gitlab-ci.yml")), "CI configuration present")
            checks["Licence"] = (bool(has("LICENSE", "LICENSE.md", "LICENCE")), "licence file present")
        live = (workspace.config or {}).get("last_check")
        if live:
            checks["Live site reachable"] = (bool(live.get("up")), f"last check {live.get('status_code')}")
            checks["HTTPS"] = (bool(live.get("https")), "served over https")
        return checks

    async def update_launch_checklist(self, db: AsyncSession, workspace: Workspace, items: Optional[Sequence[Any]],
                                      refresh: bool = True) -> Dict[str, Any]:
        """Manual items plus checks verified from the workspace's files and live URL."""
        from app.core.company_ops.service import _merge

        cfg = dict(workspace.config or {})
        checklist = _merge(list(cfg.get("launch_checklist") or []), items)
        if refresh:
            for title, (ok, evidence) in self._auto_checks(workspace).items():
                entry = next((i for i in checklist if i["title"] == title), None)
                if entry is None:
                    entry = {"title": title}
                    checklist.append(entry)
                entry.update({"status": "done" if ok else "open", "evidence": evidence, "verified": True,
                              "checked_at": _now().isoformat()})
        done = sum(1 for i in checklist if i.get("status") in ("done", "completed"))
        cfg["launch_checklist"] = checklist
        workspace.config = cfg
        workspace.updated_at = _now()
        await db.flush()
        return {"items": checklist, "done": done, "total": len(checklist),
                "ready": bool(checklist) and done == len(checklist)}

    # ----- rules -------------------------------------------------------------------------

    async def rule_changes(self, db: AsyncSession, workspace: Workspace, rules: Sequence[Dict[str, Any]]
                           ) -> List[Dict[str, Any]]:
        """Classify each requested change; weakening a protected rule is flagged for approval."""
        from app.core.safety.evolution_guard import classify_change

        planned = []
        for change in rules:
            name = str(change.get("name") or "").strip()
            if not name:
                raise ValueError("Every rule needs a name")
            row = (await db.execute(select(WorkspaceRule).where(WorkspaceRule.workspace_id == workspace.id,
                                                                WorkspaceRule.rule_name == name))).scalar_one_or_none()
            rule_type = str(change.get("type") or (row.rule_type if row else "workflow")).lower()
            text = json.dumps(change.get("content") or {}) + " " + str(change.get("description") or "")
            unsafe, matched = classify_change(text)
            protected = rule_type in PROTECTED_RULE_TYPES or (row is not None and row.rule_type in PROTECTED_RULE_TYPES)
            weakens = protected and row is not None and (change.get("remove") or change.get("active") is False
                                                          or change.get("content") is not None)
            planned.append({"name": name, "row": row, "type": rule_type, "change": change,
                            "needs_approval": bool(weakens or unsafe),
                            "reason": (f"text matches a safety-weakening pattern ('{matched}')" if unsafe else
                                       "changes a protected rule" if weakens else None)})
        return planned

    async def apply_rule_changes(self, db: AsyncSession, workspace: Workspace, planned: List[Dict[str, Any]],
                                 changed_by: Optional[UUID], summary: str) -> List[Dict[str, Any]]:
        now = _now()
        results = []
        for item in planned:
            row, change = item["row"], item["change"]
            if change.get("remove"):
                if row is None:
                    raise LookupError(f"Rule '{item['name']}' does not exist")
                row.is_active = False
                row.meta_data = {**(row.meta_data or {}), "removed_at": now.isoformat()}
                action = "deactivated"
            elif row is None:
                row = WorkspaceRule(id=uuid4(), workspace_id=workspace.id, rule_name=item["name"][:255],
                                    rule_type=item["type"][:50], description=change.get("description"),
                                    rule_content=change.get("content") or {}, conditions=change.get("conditions"),
                                    actions=change.get("actions"),
                                    is_active=True if change.get("active") is None else bool(change["active"]),
                                    priority=int(change.get("priority") or 5), current_version=1, created_by=changed_by,
                                    meta_data={}, created_at=now, updated_at=now)
                db.add(row)
                action = "created"
            else:
                row.current_version += 1
                for field, column in (("description", "description"), ("content", "rule_content"),
                                      ("conditions", "conditions"), ("actions", "actions"), ("priority", "priority")):
                    if change.get(field) is not None:
                        setattr(row, column, change[field])
                if change.get("active") is not None:
                    row.is_active = bool(change["active"])
                action = "updated"
            row.updated_at = now
            await db.flush()
            db.add(WorkspaceRuleVersion(id=uuid4(), rule_id=row.id, version_number=row.current_version,
                                        version_description=summary[:2000], rule_content=row.rule_content,
                                        conditions=row.conditions, actions=row.actions, changed_by=changed_by,
                                        change_summary=f"{action}: {summary}"[:2000], created_at=now, updated_at=now))
            results.append({"rule_id": str(row.id), "name": row.rule_name, "type": row.rule_type, "action": action,
                            "version": row.current_version, "active": row.is_active})
        await db.flush()
        return results

    # ----- archive / delete ---------------------------------------------------------------

    async def active_tasks(self, db: AsyncSession, workspace_id: UUID) -> int:
        await db.flush()
        return int((await db.execute(select(func.count()).select_from(Task).where(
            Task.workspace_id == workspace_id, Task.status.in_(ACTIVE_TASK_STATES)))).scalar_one())

    async def archive(self, db: AsyncSession, workspace: Workspace, archived: bool = True) -> Workspace:
        if archived:
            running = await self.active_tasks(db, workspace.id)
            if running:
                raise ValueError(f"{running} task(s) are still running or waiting in this workspace; finish or "
                                 "cancel them before archiving")
        workspace.is_archived = archived
        workspace.is_active = not archived
        workspace.updated_at = _now()
        await db.flush()
        return workspace

    async def delete(self, db: AsyncSession, workspace: Workspace) -> Dict[str, Any]:
        running = await self.active_tasks(db, workspace.id)
        if running:
            raise ValueError(f"{running} task(s) are still running or waiting in this workspace")
        summary = {"workspace_id": str(workspace.id), "name": workspace.name,
                   "folder_kept": (workspace.config or {}).get("root_path")}
        # One DELETE in the database: every table that references a workspace (and every table
        # that references its tasks or agents) is declared ON DELETE CASCADE / SET NULL, so the
        # database removes the dependent rows itself. An ORM-level cascade would have to load
        # each task's dependency collections, which an async session cannot do lazily.
        workspace_id = workspace.id
        db.expunge(workspace)
        await db.execute(sa_delete(Workspace).where(Workspace.id == workspace_id))
        await db.flush()
        return summary


workspace_lifecycle = WorkspaceLifecycle()
