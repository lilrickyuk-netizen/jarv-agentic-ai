"""
JARV Backend - Tool Execution Runtime

Confirmed tool-execution layer for the command pipeline. Agents act through
real, named tools (not prose). Every call is:

  * executed for real (filesystem read-only inspection, memory persistence, etc.),
  * authority-checked,
  * logged to the audit trail and the Live Operations Feed (item_type="tool"),
  * recorded on the owning task (task.result["tool_calls"]) so it shows in task
    detail.

This wraps the real implementations (fs_inspector, MemoryService, the boundary/
feed writers) behind a stable tool surface so the dashboard can prove that JARV
actually acted, with which tool, on which inputs, and with what result.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

import asyncio

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
    "check_package_registry": 1,
    "check_cve": 1,
    "asset_licence_check": 1,
}


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
        coercion mirrors app.core.auth.get_current_user so the same operator
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

    async def read_file(self, path: str) -> Dict[str, Any]:
        denied = await self._enforce("read_file", path=path)
        if denied:
            return denied
        res = fs_inspector.read_file(path)
        ok = res.accessible and res.exists
        redacted = res.data.get("redacted") if ok else None
        await self._record(
            "read_file", {"path": path}, ok,
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
                         overwrite: bool = False) -> Dict[str, Any]:
        denied = await self._enforce("write_file", path=host_path, content=content)
        if denied:
            return denied
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
                agent_id = await memory_service._agent_id(self.db)
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
        return {"success": ok, "data": res.data, "reason": res.reason}

    # ----- code/command execution (read-only safe; dangerous blocked) -----

    async def run_safe_readonly_command(self, command: str,
                                        cwd_host: Optional[str] = None) -> Dict[str, Any]:
        return await self.run_command(command, cwd_host, allow_build=False)

    async def run_command(self, command: str, cwd_host: Optional[str] = None,
                          allow_build: bool = True, allow_install: bool = True,
                          timeout: int = 120) -> Dict[str, Any]:
        """
        Execute a command with classification-based gating:
          safe -> always; build -> allowed when allow_build (Level 3, in workspace);
          install -> trusted local package install, allowed when allow_install AND
                     run inside an approved workspace (PackageInstallPolicy);
          dangerous -> blocked; risky -> requires approval.
        Captures stdout/stderr/exit, times out, persists a CommandRun.
        """
        cls = fs_inspector.classify_command(command)
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
        denied = await self._enforce("run_command", command=command,
                                     allow_build=allow_build,
                                     allow_install=allow_install)
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

        if cls == "install":
            if not cwd:
                await self._record("run_command", {"command": command}, False,
                                   "blocked: install must run inside an approved workspace")
                await self._persist_command_run(command, cwd_host, None, "", "blocked", False,
                                                dangerous=True)
                return {"success": False, "blocked": True, "classification": cls,
                        "reason": "Package install blocked: not inside an approved workspace."}
            timeout = max(timeout, 420)  # installs can take minutes

        # safe/build/install: execute with timeout, capture stdout/stderr/exit code.
        stdout = stderr = ""
        exit_code = -1
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
            stdout = out.decode("utf-8", errors="replace")[:8000]
            stderr = err.decode("utf-8", errors="replace")[:4000]
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            await self._record("run_command", {"command": command}, False,
                               f"timed out after {timeout}s")
            await self._persist_command_run(command, cwd_host, None, "timeout", "timeout", False)
            return {"success": False, "reason": f"Command timed out after {timeout}s."}
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
            agent_id = await memory_service._agent_id(self.db)
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
        """Persist a web source record (memory_type=source) so claims are traceable."""
        try:
            await memory_service.add(
                self.db, content=f"[source:{source_type}] {title or url} | {url} | {summary}"[:600],
                memory_type="source", workspace_id=self.workspace_id, task_id=self.task_id,
                importance=0.55, meta={"url": url, "source_type": source_type, "title": title})
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"source record failed: {exc}")

    async def fetch_url(self, url: str) -> Dict[str, Any]:
        denied = await self._enforce("fetch_url", content=url)
        if denied:
            return denied
        from app.core.internet import fetch_url as _fetch
        res = await _fetch(url)
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
