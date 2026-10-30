"""
JARV Backend - Owner scoping for API reads and writes (Repair 15a)

Every record the dashboard reads belongs to a workspace, or to an agent
session that belongs to a workspace and an operator. These helpers turn the
signed-in operator into SQL conditions so a query only ever sees that
operator's records, and 404 anything else (an id from someone else's
workspace looks exactly like an id that does not exist).
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


def as_uuid(user_id: Any) -> UUID:
    return user_id if isinstance(user_id, UUID) else UUID(str(user_id))


def owned_workspaces(user_id: Any):
    """SELECT of the ids of the workspaces the operator owns (usable in .in_())."""
    from app.models.workspace import Workspace

    return select(Workspace.id).where(Workspace.owner_id == as_uuid(user_id))


def owned_sessions(user_id: Any):
    """SELECT of the agent sessions the operator started or that run in their workspaces."""
    from app.models.session import AgentSession

    uid = as_uuid(user_id)
    return select(AgentSession.id).where(or_(AgentSession.user_id == uid,
                                             AgentSession.workspace_id.in_(owned_workspaces(uid))))


def owned_agents(user_id: Any):
    from app.models.agent import Agent

    return select(Agent.id).where(Agent.workspace_id.in_(owned_workspaces(user_id)))


def visible(model: Any, user_id: Any):
    """The condition under which a row of ``model`` belongs to the operator."""
    uid = as_uuid(user_id)
    clauses = []
    if hasattr(model, "workspace_id"):
        clauses.append(model.workspace_id.in_(owned_workspaces(uid)))
    if hasattr(model, "session_id"):
        clauses.append(model.session_id.in_(owned_sessions(uid)))
    if hasattr(model, "agent_id") and hasattr(model, "workspace_id"):
        clauses.append(model.workspace_id.is_(None) & model.agent_id.in_(owned_agents(uid)))
    if hasattr(model, "user_id"):
        clauses.append(model.user_id == uid)
    if hasattr(model, "owner_id"):
        clauses.append(model.owner_id == uid)
    return or_(*clauses) if clauses else false()


async def require_workspace(db: AsyncSession, user_id: Any, workspace_id: Optional[UUID]) -> Optional[UUID]:
    """The workspace id when the operator owns it; 404 otherwise. None passes through (no filter asked)."""
    if workspace_id is None:
        return None
    from app.models.workspace import Workspace

    found = (await db.execute(select(Workspace.id).where(Workspace.id == workspace_id,
                                                         Workspace.owner_id == as_uuid(user_id)))).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return found
