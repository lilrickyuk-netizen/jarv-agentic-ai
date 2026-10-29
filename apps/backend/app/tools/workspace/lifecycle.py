"""
JARV Backend - Workspace lifecycle tools (Repair 12e-3c)

create_workspace, import_folder_workspace, import_repository_workspace,
import_document_pack_workspace, import_live_platform_workspace,
generate_task_plan, update_roadmap, update_launch_checklist,
update_workspace_rules, archive_workspace, delete_workspace_with_boundary.

All act for the calling workspace's owner through
app.core.workspaces.lifecycle: folders stay inside the approved workspace
root, new workspaces never get more authority than the calling workspace,
changes to protected rules (safety, boundary, authority, security, logging,
audit, verification, secrets) pause for Richard's approval, and deleting a
workspace removes JARV's records only, never files.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.agents.base import AuthorityLevel
from app.core.tools import ToolContext, ToolResult
from app.core.workspaces.lifecycle import workspace_lifecycle
from app.tools._scoped import ScopedTool, workspace_owner


class _LifecycleTool(ScopedTool):
    _category = "workspace"
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS


async def _ceiling(db, context: ToolContext) -> int:
    from sqlalchemy import select

    from app.models.workspace import Workspace

    level = (await db.execute(select(Workspace.authority_level).where(Workspace.id == context.workspace_id))
             ).scalar_one_or_none()
    return int(level or 1)


async def _target(db, context: ToolContext, owner: UUID, workspace_id: Optional[str]):
    return await workspace_lifecycle.owned(db, workspace_id or context.workspace_id, owner)


def _view(ws) -> Dict[str, Any]:
    cfg = ws.config or {}
    return {"workspace_id": str(ws.id), "name": ws.name, "slug": ws.slug, "type": ws.workspace_type,
            "authority_level": ws.authority_level, "is_active": ws.is_active, "is_archived": ws.is_archived,
            "root_path": cfg.get("root_path"), "live_url": cfg.get("live_url")}


# ----- inputs ------------------------------------------------------------------------------

class _Create(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    workspace_type: str = "project"
    path: Optional[str] = Field(None, description="Existing folder inside the approved root to link")
    authority_level: Optional[int] = Field(None, ge=1, le=7, description="Capped at the calling workspace's level")
    company_mode: bool = False


class _ImportFolder(BaseModel):
    path: str = Field(..., description="Existing folder inside the approved root")
    name: Optional[str] = None
    description: Optional[str] = None
    authority_level: Optional[int] = Field(None, ge=1, le=7)


class _ImportRepo(BaseModel):
    url: str = Field(..., description="https URL of a public git repository")
    folder_name: str = Field(..., description="New folder to clone into")
    branch: Optional[str] = None
    parent_folder: Optional[str] = Field(None, description="Inside the approved root; defaults to the root")
    name: Optional[str] = None
    authority_level: Optional[int] = Field(None, ge=1, le=7)


class _Document(BaseModel):
    filename: str
    content: str


class _ImportDocs(BaseModel):
    folder_name: str
    documents: List[_Document] = Field(..., min_length=1)
    parent_folder: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    authority_level: Optional[int] = Field(None, ge=1, le=7)


class _ImportLive(BaseModel):
    name: str = Field(..., min_length=2)
    url: str
    health_path: Optional[str] = Field(None, description="e.g. /health")
    path: Optional[str] = Field(None, description="Optional source folder inside the approved root")
    description: Optional[str] = None
    authority_level: Optional[int] = Field(None, ge=1, le=7)


class _Plan(BaseModel):
    goal: str = Field(..., min_length=5)
    steps: Optional[List[Any]] = Field(None, description="Strings or {title, description, agent, priority}; "
                                                         "omitted: planned by the model or from the project files")
    workspace_id: Optional[str] = None


class _Roadmap(BaseModel):
    milestones: List[Any] = Field(..., min_length=1, description="{title, due, status} by title; {title, remove: true}")
    workspace_id: Optional[str] = None


class _Checklist(BaseModel):
    items: Optional[List[Any]] = Field(None, description="{title, status, evidence} by title")
    refresh: bool = Field(True, description="Re-verify the checks JARV can confirm from files and the live URL")
    workspace_id: Optional[str] = None


class _Rule(BaseModel):
    name: str
    type: Optional[str] = Field(None, description="workflow, coding, naming, safety, boundary, authority, ...")
    description: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    conditions: Optional[Dict[str, Any]] = None
    actions: Optional[Dict[str, Any]] = None
    priority: Optional[int] = Field(None, ge=1, le=10)
    active: Optional[bool] = None
    remove: bool = False


class _Rules(BaseModel):
    rules: List[_Rule] = Field(..., min_length=1)
    change_summary: str = Field(..., min_length=3)
    workspace_id: Optional[str] = None


class _Archive(BaseModel):
    workspace_id: Optional[str] = None
    archived: bool = True


class _Delete(BaseModel):
    workspace_id: str
    reason: str = Field(..., min_length=5)


# ----- tools ------------------------------------------------------------------------------

class CreateWorkspaceTool(_LifecycleTool):
    _name = "create_workspace"
    _description = "Create a workspace for this owner, optionally linked to an existing approved folder."
    _input = _Create

    async def act(self, db, context, owner, data):
        ws = await workspace_lifecycle.create(
            db, owner, name=data["name"], ceiling=await _ceiling(db, context), description=data.get("description"),
            workspace_type=data["workspace_type"], root_path=data.get("path"),
            authority_level=data.get("authority_level"), company_mode=data["company_mode"])
        return _view(ws), f"Workspace '{ws.name}' created (authority {ws.authority_level})"


class ImportFolderWorkspaceTool(_LifecycleTool):
    _name = "import_folder_workspace"
    _description = "Register an existing folder as a workspace and scan it (stack, commands, missing files)."
    _input = _ImportFolder

    async def act(self, db, context, owner, data):
        ws, scan = await workspace_lifecycle.import_folder(
            db, owner, path=data["path"], ceiling=await _ceiling(db, context), name=data.get("name"),
            description=data.get("description"), authority_level=data.get("authority_level"))
        return {**_view(ws), "scan": scan}, f"Imported '{ws.name}' ({ws.workspace_type})"


class ImportRepositoryWorkspaceTool(_LifecycleTool):
    _name = "import_repository_workspace"
    _description = "Clone a public https git repository into a new folder in the approved root and register it."
    _input = _ImportRepo
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    async def act(self, db, context, owner, data):
        ws, scan = await workspace_lifecycle.import_repository(
            db, owner, url=data["url"], folder_name=data["folder_name"], ceiling=await _ceiling(db, context),
            branch=data.get("branch"), parent_folder=data.get("parent_folder"), name=data.get("name"),
            authority_level=data.get("authority_level"))
        return {**_view(ws), "scan": scan}, f"Cloned and imported '{ws.name}'"


class ImportDocumentPackWorkspaceTool(_LifecycleTool):
    _name = "import_document_pack_workspace"
    _description = "Write a pack of specs or documents into a new folder (docs/ plus an index) and register it."
    _input = _ImportDocs

    async def act(self, db, context, owner, data):
        ws, detail = await workspace_lifecycle.import_document_pack(
            db, owner, folder_name=data["folder_name"], documents=data["documents"],
            ceiling=await _ceiling(db, context), parent_folder=data.get("parent_folder"), name=data.get("name"),
            description=data.get("description"), authority_level=data.get("authority_level"))
        return {**_view(ws), **detail}, f"Document pack '{ws.name}' imported ({len(detail['documents'])} documents)"


class ImportLivePlatformWorkspaceTool(_LifecycleTool):
    _name = "import_live_platform_workspace"
    _description = "Register a live site or service as a workspace after a real reachability and health check."
    _input = _ImportLive
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    async def act(self, db, context, owner, data):
        ws, checks = await workspace_lifecycle.import_live_platform(
            db, owner, name=data["name"], url=data["url"], ceiling=await _ceiling(db, context),
            health_path=data.get("health_path"), root_path=data.get("path"), description=data.get("description"),
            authority_level=data.get("authority_level"))
        state = "up" if checks["check"].get("up") else "DOWN"
        return {**_view(ws), **checks}, f"Live platform '{ws.name}' registered ({state})"


class GenerateTaskPlanTool(_LifecycleTool):
    _name = "generate_task_plan"
    _description = ("Turn a goal into ordered pending tasks in the workspace: the given steps, a model-made "
                    "plan, or steps from the project's own files and commands.")
    _input = _Plan

    async def act(self, db, context, owner, data):
        ws = await _target(db, context, owner, data.get("workspace_id"))
        plan = await workspace_lifecycle.generate_task_plan(db, ws, goal=data["goal"], steps=data.get("steps"))
        return plan, f"{len(plan['tasks'])} task(s) planned ({plan['source']})"


class UpdateRoadmapTool(_LifecycleTool):
    _name = "update_roadmap"
    _description = "Add, change or remove roadmap milestones (by title)."
    _input = _Roadmap

    async def act(self, db, context, owner, data):
        ws = await _target(db, context, owner, data.get("workspace_id"))
        roadmap = await workspace_lifecycle.update_roadmap(db, ws, data["milestones"])
        done = sum(1 for m in roadmap if m.get("status") in ("done", "completed"))
        return {"workspace_id": str(ws.id), "roadmap": roadmap}, f"Roadmap: {done}/{len(roadmap)} milestones done"


class UpdateLaunchChecklistTool(_LifecycleTool):
    _name = "update_launch_checklist"
    _description = ("Update the launch checklist and re-verify what JARV can confirm itself (README, env "
                    "template, tests, container build, CI, licence, live site, HTTPS).")
    _input = _Checklist

    async def act(self, db, context, owner, data):
        ws = await _target(db, context, owner, data.get("workspace_id"))
        result = await workspace_lifecycle.update_launch_checklist(db, ws, data.get("items"), data["refresh"])
        return {"workspace_id": str(ws.id), **result}, (f"Launch checklist {result['done']}/{result['total']}"
                                                         + (" - ready" if result["ready"] else ""))


class UpdateWorkspaceRulesTool(_LifecycleTool):
    _name = "update_workspace_rules"
    _description = ("Create, change or deactivate workspace rules, each change versioned. Changing a protected "
                    "rule or any change that would weaken safety pauses for Richard's approval.")
    _input = _Rules

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if context.db_session is None or context.workspace_id is None:
            return self.create_result(success=False, error_message="update_workspace_rules needs a workspace.")
        db = context.db_session
        try:
            data = _Rules(**input_data).model_dump()
            owner = await workspace_owner(context)
            ws = await _target(db, context, owner, data.get("workspace_id"))
            planned = await workspace_lifecycle.rule_changes(db, ws, data["rules"])
        except (LookupError, PermissionError, ValueError) as exc:
            return self.create_result(success=False, error_message=str(exc))
        gated = [p for p in planned if p["needs_approval"]]
        approved = context.approval_granted or self.name in (context.approved_tools or [])
        if gated and not approved:
            return self.create_result(
                success=False,
                result_data={"blocked": True, "requires_approval": True,
                             "protected_changes": [{"rule": p["name"], "reason": p["reason"]} for p in gated]},
                error_message="Changing protected or safety rules needs Richard's approval (hard boundary).")
        try:
            result, text = await self.act(db, context, owner, {**data, "workspace": ws, "planned": planned})
        except (LookupError, ValueError) as exc:
            return self.create_result(success=False, error_message=str(exc))
        return self.create_result(success=True, result_data=result, output_text=text)

    async def act(self, db, context, owner, data):
        """Apply changes already classified (and, where needed, approved) by run()."""
        ws = data["workspace"]
        results = await workspace_lifecycle.apply_rule_changes(db, ws, data["planned"], owner, data["change_summary"])
        return {"workspace_id": str(ws.id), "rules": results}, f"{len(results)} rule change(s) saved as new versions"


class ArchiveWorkspaceTool(_LifecycleTool):
    _name = "archive_workspace"
    _description = "Archive a workspace (no running work) or restore it with archived=false."
    _input = _Archive

    async def act(self, db, context, owner, data):
        ws = await _target(db, context, owner, data.get("workspace_id"))
        ws = await workspace_lifecycle.archive(db, ws, data["archived"])
        return _view(ws), f"'{ws.name}' {'archived' if ws.is_archived else 'restored'}"


class DeleteWorkspaceWithBoundaryTool(_LifecycleTool):
    _name = "delete_workspace_with_boundary"
    _description = ("Delete a workspace's records after Richard approves (hard boundary). Files on disk are "
                    "never deleted. The workspace running this mission cannot delete itself.")
    _input = _Delete
    _authority = AuthorityLevel.LEVEL_4_SYSTEM_CHANGES
    _approval = True

    async def act(self, db, context, owner, data):
        ws = await _target(db, context, owner, data["workspace_id"])
        if ws.id == context.workspace_id:
            raise PermissionError("A mission cannot delete the workspace it is running in")
        summary = await workspace_lifecycle.delete(db, ws)
        return {**summary, "reason": data["reason"]}, f"Workspace '{summary['name']}' deleted (files kept)"


WORKSPACE_LIFECYCLE_TOOLS = [
    CreateWorkspaceTool, ImportFolderWorkspaceTool, ImportRepositoryWorkspaceTool, ImportDocumentPackWorkspaceTool,
    ImportLivePlatformWorkspaceTool, GenerateTaskPlanTool, UpdateRoadmapTool, UpdateLaunchChecklistTool,
    UpdateWorkspaceRulesTool, ArchiveWorkspaceTool, DeleteWorkspaceWithBoundaryTool,
]
