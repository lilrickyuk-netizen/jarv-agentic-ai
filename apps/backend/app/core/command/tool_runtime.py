"""
JAI Backend - Tool Execution Runtime

Confirmed tool-execution layer for the command pipeline. Agents act through
real, named tools (not prose). Every call is:

  * executed for real (filesystem read-only inspection, memory persistence, etc.),
  * authority-checked,
  * logged to the audit trail and the Live Operations Feed (item_type="tool"),
  * recorded on the owning task (task.result["tool_calls"]) so it shows in task
    detail.

This wraps the real implementations (fs_inspector, MemoryService, the boundary/
feed writers) behind a stable tool surface so the dashboard can prove that JAI
actually acted, with which tool, on which inputs, and with what result.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

import asyncio

from app.core.config import settings
from app.core.jarv_memory import memory_service
from app.core.safety.permission_policy import (
    PermissionDecision,
    check_tool_permission,
    get_tool_policy,
)
from app.core.security import redact_secrets, redact_text
from app.core.workspaces import fs_inspector
from app.models.company_operations import LiveOperationsFeedItem
from app.models.execution import CommandRun, FileChange
from app.models.operations import AuditLog

logger = logging.getLogger(__name__)

# A file is read in parts of this many characters (next_offset says where it continues).
READ_CHUNK_CHARS = 16000

# Authority level required per tool (kept in sync with the central policy in
# app.core.safety.permission_policy; that policy is the enforcement source).
_TOOL_AUTHORITY = {
    "list_files": 1,
    "read_file": 1,
    "search_files": 1,
    "scan_workspace": 1,
    "memory_add": 1,
    "memory_search": 1,
    "create_live_operations_feed_item": 1,
    "create_boundary_report": 1,
    "run_safe_readonly_command": 3,
    "run_command": 3,
    "write_file": 2,
    "send_notification": 4,
    "fetch_url": 1,
    "web_search": 1,
    "research_web": 1,
    "generate_image": 2,
    "read_mission_report": 1,
    "make_voiceover": 2,
    "make_video": 2,
    "social_channels": 1,
    "social_draft": 2,
    "code_overview": 1, "code_find_symbol": 1, "code_references": 1, "code_implementations": 1,
    "code_diagnostics": 1,
    "read_document": 1, "use_browser": 2, "knowledge_graph_search": 1, "knowledge_graph_add": 1,
    "recall_richard": 1, "run_prompt_checks": 2,
    "check_package_registry": 1,
    "check_cve": 1,
    "asset_licence_check": 1,
    # Repair 12e-3a workspace tools
    "edit_file": 2, "create_folder": 2, "move_file": 2, "copy_file": 2, "delete_file_with_boundary": 2,
    "get_file_metadata": 1, "detect_workspace_type": 1, "detect_stack": 1, "detect_commands": 1,
    "find_missing_files": 1, "check_installed": 1, "get_command_log": 1, "git_create_branch": 2,
    "git_push_with_boundary": 5, "memory_link_to_workspace": 1, "memory_link_to_task": 1,
}



# Programs whose runs take minutes: test runners, builds, installs, infrastructure checks and task runners.
_LONG_RUNNING = frozenset({"task", "make", "just", "pnpm", "npm", "npx", "yarn", "uv", "uvx", "pip", "poetry",
                           "pytest", "vitest", "jest", "tsc", "terraform", "helm", "docker", "cargo", "go",
                           "gradle", "mvn", "dotnet", "turbo", "nx", "syft", "trivy", "gitleaks"})


def command_timeout(command: str, classification: Optional[str] = None, approved: bool = False) -> int:
    """How long a command may run: the long limit for builds, tests, installs, task runners, SBOM scans and any
    command Richard approved (he approved it to run, not to be stopped after two minutes), else the short."""
    first = (command or "").strip().split(" ", 1)[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".exe", ".cmd"):
        first = first[:-len(suffix)] if first.endswith(suffix) else first
    if approved or classification in ("build", "install") or first in _LONG_RUNNING:
        return int(settings.AGENT_LONG_COMMAND_TIMEOUT_SECONDS)
    return int(settings.AGENT_COMMAND_TIMEOUT_SECONDS)

# Commands that start a server or a watcher: they never end on their own, so as a mission step they would hold the
# mission until the command timeout (up to 15 minutes) and then report nothing useful.
_RUNNERS = ("npx", "pnpx", "bunx", "uvx")
_EXEC = {("pnpm", "exec"), ("pnpm", "dlx"), ("yarn", "dlx"), ("yarn", "exec"), ("npm", "exec"), ("uv", "run"),
         ("poetry", "run"), ("pipenv", "run")}
_SERVER_SCRIPTS = {"dev", "start", "serve", "watch", "preview", "develop"}
_SERVERS = {("next", "dev"), ("next", "start"), ("nuxt", "dev"), ("nuxi", "dev"), ("astro", "dev"),
            ("remix", "dev"), ("vite", "dev"), ("vite", "serve"), ("vite", "preview"), ("webpack", "serve"),
            ("ng", "serve"), ("expo", "start"), ("react-scripts", "start"), ("flask", "run"),
            ("fastapi", "dev"), ("fastapi", "run"), ("wrangler", "dev"), ("vercel", "dev"), ("netlify", "dev"),
            ("gatsby", "develop"), ("svelte-kit", "dev"), ("ember", "serve"), ("hugo", "server"),
            ("jekyll", "serve"), ("rails", "server"), ("rails", "s"), ("php", "artisan")}
_ALWAYS_SERVERS = {"uvicorn", "gunicorn", "hypercorn", "daphne", "nodemon", "http-server", "live-server",
                   "webpack-dev-server", "tsc-watch", "serve", "json-server", "browser-sync"}


def never_ends(argv: List[str]) -> Optional[str]:
    """Why ``argv`` would run until it is stopped (a dev server, a watcher, compose in the foreground), or None."""
    words = [str(w) for w in argv]
    while words:
        head = Path(words[0]).name.lower()
        if head in _RUNNERS:
            words = words[1:]
        elif len(words) > 1 and (head, words[1].lower()) in _EXEC:
            words = words[2:]
        else:
            break
        while words and words[0].startswith("-"):  # npx -y next dev
            words = words[1:]
    if not words:
        return None
    head = Path(words[0]).name.lower()
    rest = [w.lower() for w in words[1:]]
    flags = set(rest)
    why = None
    if flags & {"--watch", "--watchall", "--watch-all"} or (head == "tsc" and "-w" in flags):
        why = "it watches for changes and never finishes"
    elif head in _ALWAYS_SERVERS:
        why = f"{head} starts a server that keeps running"
    elif head in ("npm", "pnpm", "yarn", "bun"):
        script = rest[1] if rest[:1] == ["run"] and len(rest) > 1 else (rest[0] if rest else "")
        if script in _SERVER_SCRIPTS:
            why = f"'{head} {'run ' if rest[:1] == ['run'] else ''}{script}' starts the app's server or watcher"
    elif head == "vite" and (not rest or rest[0].startswith("-")):
        why = "vite on its own starts the development server"
    elif head == "vitest" and (not rest or rest[0] in ("watch", "dev")):
        why = "vitest on its own watches for changes"
    elif rest and (head, rest[0]) in _SERVERS and not (head == "php" and rest[1:2] != ["serve"]):
        why = f"'{head} {rest[0]}' starts a server that keeps running"
    elif head in ("python", "python3") and rest[:2] in (["-m", "http.server"], ["manage.py", "runserver"]):
        why = "it starts a server that keeps running"
    elif head == "manage.py" and rest[:1] == ["runserver"]:
        why = "it starts a server that keeps running"
    elif head in ("docker", "docker-compose"):
        sub = rest[1:] if head == "docker" and rest[:1] == ["compose"] else rest
        if sub[:1] == ["up"] and not flags & {"-d", "--detach", "--wait"}:
            why = "compose in the foreground keeps running"
        elif head == "docker" and rest[:1] == ["logs"] and flags & {"-f", "--follow"}:
            why = "following logs never finishes"
    if why is None:
        return None
    return (f"Not run: {why}, so it would hold this step until the command timeout and tell you nothing. Run the "
            "check once instead: the build (for example `npm run build`), the tests once (`vitest run`, `jest`, "
            "`pytest`), the type check (`tsc --noEmit`), or the project's own smoke test. To try a server, "
            "use `docker compose up -d` (or `--wait`) and then a single request to it.")


def _stop_group(proc) -> None:
    """Stop a command and everything it started."""
    if proc is None or proc.returncode is not None:
        return
    import os
    import signal

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except Exception:  # noqa: BLE001 - the process ended already, or has no group of its own
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


class ToolRuntime:
    """Executes named tools, recording each call on the task + feed + audit.

    Repair 10: EVERY tool method passes through one shared permission gate
    (app.core.safety.permission_policy.check_tool_permission) BEFORE executing.
    A hard-blocked action never runs. An approval-gated action pauses ONLY
    itself: when the runtime has enough context it opens the real Richard
    Boundary chain (BoundaryReport -> SafeCheckpoint -> pending BoundaryApproval)
    and sets the linked Task to waiting_on_approval; unrelated work continues.
    """

    def __init__(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        task_id: Optional[UUID],
        operator: str = "operator",
        authority_level: int = 5,
        user_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        open_boundary_flows: bool = True,
    ):
        self.db = db
        self.workspace_id = workspace_id
        self.task_id = task_id
        self.operator = operator
        self.authority_level = authority_level
        self.user_id = user_id
        self.session_id = session_id
        self.agent_id = agent_id
        self.open_boundary_flows = open_boundary_flows
        self._block_counts: Dict[str, int] = {}
        # Folder a paused command was to run in, kept with its checkpoint so the approved
        # command runs in the same folder (a mission's folder is not always its workspace's).
        self._command_cwd: Optional[str] = None
        # Exact arguments of a boundary tool (delete, push) about to be gated, kept with its checkpoint so
        # the approved action is the one that runs, in the folder it was asked for.
        self.pending_tool_args: Optional[Dict[str, Any]] = None
        # Whether opening a boundary pauses this runtime's task. A mission's agent loop turns
        # this off: only the blocked action waits, the mission keeps going.
        self.pause_task_on_boundary = True
        self.calls: List[Dict[str, Any]] = []

    # ----- recording -----

    async def _record(
        self, tool: str, inputs: Dict[str, Any], success: bool,
        summary: str, output: Optional[Dict[str, Any]] = None,
    ) -> None:
        required = _TOOL_AUTHORITY.get(tool, 1)
        # Secrets never reach the task record, the feed, or the audit trail.
        safe_inputs = redact_secrets(inputs)
        safe_summary = redact_text(str(summary))
        entry = {
            "tool": tool,
            "inputs": safe_inputs,
            "success": success,
            "summary": safe_summary,
            "authority_level": required,
            "authorized": self.authority_level >= required,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if output is not None:
            entry["output"] = redact_secrets(output)
        self.calls.append(entry)
        # Operations feed
        try:
            self.db.add(LiveOperationsFeedItem(
                id=uuid4(), workspace_id=self.workspace_id, item_type="tool",
                severity="info" if success else "error",
                title=f"Tool: {tool}", message=safe_summary,
                related_task_id=self.task_id, requires_action=False,
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            ))
            await self.db.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"tool feed write failed: {exc}")
        # Audit
        try:
            self.db.add(AuditLog(
                id=uuid4(), workspace_id=self.workspace_id, actor_type="tool",
                action=f"tool:{tool}", action_category="tool_execution",
                description=safe_summary, target_type="task",
                target_id=str(self.task_id) if self.task_id else None,
                after_state={"tool": tool, "inputs": safe_inputs, "operator": self.operator},
                success=success, authority_level=required,
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            ))
            await self.db.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"tool audit write failed: {exc}")

    def _authorized(self, tool: str) -> bool:
        return self.authority_level >= _TOOL_AUTHORITY.get(tool, 1)

    # ----- central permission enforcement (Repair 10) -----

    def _check_permission(
        self,
        tool: str,
        *,
        command: Optional[str] = None,
        path: Optional[str] = None,
        action_description: Optional[str] = None,
        content: Optional[str] = None,
        requires_approval_flag: Optional[bool] = None,
        allow_build: bool = True,
        allow_install: bool = True,
        approval_granted: bool = False,
    ) -> PermissionDecision:
        """Run the ONE shared permission check for this runtime's context."""
        path_in_scope: Optional[bool] = None
        if path is not None and get_tool_policy(tool).workspace_scope_required:
            path_in_scope = fs_inspector.host_to_container(path) is not None
        return check_tool_permission(
            tool_id=tool,
            command=command,
            target_path=path,
            action_description=action_description,
            content=content,
            operator=self.operator,
            agent_id=self.agent_id,
            task_id=self.task_id,
            workspace_id=self.workspace_id,
            authority_level=self.authority_level,
            requires_approval_flag=requires_approval_flag,
            approval_granted=approval_granted,
            path_in_scope=path_in_scope,
            allow_build=allow_build,
            allow_install=allow_install,
        )

    async def _enforce(
        self,
        tool: str,
        *,
        command: Optional[str] = None,
        path: Optional[str] = None,
        action_description: Optional[str] = None,
        content: Optional[str] = None,
        requires_approval_flag: Optional[bool] = None,
        allow_build: bool = True,
        allow_install: bool = True,
        approval_granted: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Permission gate every tool method calls FIRST.

        Returns None when the action may execute now. Otherwise returns the
        structured blocked/paused result the tool method must return verbatim
        (the action did NOT run). Approval-gated actions open the real Richard
        Boundary chain when context allows; hard-blocked actions never do.
        """
        decision = self._check_permission(
            tool, command=command, path=path, action_description=action_description,
            content=content, requires_approval_flag=requires_approval_flag,
            allow_build=allow_build, allow_install=allow_install,
            approval_granted=approval_granted,
        )
        if decision.allowed:
            return None

        display = decision.redacted_display
        base = {
            "success": False,
            "blocked": True,
            "requires_approval": decision.requires_approval,
            "boundary_type": decision.boundary_type,
            "risk_level": decision.risk_level,
            "reason": decision.boundary_reason,
            "safe_alternative": decision.safe_alternative,
            "redacted_display": display,
        }

        if not decision.requires_approval:
            # Never-runnable on this path: record and stop (no approval chain).
            await self._record(
                tool, {"display": display}, False,
                f"blocked ({decision.boundary_type}): {decision.boundary_reason}",
                output={"permission": decision.to_dict()})
            return base

        # Approval-gated: pause ONLY this action and open the real boundary
        # chain (report -> checkpoint -> pending approval) when context allows.
        await self._record(
            tool, {"display": display}, False,
            f"paused for approval ({decision.boundary_type}): {decision.boundary_reason}",
            output={"permission": decision.to_dict()})
        chain = await self._open_boundary(
            tool, decision, command=command, path=path,
            action_description=action_description)
        base.update(chain)
        return base

    async def _ensure_operator_user_id(self) -> Optional[UUID]:
        """Resolve the runtime's user to a REAL users row (get-or-create).

        The operator string is the authenticated identity from the API layer;
        coercion matches the operator identity mapping in app.core.auth so the same operator
        always maps to the same UUID. The row is real (FKs must hold).
        """
        from app.core.richard.workflow import coerce_user_id
        from sqlalchemy import select
        from app.models.user import User

        uid = self.user_id or coerce_user_id(self.operator)
        if uid is None:
            return None
        row = (await self.db.execute(
            select(User).where(User.id == uid))).scalar_one_or_none()
        if row is None:
            self.db.add(User(
                id=uid, username=f"op-{uid.hex[:12]}",
                email=f"op-{uid.hex[:12]}@jarv.local",
                password_hash="!external-authenticated-operator",
                is_active=True, is_admin=False,
            ))
            await self.db.flush()
        return uid

    async def _open_boundary(
        self,
        tool: str,
        decision: PermissionDecision,
        *,
        command: Optional[str] = None,
        path: Optional[str] = None,
        action_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Open the real Richard Boundary chain for one approval-gated action.

        Persists BoundaryReport + SafeCheckpoint + pending BoundaryApproval
        linked to this runtime's workspace/task, pauses ONLY the linked task,
        and returns the chain ids. If persistence is impossible the honest
        partial state is returned (requires_approval stays True; nothing is
        faked as paused-with-chain).
        """
        if not self.open_boundary_flows:
            return {"boundary_chain_opened": False,
                    "boundary_chain_reason": "boundary flows disabled for this runtime"}
        try:
            from app.core.richard.workflow import RichardBoundaryWorkflow

            uid = await self._ensure_operator_user_id()
            if uid is None:
                return {"boundary_chain_opened": False,
                        "boundary_chain_reason": "no operator identity available"}
            wf = RichardBoundaryWorkflow(self.db)
            agent = await wf.ensure_orchestrator_agent(self.workspace_id)
            sess = await wf.ensure_session(
                session_id=self.session_id, user_id=uid,
                workspace_id=self.workspace_id, agent_id=self.agent_id or agent.id,
                initial_prompt=None, session_name="tool-runtime")
            self.session_id = sess.id  # reuse for later boundaries in this runtime

            display = decision.redacted_display
            blocked_action = (action_description or display or tool)[:1000]
            # The snapshot stores only REDACTED values. If redaction changed the
            # input, the raw secret is never persisted; Richard re-enters it via
            # the Repair 14 secret-entry surface when the action resumes.
            raw = command or action_description or path or ""
            needs_secret_reentry = (
                (bool(raw) and redact_text(raw) != raw)
                or decision.boundary_type == "secret_material")
            snapshot = {
                "blocked_task": {
                    "task_id": str(self.task_id) if self.task_id else None,
                    "agent": "orchestrator",
                    "description": blocked_action,
                    "tool": tool,
                    "command": redact_text(command) if command else None,
                    "target_path": path,
                    "cwd": self._command_cwd if tool == "run_command" else None,
                    "tool_args": self.pending_tool_args if tool != "run_command" else None,
                    "requested_authority_level": int(
                        decision.audit_metadata.get("required_authority") or 0),
                },
                "input_hash": decision.audit_metadata.get("input_hash"),
                "next_step": "execute_blocked_action",
                "retry_counters": {"blocks": self._block_counts.get(
                    " ".join((command or blocked_action).lower().split()), 0)},
                "requires_secret_reentry": needs_secret_reentry,
                "secret_entry_reference": (
                    "deferred:repair14-secret-entry-ui" if needs_secret_reentry else None),
            }
            self.pending_tool_args = None
            res = await wf.handle_hard_boundary(
                session_id=sess.id,
                agent_id=self.agent_id or agent.id,
                workspace_id=self.workspace_id,
                user_id=uid,
                blocked_action=blocked_action,
                boundary_type=decision.boundary_type or "approval_required",
                reason=decision.boundary_reason or "approval required",
                severity=decision.risk_level,
                requested_authority_level=int(
                    decision.audit_metadata.get("required_authority") or 0),
                available_authority_level=int(self.authority_level),
                task_id=self.task_id,
                resume_snapshot=snapshot,
                detection=decision.audit_metadata.get("detection") or {},
                pause_task=self.pause_task_on_boundary,
            )
            if res.get("status") == "needs_operator_review":
                return {"boundary_chain_opened": False,
                        "status": "needs_operator_review",
                        "boundary_chain_reason": res.get("reason")}
            if res.get("status") != "waiting_on_richard":
                return {"boundary_chain_opened": False,
                        "boundary_chain_reason": res.get("reason", "chain not persisted")}
            return {
                "boundary_chain_opened": True,
                "status": "waiting_on_approval",
                "boundary_report_id": res.get("boundary_report_id"),
                "approval_id": res.get("approval_id"),
                "checkpoint_id": res.get("checkpoint_id"),
                "session_id": res.get("session_id"),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error(f"boundary chain open failed: {exc}", exc_info=True)
            try:
                await self.db.rollback()
            except Exception:  # noqa: BLE001
                pass
            return {"boundary_chain_opened": False,
                    "boundary_chain_reason": f"boundary persistence failed: {exc}"}

    # ----- file / workspace tools -----

    async def list_files(self, path: str) -> Dict[str, Any]:
        denied = await self._enforce("list_files", path=path)
        if denied:
            return denied
        res = fs_inspector.list_dir(path)
        ok = res.accessible and res.exists
        entries = res.data.get("entries", []) if ok else []
        await self._record(
            "list_files", {"path": path}, ok,
            f"{len(entries)} entries listed" if ok else (res.reason or "not accessible"),
            output={"count": len(entries)},
        )
        return {"success": ok, "entries": entries, "reason": res.reason}

    async def read_file(self, path: str, offset: int = 0) -> Dict[str, Any]:
        denied = await self._enforce("read_file", path=path)
        if denied:
            return denied
        res = fs_inspector.read_file(path, max_bytes=READ_CHUNK_CHARS, offset=offset)
        ok = res.accessible and res.exists
        redacted = res.data.get("redacted") if ok else None
        await self._record(
            "read_file", {"path": path, "offset": offset}, ok,
            ("read (redacted)" if redacted else "read") if ok else (res.reason or "not accessible"),
            output={"redacted": redacted, "bytes": res.data.get("size_bytes")},
        )
        return {"success": ok, "data": res.data, "reason": res.reason}

    async def scan_workspace(self, path: str) -> Dict[str, Any]:
        denied = await self._enforce("scan_workspace", path=path)
        if denied:
            return denied
        res = fs_inspector.scan_workspace(path)
        ok = res.accessible and res.exists
        await self._record(
            "scan_workspace", {"path": path}, ok,
            res.data.get("summary", "") if ok else (res.reason or "not accessible"),
            output={"total_files": res.data.get("total_files")} if ok else None,
        )
        return {"success": ok, "data": res.data, "reason": res.reason,
                "accessible": res.accessible, "exists": res.exists}

    # ----- memory tools -----

    async def memory_add(self, content: str, memory_type: str = "fact",
                         importance: float = 0.7) -> Dict[str, Any]:
        denied = await self._enforce("memory_add", content=content,
                                     action_description=f"store {memory_type} memory")
        if denied:
            return denied
        rec = await memory_service.add(
            self.db, content=content, memory_type=memory_type,
            workspace_id=self.workspace_id, task_id=self.task_id, importance=importance,
        )
        await self._record("memory_add", {"memory_type": memory_type}, True,
                           f"stored memory {rec.id}", output={"memory_id": str(rec.id)})
        return {"success": True, "memory_id": str(rec.id)}

    async def memory_search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        denied = await self._enforce("memory_search")
        if denied:
            return denied
        rows = await memory_service.search(self.db, query, limit=limit,
                                           workspace_id=self.workspace_id)
        results = [{"id": str(r.id), "type": r.memory_type, "content": r.content,
                    "created_at": r.created_at.isoformat() if r.created_at else None}
                   for r in rows]
        await self._record("memory_search", {"query": query}, True,
                           f"{len(results)} memories matched", output={"count": len(results)})
        return {"success": True, "results": results}

    # ----- write tool (authority-gated, scope + secret enforced) -----

    async def write_file(self, host_path: str, content: str,
                         overwrite: bool = False, append: bool = False) -> Dict[str, Any]:
        denied = await self._enforce("write_file", path=host_path, content=content)
        if denied:
            return denied
        if append:
            # A long file written in parts: this part goes after what the file already holds.
            existing, offset = [], 0
            while offset is not None:
                found = fs_inspector.read_file(host_path, max_bytes=READ_CHUNK_CHARS, offset=offset)
                if not (found.accessible and found.exists) or found.data.get("redacted"):
                    break
                existing.append(found.data.get("content", ""))
                offset = found.data.get("next_offset")
            content = "".join(existing) + content
            overwrite = True
        res = fs_inspector.write_file(host_path, content, overwrite=overwrite)
        ok = res.accessible and res.exists
        await self._record(
            "write_file", {"path": host_path, "bytes": len(content)}, ok,
            (f"wrote {res.data.get('bytes_written')} bytes "
             f"({'created' if res.data.get('created') else 'updated'})") if ok else (res.reason or "blocked"),
            output={"created": res.data.get("created") if ok else None},
        )
        # Persist a FileChange record (best-effort).
        if ok:
            try:
                agent_id = await memory_service._agent_id(self.db, self.workspace_id)
                prev = res.data.get("previous_content")
                self.db.add(FileChange(
                    id=uuid4(), agent_id=agent_id,
                    file_path=res.container_path or host_path,
                    file_name=host_path.replace("\\", "/").rstrip("/").split("/")[-1],
                    file_type=(host_path.rsplit(".", 1)[-1] if "." in host_path else None),
                    change_type="create" if res.data.get("created") else "update",
                    operation="write_file",
                    previous_content=prev, new_content=content,
                    authority_level_used=_TOOL_AUTHORITY["write_file"],
                    required_approval=False,
                    executed_at=datetime.now(timezone.utc), success=True,
                    can_rollback=prev is not None,
                    meta_data={"host_path": host_path, "operator": self.operator,
                               "task_id": str(self.task_id) if self.task_id else None},
                    created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
                ))
                await self.db.flush()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"FileChange write failed: {exc}")
            await self._graph("record_file", host_path, content)
        return {"success": ok, "data": res.data, "reason": res.reason}

    # ----- code/command execution (read-only safe; dangerous blocked) -----

    async def run_safe_readonly_command(self, command: str,
                                        cwd_host: Optional[str] = None) -> Dict[str, Any]:
        return await self.run_command(command, cwd_host, allow_build=False)

    async def run_command(self, command: str, cwd_host: Optional[str] = None,
                          allow_build: bool = True, allow_install: bool = True,
                          timeout: Optional[int] = None, approval_granted: bool = False) -> Dict[str, Any]:
        """
        Execute a command with classification-based gating:
          safe -> always; build -> allowed when allow_build (Level 3, in workspace);
          install -> trusted local package install, allowed when allow_install AND
                     run inside an approved workspace (PackageInstallPolicy);
          dangerous -> blocked; risky -> requires approval.
        Captures stdout/stderr/exit, times out, persists a CommandRun.
        """
        cls = fs_inspector.classify_command(command)
        if timeout is None:
            timeout = command_timeout(command, cls, approved=approval_granted)
        cwd = None
        if cwd_host:
            chk = fs_inspector.path_exists(cwd_host)
            cwd = chk.container_path if (chk.accessible and chk.exists) else None

        # Repeated-block guard: after 2 blocks of the same command, tell the agent
        # to stop retrying (re-plan) instead of looping on a blocked command.
        norm = " ".join((command or "").lower().split())
        repeated = self._block_counts.get(norm, 0) >= 2

        # Central permission gate (Repair 10): destructive/privileged/pipe-to-
        # shell/unknown-executable commands are blocked outright; risky and
        # policy-gated build/install commands pause ONLY this action for
        # approval (opening the real boundary chain when context allows).
        self._command_cwd = cwd_host if cwd else None
        denied = await self._enforce("run_command", command=command,
                                     allow_build=allow_build,
                                     allow_install=allow_install,
                                     approval_granted=approval_granted)
        if denied:
            self._block_counts[norm] = self._block_counts.get(norm, 0) + 1
            if repeated:
                denied["reason"] = (str(denied.get("reason") or "") +
                                    " STOP: this command has been blocked repeatedly — do NOT "
                                    "retry it; use write_file or a single allowed command "
                                    "(no &&, ;, |, >).")
            denied["classification"] = cls
            denied["repeated_block"] = repeated
            if not denied.get("requires_approval"):
                await self._persist_command_run(command, cwd_host, None, "", "blocked", False,
                                                dangerous=True)
            return denied

        if fs_inspector.needs_workspace(command) and not cwd:
            what = "Package install" if cls == "install" else "This command"
            await self._record("run_command", {"command": command}, False,
                               "blocked: must run inside an approved workspace")
            await self._persist_command_run(command, cwd_host, None, "", "blocked", False,
                                            dangerous=True)
            return {"success": False, "blocked": True, "classification": cls,
                    "reason": f"{what} blocked: not inside an approved workspace."}
        if cls == "install":
            timeout = max(timeout, 420)  # installs can take minutes

        # safe/build/install: execute with timeout, capture stdout/stderr/exit code. The process
        # runs the exact words the policy classified, with no shell in between to reinterpret them.
        argv = fs_inspector.command_argv(command, cwd)
        if not argv:
            await self._record("run_command", {"command": command}, False, "blocked: not one plain command")
            return {"success": False, "blocked": True, "classification": "dangerous",
                    "reason": "Run one plain command (no &&, ;, |, >, $ or backticks)."}
        endless = never_ends(argv)
        if endless:
            await self._record("run_command", {"command": command}, False, endless)
            return {"success": False, "classification": cls, "never_ends": True, "reason": endless}
        stdout = stderr = ""
        exit_code = -1
        proc = None
        try:
            # Its own process group, so a timeout stops everything it started (a dev server's children too).
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd,
                stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
            stdout = out.decode("utf-8", errors="replace")[:8000]
            stderr = err.decode("utf-8", errors="replace")[:4000]
        except (asyncio.TimeoutError, asyncio.CancelledError) as stopped:
            _stop_group(proc)
            if isinstance(stopped, asyncio.CancelledError):
                raise
            await self._record("run_command", {"command": command}, False,
                               f"timed out after {timeout}s")
            await self._persist_command_run(command, cwd_host, None, "timeout", "timeout", False)
            return {"success": False, "reason": f"Command timed out after {timeout}s."}
        except FileNotFoundError:
            reason = (f"'{argv[0]}' is not installed. Install it into your tool home and run it there: a language "
                      f"or tool through mise ('mise install <tool>@<version>', then 'mise exec <tool>@<version> -- "
                      f"{argv[0]} ...'), a Python or Node tool through uvx, uv tool install, pnpm dlx or npx. Never "
                      "download or install anything into the project folder. A missing tool is not a blocker.")
            await self._record("run_command", {"command": command}, False, reason)
            await self._persist_command_run(command, cwd_host, 127, "", reason, False)
            return {"success": False, "exit_code": 127, "stdout": "", "stderr": reason,
                    "classification": cls, "reason": reason}
        except Exception as exc:  # noqa: BLE001
            await self._record("run_command", {"command": command}, False, str(exc))
            return {"success": False, "reason": str(exc)}

        ok = exit_code == 0
        await self._record("run_command", {"command": command, "cwd": cwd_host}, ok,
                           f"exit={exit_code}, {len(stdout)} bytes stdout",
                           output={"exit_code": exit_code})
        await self._persist_command_run(command, cwd_host, exit_code, stdout, stderr, ok)
        return {"success": ok, "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
                "classification": cls}

    async def _persist_command_run(self, command, cwd, exit_code, stdout, stderr, success,
                                   dangerous=False):
        try:
            agent_id = await memory_service._agent_id(self.db, self.workspace_id)
            self.db.add(CommandRun(
                id=uuid4(), agent_id=agent_id, command=redact_text(command or ""),
                command_type="readonly",
                working_directory=cwd,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                exit_code=exit_code if isinstance(exit_code, int) else None,
                stdout=redact_text((stdout or ""))[:8000],
                stderr=redact_text((stderr or ""))[:4000], success=success,
                authority_level_used=_TOOL_AUTHORITY["run_safe_readonly_command"],
                required_approval=False, is_dangerous=dangerous,
                meta_data={"task_id": str(self.task_id) if self.task_id else None,
                           "operator": self.operator},
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            ))
            await self.db.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"CommandRun write failed: {exc}")
        await self._graph("record_command", redact_text(command or ""),
                          exit_code if isinstance(exit_code, int) else None)

    async def _graph(self, method: str, *args, **kwargs) -> None:
        """Add this write or command to the workspace's artifact graph (Upgrade 3), in a savepoint so a failure
        here never undoes the action or the mission's transaction."""
        if self.workspace_id is None:
            return
        try:
            from app.core.graph import graph_service

            async with self.db.begin_nested():
                await getattr(graph_service, method)(self.db, self.workspace_id, self.task_id, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"artifact graph {method} failed: {exc}")

    # ----- external I/O (dry-run by default; secret-safe) -----

    async def send_notification(self, target: str, message: str,
                                dry_run: bool = True) -> Dict[str, Any]:
        # A REAL outbound send from Richard's accounts is a hard boundary;
        # dry-run previews are safe and proceed without approval.
        denied = await self._enforce(
            "send_notification",
            action_description=f"send real notification to {target}" if not dry_run else None,
            content=message,
            requires_approval_flag=(not dry_run))
        if denied:
            return denied
        from app.core.integrations import integrations
        result = await integrations.send(target, message, dry_run=dry_run)
        await self._record(
            "send_notification", {"target": target, "dry_run": dry_run}, result["ok"],
            result["summary"], output={"mode": result["mode"]},
        )
        return result

    # ----- safe internet tools (read-only, SSRF-guarded, logged + source-recorded) -----

    async def _source_record(self, url: str, title: str, source_type: str, summary: str) -> None:
        """Persist a web source record (memory_type=source) so claims are traceable. It is a record, never the
        reason a mission fails: an identical record already kept is left as it is (so agents reading the same page
        at once never lock the same row), and the write is in a savepoint, so a failure undoes only itself."""
        try:
            async with self.db.begin_nested():
                await memory_service.add(
                    self.db, content=f"[source:{source_type}] {title or url} | {url} | {summary}"[:600],
                    memory_type="source", workspace_id=self.workspace_id, task_id=self.task_id,
                    importance=0.55, meta={"url": url, "source_type": source_type, "title": title},
                    reinforce=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"source record failed: {exc}")

    async def web_search(self, query: str, limit: int = 8, category: Optional[str] = None,
                         time_range: Optional[str] = None) -> Dict[str, Any]:
        denied = await self._enforce("web_search", content=query)
        if denied:
            return denied
        from app.core.internet import web_search as _search

        res = await _search(query, max(1, min(int(limit or 8), 20)), category, time_range)
        ok = bool(res.get("ok"))
        await self._record("web_search", {"query": query, "category": category, "time_range": time_range}, ok,
                           f"{len(res.get('results') or [])} result(s) from {res.get('source') or 'search'}"
                           if ok else str(res.get("reason"))[:120],
                           output={"results": len(res.get("results") or []), "source": res.get("source")})
        return {**res, "success": ok}

    async def research_web(self, question: str, depth: str = "quick", category: Optional[str] = None,
                           time_range: Optional[str] = None) -> Dict[str, Any]:
        denied = await self._enforce("research_web", content=question)
        if denied:
            return denied
        from app.core.internet.research import research

        res = await research(question, depth, category, time_range)
        ok = bool(res.get("ok"))
        await self._record("research_web", {"question": question, "depth": depth}, ok,
                           f"{res.get('pages_read', 0)} source(s) read" if ok else str(res.get("reason"))[:120],
                           output={"sources": len(res.get("sources") or []), "queries": res.get("queries")})
        for source in res.get("sources") or []:
            await self._source_record(source["url"], source.get("title", ""), "web_research", question[:200])
        return {**res, "success": ok}

    async def read_document(self, host_path: Optional[str] = None, url: Optional[str] = None,
                            offset: int = 0) -> Dict[str, Any]:
        """A PDF, Word, PowerPoint, Excel, HTML or scanned document, from the workspace or a public address, as
        Markdown (Docling), in parts of 16,000 characters (next_offset says where the next part starts)."""
        from app.core import documents

        source = host_path or url or ""
        denied = await self._enforce("read_document", path=host_path, content=source)
        if denied:
            return denied
        try:
            if host_path:
                found = fs_inspector.read_bytes(host_path, max_bytes=documents.MAX_BYTES)
                if not (found.accessible and found.exists):
                    await self._record("read_document", {"path": host_path}, False, found.reason or "not readable")
                    return {"success": False, "error": found.reason or "That file cannot be read."}
                name, data = Path(str(found.container_path)).name, found.data["bytes"]
            else:
                name, data = await self._download_document(str(url or ""))
            converted = await documents.convert(name, data)
        except (documents.DocumentUnavailable, ValueError) as exc:
            await self._record("read_document", {"path": host_path, "url": url}, False, str(exc)[:120])
            return {"success": False, "error": str(exc)}
        chunk = documents.part(converted["markdown"], offset)
        await self._record("read_document", {"path": host_path, "url": url, "offset": chunk["offset"]}, True,
                           f"{name}: {chunk['total_chars']} characters"
                           + (" (converted earlier)" if converted["cached"] else f" in {converted['seconds']}s"))
        if url and not chunk["offset"]:
            await self._source_record(url, name, "document", source[:200])
        return {"success": True, "document": name, **chunk}

    async def _download_document(self, url: str) -> Tuple[str, bytes]:
        from app.core import documents
        from app.core.internet import _ssrf_ok

        ok, reason = _ssrf_ok(url)
        if not ok:
            raise ValueError(f"That address is not opened: {reason}")
        import httpx as _httpx

        async with _httpx.AsyncClient(timeout=_httpx.Timeout(60.0, connect=10.0), follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "JAI-Research/1.0"})
        final_ok, final_reason = _ssrf_ok(str(response.url))
        if not final_ok:
            raise ValueError(f"It redirected to an address that is not opened: {final_reason}")
        if response.status_code >= 400:
            raise ValueError(f"{url} answered {response.status_code}.")
        if len(response.content) > documents.MAX_BYTES:
            raise ValueError("The document is larger than 60 MB.")
        name = urllib.parse.urlparse(str(response.url)).path.rsplit("/", 1)[-1] or "document"
        kind = response.headers.get("content-type", "").split(";")[0].strip()
        extension = {"application/pdf": ".pdf", "text/html": ".html",
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                     "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx"}.get(kind, "")
        if extension and not name.lower().endswith(extension):
            name += extension
        return name, response.content

    async def use_browser(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """One action in this mission's own browser (browser-use, headless Chromium): open a page, read it, click,
        type, choose, scroll, press keys, go back, switch tabs or close. Public pages only; never passwords, cards
        or bank details."""
        from app.core.internet import browser

        target = str(args.get("url") or (args.get("text") if action != "type" else "") or args.get("index") or "")
        denied = await self._enforce("use_browser", content=f"{action} {target}"[:500])
        if denied:
            return denied
        session = str(self.task_id or self.workspace_id or "jai")[:80]
        inputs = {"action": action, **{k: args[k] for k in ("url", "index", "keys", "tab_id") if args.get(k) is not None}}
        if args.get("text") is not None:
            # What is typed is not kept in the record (it may be someone's details); only how long it was.
            inputs["text_chars"] = len(str(args["text"])) if action == "type" else None
            if action != "type":
                inputs["text"] = str(args["text"])[:80]
        try:
            answer = await browser.act(session, action, args)
        except browser.BrowserUnavailable as exc:
            await self._record("use_browser", inputs, False, str(exc)[:120])
            return {"success": False, "error": str(exc)}
        ok = bool(answer.get("ok"))
        if answer.get("boundary"):
            # A hard boundary JAI never crosses, even with approval: Richard types these himself.
            answer["next"] = ("Carry on with the rest of the mission. If the mission truly needs this field filled, "
                              "call create_boundary_report saying which page and field Richard must fill himself.")
        await self._record("use_browser", inputs, ok,
                           (f"{answer.get('title') or ''} {answer.get('url') or ''}".strip() or "done") if ok
                           else str(answer.get("reason") or answer.get("error") or "failed")[:120])
        if ok and action == "open" and answer.get("url"):
            await self._source_record(str(answer["url"]), str(answer.get("title") or ""), "browser", target[:200])
        return {**answer, "success": ok}

    async def knowledge(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """JAI's knowledge graph for this workspace (search, add a fact) and what Richard has told JAI (recall)."""
        from app.core import knowledge_service as ks

        query = str(args.get("query") or args.get("fact") or "")
        denied = await self._enforce(tool, content=query[:500])
        if denied:
            return denied
        if not self.workspace_id and tool != "recall_richard":
            return {"success": False, "error": "The knowledge graph is kept per workspace; this has none."}
        try:
            if tool == "knowledge_graph_search":
                facts = await ks.search_graph(query, [self.workspace_id], int(args.get("limit") or 10), timeout=15.0)
                out = {"facts": facts}
                summary = f"{len(facts)} fact(s)"
            elif tool == "knowledge_graph_add":
                queued = await ks.add_episode(self.workspace_id, str(args.get("title") or query[:80]), query,
                                              source=f"JAI agent ({getattr(self, 'agent_name', None) or 'mission'})",
                                              timeout=10.0)
                out = {"queued": True, "position": queued.get("position")}
                summary = "queued for the knowledge graph"
            else:
                told = await ks.recall(query, int(args.get("limit") or 8), timeout=15.0)
                out = {"memories": [m["memory"] for m in told]}
                summary = f"{len(told)} memory(ies)"
        except ks.KnowledgeUnavailable as exc:
            await self._record(tool, {"query": query[:200]}, False, str(exc)[:120])
            return {"success": False, "error": str(exc)}
        await self._record(tool, {"query": query[:200]}, True, summary)
        return {"success": True, **out}

    async def prompt_checks(self, suite: str, instructions: Optional[str] = None) -> Dict[str, Any]:
        """Check JAI's prompts with promptfoo: the voice's, or the given agent instructions against Richard's hard
        boundaries. About a cent, through JAI's gateway."""
        from app.core import evals

        denied = await self._enforce("run_prompt_checks", content=suite)
        if denied:
            return denied
        try:
            result = await evals.run(suite, instructions)
        except evals.ChecksUnavailable as exc:
            await self._record("run_prompt_checks", {"suite": suite}, False, str(exc)[:120])
            return {"success": False, "error": str(exc)}
        await self._record("run_prompt_checks", {"suite": suite}, result["all_passed"],
                           f"{result['passed']} passed, {result['failed']} failed")
        return {"success": True, **result}

    async def code_intel(self, tool: str, project: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Ask Serena (language servers) about the code in the workspace at this container path: a file's symbols,
        a symbol's definition and body, its references or implementations, or a file's diagnostics. Read-only."""
        from app.core.code import serena

        target = str(args.get("symbol") or args.get("path") or "")
        denied = await self._enforce(tool, content=target)
        if denied:
            return denied
        inputs = {k: args.get(k) for k in ("path", "symbol", "include_body") if args.get(k) not in (None, "")}
        try:
            answer = await serena.client().call(project, serena.TOOLS[tool], serena.arguments(tool, args))
        except serena.CodeUnavailable as exc:
            await self._record(tool, inputs, False, str(exc)[:120])
            return {"success": False, "error": str(exc)}
        limit = 30000
        await self._record(tool, inputs, True, f"{len(answer)} characters from the language server")
        return {"success": True, "answer": answer[:limit], "truncated": len(answer) > limit}

    async def read_mission_report(self, mission: Optional[str] = None) -> Dict[str, Any]:
        """Another mission's whole report in this workspace: the one whose id (or its first eight characters) is
        given, otherwise the latest one that has finished. Read-only."""
        denied = await self._enforce("read_mission_report", content=mission or "latest")
        if denied:
            return denied
        from sqlalchemy import select as _select

        from app.core.runtime import lifecycle
        from app.models.task import Task

        rows = (await self.db.execute(_select(Task).where(
            Task.workspace_id == self.workspace_id, Task.task_type == "command")
            .order_by(Task.created_at.desc()).limit(80))).scalars().all()
        rows = [t for t in rows if t.id != self.task_id]
        wanted = re.sub(r"[^0-9a-f]", "", (mission or "").lower())[:8]
        if wanted:
            found = next((t for t in rows if str(t.id).replace("-", "").startswith(wanted)), None)
        else:
            finished = lifecycle.TERMINAL - {lifecycle.CANCELLED}
            found = next((t for t in rows if lifecycle.normalise(t.status) in finished), None)
        if found is None:
            await self._record("read_mission_report", {"mission": mission}, False, "no such mission here")
            return {"success": False, "error": "No finished mission with that id in this workspace."}
        result = found.result if isinstance(found.result, dict) else {}
        report = str(result.get("response") or result.get("response_text") or found.error_message or "")
        await self._record("read_mission_report", {"mission": mission}, True,
                           f"read {str(found.id)[:8]} ({len(report)} characters)")
        return {"success": True, "task_id": str(found.id), "title": found.title, "status": found.status,
                "started": found.created_at.isoformat(timespec="minutes") if found.created_at else None,
                "report": report[:20000], "evidence": result.get("report"),
                "agents": result.get("selected_agents")}

    def _note_licence(self, licence_file: Optional[str], entry: str) -> None:
        if not licence_file:
            return
        found = fs_inspector.read_file(licence_file, max_bytes=400_000)
        existing = found.data.get("content", "") if found.accessible and found.exists else (
            "# Asset licences\n\nWhere every asset in this workspace came from and the terms it is used under.\n")
        fs_inspector.write_file(licence_file, existing + entry, overwrite=True)

    async def make_voiceover(self, host_path: str, text: str, voice: Optional[str] = None,
                             licence_file: Optional[str] = None, shown_as: Optional[str] = None) -> Dict[str, Any]:
        """Narration in JAI's natural voice (Chatterbox on the GPU), saved as a WAV inside the workspace."""
        denied = await self._enforce("make_voiceover", path=host_path, content=text)
        if denied:
            return denied
        from app.core.creative import voiceover

        try:
            spoken = await voiceover.speak(text, voice)
        except voiceover.VoiceoverUnavailable as exc:
            await self._record("make_voiceover", {"path": host_path}, False, str(exc)[:120])
            return {"success": False, "error": str(exc)}
        res = fs_inspector.write_bytes(host_path, spoken["wav"], overwrite=True)
        ok = res.accessible and res.exists
        if ok:
            from datetime import datetime, timezone

            self._note_licence(licence_file, (
                f"\n## {shown_as or host_path}\n- Narration made by JAI on "
                f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} with Chatterbox Turbo (MIT), voice "
                f"{spoken['voice']} (reference made with Kokoro, Apache-2.0), {spoken['seconds']}s\n"))
        await self._record("make_voiceover", {"path": host_path, "characters": len(text)}, ok,
                           f"{spoken['seconds']}s of narration" if ok else (res.reason or "blocked"))
        return {"success": ok, "path": host_path, "seconds": spoken["seconds"], "voice": spoken["voice"],
                "reason": None if ok else res.reason}

    async def make_video(self, host_path: str, topic: str, seconds: int = 40, aspect: str = "portrait",
                         audience: str = "", footage: str = "auto", licence_file: Optional[str] = None,
                         shown_as: Optional[str] = None) -> Dict[str, Any]:
        """A short video: JAI writes it, narrates it, makes or finds the footage, MoneyPrinterTurbo renders it; the
        MP4 and its script are saved inside the workspace. Nothing is published."""
        denied = await self._enforce("make_video", path=host_path, content=topic)
        if denied:
            return denied
        from app.core.creative import images, videos, voiceover

        seconds = max(15, min(int(seconds or 40), 120))
        stock = footage == "stock" or (footage == "auto" and await videos.stock_available())
        scenes = 0 if stock else max(3, min(8, seconds // 7))
        try:
            plan = await videos.plan_video(topic, seconds, audience, scenes)
            if not plan["script"]:
                raise videos.VideoUnavailable("No narration was written for that topic.")
            spoken = await voiceover.speak(plan["script"])
            stills = []
            if scenes:
                width, height = images.size_of(videos.ASPECT_SHAPES.get(aspect, "story"))
                for prompt in plan["image_prompts"]:
                    stills.append((await images.generate(prompt, width, height))["png"])
            mp4 = await videos.render({"subject": plan["title"], "script": plan["script"], "terms": plan["terms"],
                                       "aspect": aspect, "clip_seconds": max(3, int(spoken["seconds"] / max(1, scenes or 6))),
                                       "subtitles": True}, spoken["wav"], stills)
        except (videos.VideoUnavailable, voiceover.VoiceoverUnavailable, images.ImageUnavailable) as exc:
            await self._record("make_video", {"path": host_path, "topic": topic[:200]}, False, str(exc)[:120])
            return {"success": False, "error": str(exc)}
        res = fs_inspector.write_bytes(host_path, mp4, overwrite=True)
        ok = res.accessible and res.exists
        if ok:
            script_path = host_path.rsplit(".", 1)[0] + ".script.txt"
            fs_inspector.write_file(script_path, f"{plan['title']}\n\n{plan['script']}\n", overwrite=True)
            self._note_licence(licence_file, videos.licence_entry(shown_as or host_path, plan["title"],
                                                                  "pexels" if stock else "generated",
                                                                  spoken["seconds"]))
        await self._record("make_video", {"path": host_path, "topic": topic[:200]}, ok,
                           f"{spoken['seconds']}s video" if ok else (res.reason or "blocked"),
                           output={"bytes": len(mp4), "scenes": scenes})
        return {"success": ok, "path": host_path, "title": plan["title"], "script": plan["script"],
                "seconds": spoken["seconds"], "footage": "Pexels" if stock else f"{scenes} generated images",
                "reason": None if ok else res.reason}

    async def social_channels(self) -> Dict[str, Any]:
        denied = await self._enforce("social_channels", content="channels")
        if denied:
            return denied
        from app.core.creative import social

        try:
            found = await social.channels()
        except social.SocialUnavailable as exc:
            await self._record("social_channels", {}, False, str(exc)[:120])
            return {"success": False, "error": str(exc)}
        await self._record("social_channels", {}, True, f"{len(found)} channel(s) connected")
        return {"success": True, "channels": found}

    async def social_draft(self, text: str, channels: Optional[List[str]] = None,
                           media_host_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        """A post drafted in Postiz (never scheduled or published), with images or videos from the workspace."""
        denied = await self._enforce("social_draft", content=text)
        if denied:
            return denied
        from app.core.creative import social

        try:
            media = []
            for path in media_host_paths or []:
                found = fs_inspector.read_bytes(path)
                if not found.accessible:
                    return {"success": False, "error": f"{path}: {found.reason}"}
                name = path.replace("\\", "/").rsplit("/", 1)[-1]
                kind = "video/mp4" if name.lower().endswith(".mp4") else "image/png" if name.lower().endswith(
                    ".png") else "image/jpeg"
                media.append(await social.upload(name, found.data["bytes"], kind))
            drafted = await social.draft(text, channels, media)
        except social.SocialUnavailable as exc:
            await self._record("social_draft", {"channels": channels}, False, str(exc)[:120])
            return {"success": False, "error": str(exc)}
        await self._record("social_draft", {"channels": drafted["channels"], "characters": len(text)}, True,
                           f"draft for {', '.join(drafted['channels'])}")
        return {"success": True, **drafted}

    async def generate_image(self, host_path: str, prompt: str, width: int = 1024, height: int = 1024,
                             licence_file: Optional[str] = None, seed: Optional[int] = None,
                             shown_as: Optional[str] = None) -> Dict[str, Any]:
        """Make an image on the GPU (JAI's ComfyUI, FLUX.1-schnell) and save it at host_path inside the workspace,
        recording its model, licence and prompt in the workspace's ASSET_LICENCES.md (licence_file)."""
        denied = await self._enforce("generate_image", path=host_path, content=prompt)
        if denied:
            return denied
        from app.core.creative import images

        try:
            made = await images.generate(prompt, width, height, seed)
        except images.ImageUnavailable as exc:
            await self._record("generate_image", {"path": host_path, "prompt": prompt[:200]}, False, str(exc)[:120])
            return {"success": False, "error": str(exc)}
        res = fs_inspector.write_bytes(host_path, made["png"], overwrite=True)
        ok = res.accessible and res.exists
        if ok and licence_file:
            found = fs_inspector.read_file(licence_file, max_bytes=400_000)
            existing = found.data.get("content", "") if found.accessible and found.exists else (
                "# Asset licences\n\nWhere every asset in this workspace came from and the terms it is used under.\n")
            fs_inspector.write_file(licence_file, existing + images.licence_entry(
                shown_as or host_path, prompt, made["seed"], made["width"], made["height"]), overwrite=True)
        await self._record("generate_image", {"path": host_path, "prompt": prompt[:200]}, ok,
                           f"{made['width']}x{made['height']} in {made['seconds']}s" if ok else (res.reason or "blocked"),
                           output={"bytes": len(made["png"]), "seconds": made["seconds"]})
        return {"success": ok, "path": host_path, "container_path": res.container_path, "width": made["width"],
                "height": made["height"], "seed": made["seed"], "seconds": made["seconds"], "model": images.MODEL,
                "licence": images.LICENCE, "reason": None if ok else res.reason}

    async def fetch_url(self, url: str, render: Optional[bool] = None) -> Dict[str, Any]:
        denied = await self._enforce("fetch_url", content=url)
        if denied:
            return denied
        from app.core.internet import fetch_url as _fetch
        res = await _fetch(url, render)
        ok = res.get("ok", False)
        await self._record("fetch_url", {"url": url}, ok,
                           f"{res.get('status', '')} {res.get('title') or res.get('reason') or ''}"[:120],
                           output={"status": res.get("status"), "bytes": res.get("bytes")})
        if ok:
            await self._source_record(res.get("url", url), res.get("title", ""), "web_page",
                                      (res.get("text") or "")[:200])
        return res

    async def check_package_registry(self, name: str, ecosystem: str = "npm") -> Dict[str, Any]:
        denied = await self._enforce("check_package_registry")
        if denied:
            return denied
        from app.core.internet import check_package_registry as _chk
        res = await _chk(name, ecosystem)
        await self._record("check_package_registry", {"name": name, "ecosystem": ecosystem},
                           res.get("ok", False),
                           f"{name}@{res.get('latest')} licence={res.get('license')}"[:120])
        if res.get("ok"):
            await self._source_record(res.get("homepage") or f"registry:{ecosystem}/{name}",
                                      f"{name} {res.get('latest')}", "package_registry",
                                      f"licence={res.get('license')}")
        return res

    async def check_cve(self, name: str, ecosystem: str = "npm",
                        version: Optional[str] = None) -> Dict[str, Any]:
        denied = await self._enforce("check_cve")
        if denied:
            return denied
        from app.core.internet import check_cve as _cve
        res = await _cve(name, ecosystem, version)
        await self._record("check_cve", {"name": name, "ecosystem": ecosystem},
                           res.get("ok", False),
                           f"{name}: {res.get('risk')} ({res.get('vulnerabilities')} vulns)"[:120])
        if res.get("ok"):
            await self._source_record("https://osv.dev", f"OSV: {name}", "cve_database",
                                      f"risk={res.get('risk')} vulns={res.get('vulnerabilities')}")
        return res

    async def asset_licence_check(self, query: str, source: str) -> Dict[str, Any]:
        denied = await self._enforce("asset_licence_check")
        if denied:
            return denied
        from app.core.internet import asset_licence_dry_run
        res = asset_licence_dry_run(query, source)
        await self._record("asset_licence_check", {"query": query, "source": source},
                           res.get("ok", False), res.get("note", "")[:120])
        if res.get("approved_source"):
            await self._source_record(f"asset:{source}", query, "asset",
                                      "approved source (dry-run, not downloaded)")
        return res
