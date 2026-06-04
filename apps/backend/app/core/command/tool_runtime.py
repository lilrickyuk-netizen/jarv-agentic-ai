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

from app.core.jarv_memory import memory_service
from app.core.workspaces import fs_inspector
from app.models.company_operations import LiveOperationsFeedItem
from app.models.operations import AuditLog

logger = logging.getLogger(__name__)

# Authority level required per tool (read-only inspection = Level 1).
_TOOL_AUTHORITY = {
    "list_files": 1,
    "read_file": 1,
    "search_files": 1,
    "scan_workspace": 1,
    "memory_add": 1,
    "memory_search": 1,
    "create_live_operations_feed_item": 1,
    "create_boundary_report": 1,
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
