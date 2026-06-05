"""
JARV Backend - ToolRun logging.

Writes a real ToolRun record for a tool execution when a DB session and an
executing agent are available. Input/output are redacted before persistence.

This never fabricates rows and never crashes tool execution: if a session or
agent id is missing, or any DB error occurs, it returns False and the caller
marks tool_run_logged=false. It does not create dummy sessions.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select

from app.core.security import redact_secrets

logger = logging.getLogger(__name__)


async def write_tool_run(
    session: Any,
    *,
    tool_name: str,
    tool_group: str,
    description: str,
    input_schema_json: Dict[str, Any],
    output_schema_json: Dict[str, Any],
    minimum_authority_level: int,
    requires_approval: bool,
    status: str,
    success: Optional[bool],
    input_data: Optional[Dict[str, Any]],
    output_data: Optional[Dict[str, Any]],
    error_message: Optional[str],
    started_at: datetime,
    completed_at: Optional[datetime],
    authority_level_used: int,
    agent_id: Optional[UUID],
    session_id: Optional[UUID] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> bool:
    """Persist a ToolRun. Returns True if written, False otherwise (best-effort).

    Requires a real DB session AND an executing agent_id (ToolRun.agent_id is a
    non-null FK). When either is missing it returns False rather than inventing
    a row.
    """
    if session is None or agent_id is None:
        return False

    try:
        from app.models.tool_system import Tool, ToolRun

        # Get-or-create the catalog Tool row for this tool name (a real catalog
        # entry, not a fake row).
        result = await session.execute(select(Tool).where(Tool.tool_name == tool_name))
        tool = result.scalar_one_or_none()
        if tool is None:
            tool = Tool(
                tool_name=tool_name,
                tool_group=tool_group or "general",
                tool_version="1.0",
                description=description or tool_name,
                config_schema={},
                input_schema=input_schema_json or {},
                output_schema=output_schema_json or {},
                minimum_authority_level=int(minimum_authority_level),
                requires_approval=bool(requires_approval),
                is_active=True,
                tags=[],
            )
            session.add(tool)
            await session.flush()  # assign tool.id

        duration_ms: Optional[int] = None
        if completed_at is not None:
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        run = ToolRun(
            tool_id=tool.id,
            agent_id=agent_id,
            session_id=session_id,
            input_params=redact_secrets(input_data or {}),
            output_result=redact_secrets(output_data) if output_data is not None else None,
            status=status,
            success=success,
            error_message=(error_message[:2000] if error_message else None),
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            authority_level_used=int(authority_level_used),
            required_approval=bool(requires_approval),
            meta_data=redact_secrets(meta) if meta else None,
        )
        session.add(run)
        await session.commit()
        return True
    except Exception as e:  # noqa: BLE001 - logging must never break execution
        logger.warning(f"ToolRun logging failed for {tool_name}: {e}")
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False
