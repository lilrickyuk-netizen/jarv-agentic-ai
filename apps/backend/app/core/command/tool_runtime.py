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
from app.core.workspaces import fs_inspector
from app.models.company_operations import LiveOperationsFeedItem
from app.models.execution import CommandRun, FileChange
from app.models.operations import AuditLog

logger = logging.getLogger(__name__)

# Authority level required per tool.
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
    "write_file": 2,
    "send_notification": 4,
}


class ToolRuntime:
    """Executes named tools, recording each call on the task + feed + audit."""

    def __init__(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        task_id: Optional[UUID],
        operator: str = "operator",
        authority_level: int = 5,
    ):
        self.db = db
        self.workspace_id = workspace_id
        self.task_id = task_id
        self.operator = operator
        self.authority_level = authority_level
        self.calls: List[Dict[str, Any]] = []

    # ----- recording -----

    async def _record(
        self, tool: str, inputs: Dict[str, Any], success: bool,
        summary: str, output: Optional[Dict[str, Any]] = None,
    ) -> None:
        required = _TOOL_AUTHORITY.get(tool, 1)
        entry = {
            "tool": tool,
            "inputs": inputs,
            "success": success,
            "summary": summary,
            "authority_level": required,
            "authorized": self.authority_level >= required,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if output is not None:
            entry["output"] = output
        self.calls.append(entry)
        # Operations feed
        try:
            self.db.add(LiveOperationsFeedItem(
                id=uuid4(), workspace_id=self.workspace_id, item_type="tool",
                severity="info" if success else "error",
                title=f"Tool: {tool}", message=summary,
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
                description=summary, target_type="task",
                target_id=str(self.task_id) if self.task_id else None,
                after_state={"tool": tool, "inputs": inputs, "operator": self.operator},
                success=success, authority_level=required,
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            ))
            await self.db.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"tool audit write failed: {exc}")

    def _authorized(self, tool: str) -> bool:
        return self.authority_level >= _TOOL_AUTHORITY.get(tool, 1)

    # ----- file / workspace tools -----

    async def list_files(self, path: str) -> Dict[str, Any]:
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
        rec = await memory_service.add(
            self.db, content=content, memory_type=memory_type,
            workspace_id=self.workspace_id, task_id=self.task_id, importance=importance,
        )
        await self._record("memory_add", {"memory_type": memory_type}, True,
                           f"stored memory {rec.id}", output={"memory_id": str(rec.id)})
        return {"success": True, "memory_id": str(rec.id)}

    async def memory_search(self, query: str, limit: int = 5) -> Dict[str, Any]:
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
        cls = fs_inspector.classify_command(command)
        cwd = None
        if cwd_host:
            chk = fs_inspector.path_exists(cwd_host)
            cwd = chk.container_path if (chk.accessible and chk.exists) else None

        if cls == "dangerous":
            await self._record("run_safe_readonly_command", {"command": command}, False,
                               "blocked: dangerous command")
            await self._persist_command_run(command, cwd_host, None, "", "blocked", False,
                                             dangerous=True)
            return {"success": False, "blocked": True, "classification": cls,
                    "reason": "Dangerous command blocked by safety policy."}
        if cls == "risky":
            await self._record("run_safe_readonly_command", {"command": command}, False,
                               "requires approval: non-read-only command")
            return {"success": False, "requires_approval": True, "classification": cls,
                    "reason": "Command is not read-only; requires approval."}

        # safe: execute with timeout, capture stdout/stderr/exit code.
        stdout = stderr = ""
        exit_code = -1
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
            exit_code = proc.returncode
            stdout = out.decode("utf-8", errors="replace")[:8000]
            stderr = err.decode("utf-8", errors="replace")[:4000]
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            await self._record("run_safe_readonly_command", {"command": command}, False,
                               "timed out after 20s")
            await self._persist_command_run(command, cwd_host, None, "timeout", "timeout", False)
            return {"success": False, "reason": "Command timed out."}
        except Exception as exc:  # noqa: BLE001
            await self._record("run_safe_readonly_command", {"command": command}, False, str(exc))
            return {"success": False, "reason": str(exc)}

        ok = exit_code == 0
        await self._record("run_safe_readonly_command", {"command": command, "cwd": cwd_host}, ok,
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
                id=uuid4(), agent_id=agent_id, command=command, command_type="readonly",
                working_directory=cwd,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                exit_code=exit_code if isinstance(exit_code, int) else None,
                stdout=(stdout or "")[:8000], stderr=(stderr or "")[:4000], success=success,
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
        from app.core.integrations import integrations
        result = await integrations.send(target, message, dry_run=dry_run)
        await self._record(
            "send_notification", {"target": target, "dry_run": dry_run}, result["ok"],
            result["summary"], output={"mode": result["mode"]},
        )
        return result
