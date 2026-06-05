"""
JARV Backend - Audit Logging System

Comprehensive audit logging for all agent actions and system events.
Every agent execution is logged to the AuditLog database table.
"""
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.operations import AuditLog
from app.core.database import get_db
from app.core.security import redact_secrets

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Audit logger for recording all agent actions and system events.

    Logs are written to the AuditLog database table for complete traceability.
    Every agent execution, tool use, and significant system action is recorded.
    """

    @staticmethod
    async def log_agent_execution(
        session: AsyncSession,
        agent_name: str,
        action: str,
        result: str,
        user_id: Optional[UUID] = None,
        workspace_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        details: Optional[Dict[str, Any]] = None,
        severity: str = "info",
    ) -> AuditLog:
        """
        Log agent execution to audit trail.

        Args:
            session: Database session
            agent_name: Name of agent
            action: Action performed
            result: Result of action (success/failure)
            user_id: User who triggered action
            workspace_id: Workspace context
            agent_id: Agent instance ID
            task_id: Task being executed
            session_id: Execution session ID
            details: Additional details as JSON
            severity: Log severity (info, warning, error, critical)

        Returns:
            Created audit log entry
        """
        try:
            audit_entry = AuditLog(
                user_id=user_id,
                actor_type="agent",
                action=f"agent.{agent_name}.{action}",
                action_category="agent",
                description=f"Agent '{agent_name}' {action} ({result})",
                target_type="agent",
                target_id=str(agent_id) if agent_id else None,
                success=str(result).lower() in ("success", "completed", "started", "ok"),
                ip_address=None,  # Will be set by API layer if available
                user_agent=None,  # Will be set by API layer if available
                # Redact any secret-bearing values (tool input/output, etc.)
                # before they are persisted to the audit trail.
                meta_data=redact_secrets({
                    "agent_name": agent_name,
                    "action": action,
                    "result": result,
                    "severity": severity,
                    "workspace_id": str(workspace_id) if workspace_id else None,
                    "task_id": str(task_id) if task_id else None,
                    "session_id": str(session_id) if session_id else None,
                    **(details or {}),
                }),
            )

            session.add(audit_entry)
            await session.commit()
            await session.refresh(audit_entry)

            logger.debug(
                f"Audit log created: {agent_name}.{action}",
                extra={
                    "audit_id": str(audit_entry.id),
                    "agent_name": agent_name,
                    "action": action,
                    "result": result,
                }
            )

            return audit_entry

        except Exception as e:
            logger.error(
                f"Failed to create audit log: {e}",
                exc_info=True,
                extra={
                    "agent_name": agent_name,
                    "action": action,
                }
            )
            await session.rollback()
            raise

    @staticmethod
    async def log_agent_start(
        session: AsyncSession,
        agent_name: str,
        user_id: Optional[UUID] = None,
        workspace_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        """
        Log agent execution start.

        Args:
            session: Database session
            agent_name: Name of agent
            user_id: User ID
            workspace_id: Workspace ID
            agent_id: Agent instance ID
            task_id: Task ID
            session_id: Session ID
            input_data: Agent input data

        Returns:
            Audit log entry
        """
        return await AuditLogger.log_agent_execution(
            session=session,
            agent_name=agent_name,
            action="start",
            result="started",
            user_id=user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            task_id=task_id,
            session_id=session_id,
            details={"input": input_data} if input_data else None,
            severity="info",
        )

    @staticmethod
    async def log_agent_complete(
        session: AsyncSession,
        agent_name: str,
        result: str,
        execution_time: float,
        tokens_used: Dict[str, int],
        cost_estimate: float,
        user_id: Optional[UUID] = None,
        workspace_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        output_data: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        """
        Log agent execution completion.

        Args:
            session: Database session
            agent_name: Name of agent
            result: Execution result (success/failure)
            execution_time: Execution time in seconds
            tokens_used: Token usage dict
            cost_estimate: Cost in USD
            user_id: User ID
            workspace_id: Workspace ID
            agent_id: Agent instance ID
            task_id: Task ID
            session_id: Session ID
            output_data: Agent output data

        Returns:
            Audit log entry
        """
        severity = "info" if result == "success" else "error"

        return await AuditLogger.log_agent_execution(
            session=session,
            agent_name=agent_name,
            action="complete",
            result=result,
            user_id=user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            task_id=task_id,
            session_id=session_id,
            details={
                "execution_time": execution_time,
                "tokens_used": tokens_used,
                "cost_estimate": cost_estimate,
                "output": output_data,
            },
            severity=severity,
        )

    @staticmethod
    async def log_agent_error(
        session: AsyncSession,
        agent_name: str,
        error_message: str,
        error_type: str,
        user_id: Optional[UUID] = None,
        workspace_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        stack_trace: Optional[str] = None,
    ) -> AuditLog:
        """
        Log agent execution error.

        Args:
            session: Database session
            agent_name: Name of agent
            error_message: Error message
            error_type: Error type/class
            user_id: User ID
            workspace_id: Workspace ID
            agent_id: Agent instance ID
            task_id: Task ID
            session_id: Session ID
            stack_trace: Error stack trace

        Returns:
            Audit log entry
        """
        return await AuditLogger.log_agent_execution(
            session=session,
            agent_name=agent_name,
            action="error",
            result="failed",
            user_id=user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            task_id=task_id,
            session_id=session_id,
            details={
                "error_message": error_message,
                "error_type": error_type,
                "stack_trace": stack_trace,
            },
            severity="error",
        )

    @staticmethod
    async def log_tool_use(
        session: AsyncSession,
        agent_name: str,
        tool_name: str,
        tool_result: str,
        user_id: Optional[UUID] = None,
        workspace_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        tool_input: Optional[Dict[str, Any]] = None,
        tool_output: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        """
        Log tool usage by agent.

        Args:
            session: Database session
            agent_name: Name of agent using tool
            tool_name: Name of tool used
            tool_result: Result of tool execution
            user_id: User ID
            workspace_id: Workspace ID
            agent_id: Agent instance ID
            task_id: Task ID
            session_id: Session ID
            tool_input: Tool input data
            tool_output: Tool output data

        Returns:
            Audit log entry
        """
        severity = "info" if tool_result == "success" else "warning"

        return await AuditLogger.log_agent_execution(
            session=session,
            agent_name=agent_name,
            action=f"tool.{tool_name}",
            result=tool_result,
            user_id=user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            task_id=task_id,
            session_id=session_id,
            details={
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": tool_output,
            },
            severity=severity,
        )

    @staticmethod
    async def log_system_event(
        session: AsyncSession,
        action: str,
        result: str,
        resource_type: str,
        resource_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        details: Optional[Dict[str, Any]] = None,
        severity: str = "info",
    ) -> AuditLog:
        """
        Log general system event.

        Args:
            session: Database session
            action: Action performed
            result: Result of action
            resource_type: Type of resource affected
            resource_id: ID of resource
            user_id: User who triggered action
            details: Additional details
            severity: Log severity

        Returns:
            Audit log entry
        """
        try:
            audit_entry = AuditLog(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details={
                    "result": result,
                    **(details or {}),
                },
                severity=severity,
            )

            session.add(audit_entry)
            await session.commit()
            await session.refresh(audit_entry)

            return audit_entry

        except Exception as e:
            logger.error(f"Failed to create audit log: {e}", exc_info=True)
            await session.rollback()
            raise

    @staticmethod
    async def query_logs(
        session: AsyncSession,
        user_id: Optional[UUID] = None,
        workspace_id: Optional[UUID] = None,
        agent_name: Optional[str] = None,
        action: Optional[str] = None,
        severity: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        """
        Query audit logs with filters.

        Args:
            session: Database session
            user_id: Filter by user
            workspace_id: Filter by workspace
            agent_name: Filter by agent name
            action: Filter by action
            severity: Filter by severity
            resource_type: Filter by resource type
            start_date: Filter by start date
            end_date: Filter by end date
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of audit log entries
        """
        query = select(AuditLog).order_by(desc(AuditLog.created_at))

        # Apply filters
        if user_id:
            query = query.where(AuditLog.user_id == user_id)

        if workspace_id:
            # Workspace ID is in details JSON
            query = query.where(
                AuditLog.details["workspace_id"].astext == str(workspace_id)
            )

        if agent_name:
            query = query.where(
                AuditLog.details["agent_name"].astext == agent_name
            )

        if action:
            query = query.where(AuditLog.action == action)

        if severity:
            query = query.where(AuditLog.severity == severity)

        if resource_type:
            query = query.where(AuditLog.resource_type == resource_type)

        if start_date:
            query = query.where(AuditLog.created_at >= start_date)

        if end_date:
            query = query.where(AuditLog.created_at <= end_date)

        # Apply pagination
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        return list(result.scalars().all())


# Convenience functions for common audit operations

async def audit_agent_start(
    agent_name: str,
    user_id: Optional[UUID] = None,
    workspace_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    session_id: Optional[UUID] = None,
    input_data: Optional[Dict[str, Any]] = None,
) -> Optional[AuditLog]:
    """
    Convenience function to log agent start.

    Gets database session and logs agent execution start.
    """
    try:
        async for session in get_db():
            return await AuditLogger.log_agent_start(
                session=session,
                agent_name=agent_name,
                user_id=user_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                task_id=task_id,
                session_id=session_id,
                input_data=input_data,
            )
    except Exception as e:
        logger.error(f"Failed to audit agent start: {e}", exc_info=True)
        return None


async def audit_agent_complete(
    agent_name: str,
    result: str,
    execution_time: float,
    tokens_used: Dict[str, int],
    cost_estimate: float,
    user_id: Optional[UUID] = None,
    workspace_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    session_id: Optional[UUID] = None,
    output_data: Optional[Dict[str, Any]] = None,
) -> Optional[AuditLog]:
    """
    Convenience function to log agent completion.

    Gets database session and logs agent execution completion.
    """
    try:
        async for session in get_db():
            return await AuditLogger.log_agent_complete(
                session=session,
                agent_name=agent_name,
                result=result,
                execution_time=execution_time,
                tokens_used=tokens_used,
                cost_estimate=cost_estimate,
                user_id=user_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                task_id=task_id,
                session_id=session_id,
                output_data=output_data,
            )
    except Exception as e:
        logger.error(f"Failed to audit agent completion: {e}", exc_info=True)
        return None


async def audit_agent_error(
    agent_name: str,
    error_message: str,
    error_type: str,
    user_id: Optional[UUID] = None,
    workspace_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    session_id: Optional[UUID] = None,
    stack_trace: Optional[str] = None,
) -> Optional[AuditLog]:
    """
    Convenience function to log agent error.

    Gets database session and logs agent execution error.
    """
    try:
        async for session in get_db():
            return await AuditLogger.log_agent_error(
                session=session,
                agent_name=agent_name,
                error_message=error_message,
                error_type=error_type,
                user_id=user_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                task_id=task_id,
                session_id=session_id,
                stack_trace=stack_trace,
            )
    except Exception as e:
        logger.error(f"Failed to audit agent error: {e}", exc_info=True)
        return None
