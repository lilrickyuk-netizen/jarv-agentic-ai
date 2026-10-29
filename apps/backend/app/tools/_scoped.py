"""
JARV Backend - Base for database-backed, workspace-scoped registry tools

Company operations, workspace lifecycle and experience tools all act on
persisted records inside the calling context's workspace, for that
workspace's owner. ``ScopedTool`` supplies the ToolBase properties, the
workspace/owner lookup and uniform error handling; each tool implements
``act`` and returns (result data, one-line summary).

Authority checks, the central permission gate, approval gating, the ToolRun
record and the audit entry all run in ``ToolBase.execute`` before ``run``.
"""
from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, Type
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.agents.base import AuthorityLevel
from app.core.tools import ToolBase, ToolContext, ToolResult


class ScopedOutput(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)


class ScopedTool(ToolBase):
    _name = ""
    _description = ""
    _category = ""
    _input: Type[BaseModel] = BaseModel
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS
    _approval = False

    name = property(lambda self: self._name)
    description = property(lambda self: self._description)
    input_schema = property(lambda self: self._input)
    output_schema = property(lambda self: ScopedOutput)
    required_authority_level = property(lambda self: self._authority)
    requires_approval = property(lambda self: self._approval)
    category = property(lambda self: self._category)

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if context.db_session is None or context.workspace_id is None:
            return self.create_result(success=False,
                                      error_message=f"{self._name} needs a workspace and a database session.")
        try:
            data = self._input(**(input_data or {})).model_dump()
            result, text = await self.act(context.db_session, context, await workspace_owner(context), data)
        except (LookupError, PermissionError, ValueError) as exc:
            return self.create_result(success=False, error_message=str(exc))
        return self.create_result(success=True, result_data=result, output_text=text)

    @abstractmethod
    async def act(self, db, context: ToolContext, owner: UUID, data: Dict[str, Any]):
        """Do the tool's work; return (result data, one-line summary)."""


async def workspace_owner(context: ToolContext) -> UUID:
    from sqlalchemy import select

    from app.models.workspace import Workspace

    owner = (await context.db_session.execute(select(Workspace.owner_id).where(
        Workspace.id == context.workspace_id))).scalar_one_or_none()
    if owner is None:
        raise LookupError("Workspace not found")
    return owner


def as_uuid(value: Any, what: str = "id") -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"'{value}' is not a valid {what}") from None
