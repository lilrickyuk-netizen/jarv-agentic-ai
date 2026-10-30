"""
JARV Backend - Workspace Backup Tools

Workspace backup/restore: backup, restore, export, import.
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field
import logging
import json
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4
from sqlalchemy import select

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.core.security import redact_secrets
from app.models.operations import BackupRecord
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


def _scope(context: ToolContext):
    if context.db_session is None:
        raise ValueError("Workspace database session is unavailable")
    if context.user_id is None:
        raise PermissionError("Authenticated user context is required")
    return context.db_session, UUID(str(context.user_id))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:90] or "workspace"


def _scoped_path(raw_path: str, context: ToolContext, workspace: Optional[Workspace] = None) -> Path:
    requested = Path(raw_path).expanduser().resolve()
    roots = list(context.approved_folders or [])
    if workspace is not None:
        configured = (workspace.config or {}).get("workspace_path")
        if configured:
            roots.append(configured)
    allowed_roots = [Path(root).expanduser().resolve() for root in roots]
    if not allowed_roots or not any(requested == root or root in requested.parents for root in allowed_roots):
        raise PermissionError("Transfer path is outside approved workspace folders")
    banned = [Path(root).expanduser().resolve() for root in context.banned_folders or []]
    if any(requested == root or root in requested.parents for root in banned):
        raise PermissionError("Transfer path is inside a banned folder")
    return requested


def _workspace_payload(workspace: Workspace) -> Dict[str, Any]:
    config = redact_secrets({
        key: value for key, value in (workspace.config or {}).items()
        if key != "workspace_path"
    })
    return {
        "format_version": 1,
        "workspace": {
            "name": workspace.name,
            "description": workspace.description,
            "workspace_type": workspace.workspace_type,
            "authority_level": workspace.authority_level,
            "config": config,
            "max_subagents": workspace.max_subagents,
            "swarm_enabled": workspace.swarm_enabled,
            "self_evolution_enabled": workspace.self_evolution_enabled,
            "company_mode_enabled": workspace.company_mode_enabled,
        },
        "limitations": [
            "This transfer contains redacted workspace metadata only; task history, files, credentials, and external integrations are not included."
        ],
    }


# ===== WORKSPACE BACKUP TOOL =====

class WorkspaceBackupInput(BaseModel):
    """Input schema for workspace backup tool"""
    workspace_id: str = Field(..., description="Workspace ID to backup")
    backup_name: Optional[str] = Field(None, description="Backup name")
    include_files: bool = Field(default=True, description="Include files in backup")


class WorkspaceBackupOutput(BaseModel):
    """Output schema for workspace backup tool"""
    backup_id: str = Field(..., description="Backup ID")
    workspace_id: str = Field(..., description="Workspace ID")
    backup_size: int = Field(..., description="Backup size in bytes")
    message: str = Field(..., description="Status message")
    files_included: bool = False
    limitations: list[str] = Field(default_factory=list)


class WorkspaceBackupTool(ToolBase):
    """Tool for backing up workspace"""

    @property
    def name(self) -> str:
        return "workspace_backup"

    @property
    def description(self) -> str:
        return "Create a backup of workspace data and settings."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceBackupInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceBackupOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "workspace"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute workspace backup"""
        workspace_id = input_data["workspace_id"]
        backup_name = input_data.get("backup_name")
        include_files = input_data["include_files"]
        try:
            db, user_id = _scope(context)
            workspace = (await db.execute(select(Workspace).where(
                Workspace.id == UUID(workspace_id), Workspace.owner_id == user_id
            ))).scalar_one_or_none()
            if workspace is None:
                return self.create_result(success=False, error_message="Owned workspace not found")
            snapshot = {
                "workspace": {
                    "name": workspace.name,
                    "description": workspace.description,
                    "workspace_type": workspace.workspace_type,
                    "authority_level": workspace.authority_level,
                    "config": workspace.config or {},
                    "max_subagents": workspace.max_subagents,
                    "swarm_enabled": workspace.swarm_enabled,
                    "self_evolution_enabled": workspace.self_evolution_enabled,
                    "company_mode_enabled": workspace.company_mode_enabled,
                },
            }
            encoded = json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")
            backup_id = uuid4()
            limitations = []
            if include_files:
                limitations.append("No filesystem root is configured in the workspace record; file contents were not backed up.")
            record = BackupRecord(
                id=backup_id,
                workspace_id=workspace.id,
                backup_name=(backup_name or f"{workspace.name}-{backup_id.hex[:8]}")[:255],
                backup_type="workspace_metadata",
                description="Database-backed workspace settings snapshot",
                source_type="workspace",
                source_id=str(workspace.id),
                source_name=workspace.name,
                storage_location=f"database://backup_records/{backup_id}",
                storage_provider="database",
                backup_size_bytes=len(encoded),
                status="completed",
                success=True,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                retention_days=30,
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                is_verified=True,
                verified_at=datetime.now(timezone.utc),
                meta_data={"snapshot": snapshot, "files_included": False, "limitations": limitations},
            )
            db.add(record)
            await db.flush()
            logger.info(f"Creating backup for workspace: {workspace_id}")
            return self.create_result(
                success=True,
                result_data={
                    "backup_id": str(backup_id),
                    "workspace_id": str(workspace.id),
                    "backup_size": len(encoded),
                    "message": "Workspace metadata snapshot persisted.",
                    "files_included": False,
                    "limitations": limitations,
                },
                output_text=f"Created backup: {backup_id}",
            )
        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to backup workspace: {str(e)}")


# ===== WORKSPACE RESTORE TOOL =====

class WorkspaceRestoreInput(BaseModel):
    """Input schema for workspace restore tool"""
    backup_id: str = Field(..., description="Backup ID to restore from")
    workspace_id: Optional[str] = Field(None, description="Target workspace ID (creates new if not specified)")


class WorkspaceRestoreOutput(BaseModel):
    """Output schema for workspace restore tool"""
    workspace_id: str = Field(..., description="Restored workspace ID")
    backup_id: str = Field(..., description="Backup ID used")
    message: str = Field(..., description="Status message")


class WorkspaceRestoreTool(ToolBase):
    """Tool for restoring workspace from backup"""

    @property
    def name(self) -> str:
        return "workspace_restore"

    @property
    def description(self) -> str:
        return "Restore workspace from a backup."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceRestoreInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceRestoreOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_4_SYSTEM_CHANGES

    @property
    def requires_approval(self) -> bool:
        return True  # Can overwrite data

    @property
    def category(self) -> str:
        return "workspace"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute workspace restore"""
        backup_id = input_data["backup_id"]
        workspace_id = input_data.get("workspace_id")

        try:
            db, user_id = _scope(context)
            backup = (await db.execute(select(BackupRecord).where(
                BackupRecord.id == UUID(backup_id),
                BackupRecord.backup_type == "workspace_metadata",
                BackupRecord.success.is_(True),
                BackupRecord.is_deleted.is_(False),
            ))).scalar_one_or_none()
            if backup is None:
                return self.create_result(success=False, error_message="Workspace backup not found")
            source = (await db.execute(select(Workspace).where(
                Workspace.id == backup.workspace_id, Workspace.owner_id == user_id
            ))).scalar_one_or_none()
            if source is None:
                return self.create_result(success=False, error_message="Backup is outside the authenticated user's scope")
            snapshot = (backup.meta_data or {}).get("snapshot", {}).get("workspace")
            if not snapshot:
                return self.create_result(success=False, error_message="Backup snapshot is missing")
            if workspace_id:
                target = (await db.execute(select(Workspace).where(
                    Workspace.id == UUID(workspace_id), Workspace.owner_id == user_id
                ))).scalar_one_or_none()
                if target is None:
                    return self.create_result(success=False, error_message="Owned restore target not found")
            else:
                name = snapshot.get("name", "Restored workspace")
                slug_base = _slug(f"{name}-restored")
                slug = f"{slug_base}-{uuid4().hex[:8]}"
                target = Workspace(
                    id=uuid4(), owner_id=user_id, name=name, slug=slug,
                    description=snapshot.get("description"),
                    workspace_type=snapshot.get("workspace_type", "project"),
                    authority_level=snapshot.get("authority_level", 3),
                    config=snapshot.get("config", {}),
                    max_subagents=snapshot.get("max_subagents", 50),
                    swarm_enabled=snapshot.get("swarm_enabled", True),
                    self_evolution_enabled=snapshot.get("self_evolution_enabled", False),
                    company_mode_enabled=snapshot.get("company_mode_enabled", False),
                    is_active=True,
                )
                db.add(target)
            if workspace_id:
                target.name = snapshot.get("name", target.name)
                target.description = snapshot.get("description")
                target.workspace_type = snapshot.get("workspace_type", target.workspace_type)
                target.config = snapshot.get("config", {})
                target.max_subagents = snapshot.get("max_subagents", target.max_subagents)
                target.swarm_enabled = snapshot.get("swarm_enabled", target.swarm_enabled)
                target.self_evolution_enabled = snapshot.get("self_evolution_enabled", target.self_evolution_enabled)
                target.company_mode_enabled = snapshot.get("company_mode_enabled", target.company_mode_enabled)
            await db.flush()
            workspace_id = str(target.id)
            logger.info(f"Restoring workspace from backup: {backup_id}")

            return self.create_result(
                success=True,
                result_data={
                    "workspace_id": workspace_id,
                    "backup_id": backup_id,
                    "message": f"Workspace restored successfully",
                },
                output_text=f"Restored workspace: {workspace_id}",
            )
        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to restore workspace: {str(e)}")


# ===== WORKSPACE EXPORT TOOL =====

class WorkspaceExportInput(BaseModel):
    """Input schema for workspace export tool"""
    workspace_id: str = Field(..., description="Workspace ID to export")
    export_path: str = Field(..., description="Path to export file")
    format: str = Field(default="json", description="Export format: json, zip")


class WorkspaceExportOutput(BaseModel):
    """Output schema for workspace export tool"""
    workspace_id: str = Field(..., description="Exported workspace ID")
    export_path: str = Field(..., description="Export file path")
    file_size: int = Field(..., description="Export file size in bytes")
    message: str = Field(..., description="Status message")
    files_included: bool = False
    limitations: list[str] = Field(default_factory=list)


class WorkspaceExportTool(ToolBase):
    """Tool for exporting workspace data"""

    @property
    def name(self) -> str:
        return "workspace_export"

    @property
    def description(self) -> str:
        return "Export workspace data to file for transfer or archival."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceExportInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceExportOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "workspace"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute workspace export"""
        workspace_id = input_data["workspace_id"]
        export_path = input_data["export_path"]
        format = input_data["format"]

        try:
            db, user_id = _scope(context)
            workspace = (await db.execute(select(Workspace).where(
                Workspace.id == UUID(workspace_id), Workspace.owner_id == user_id
            ))).scalar_one_or_none()
            if workspace is None:
                return self.create_result(success=False, error_message="Owned workspace not found")
            if format not in ("json", "zip"):
                return self.create_result(success=False, error_message="Export format must be json or zip")
            destination = _scoped_path(export_path, context, workspace)
            payload = _workspace_payload(workspace)
            encoded = json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if format == "json":
                destination.write_bytes(encoded)
            else:
                with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("workspace.json", encoded)
            file_size = destination.stat().st_size
            logger.info(f"Exporting workspace {workspace_id} to {export_path}")

            return self.create_result(
                success=True,
                result_data={
                    "workspace_id": workspace_id,
                    "export_path": export_path,
                    "file_size": file_size,
                    "message": "Redacted workspace metadata exported.",
                    "files_included": False,
                    "limitations": payload["limitations"],
                },
                output_text=f"Exported workspace to: {export_path}",
                files_affected=[export_path],
            )
        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to export workspace: {str(e)}")


# ===== WORKSPACE IMPORT TOOL =====

class WorkspaceImportInput(BaseModel):
    """Input schema for workspace import tool"""
    import_path: str = Field(..., description="Path to import file")
    workspace_name: Optional[str] = Field(None, description="Name for imported workspace")
    overwrite: bool = Field(default=False, description="Overwrite existing workspace if name conflicts")


class WorkspaceImportOutput(BaseModel):
    """Output schema for workspace import tool"""
    workspace_id: str = Field(..., description="Imported workspace ID")
    workspace_name: str = Field(..., description="Workspace name")
    message: str = Field(..., description="Status message")
    limitations: list[str] = Field(default_factory=list)


class WorkspaceImportTool(ToolBase):
    """Tool for importing workspace data"""

    @property
    def name(self) -> str:
        return "workspace_import"

    @property
    def description(self) -> str:
        return "Import workspace data from exported file."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceImportInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceImportOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_4_SYSTEM_CHANGES

    @property
    def requires_approval(self) -> bool:
        return True  # Creates new workspace

    @property
    def category(self) -> str:
        return "workspace"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute workspace import"""
        import_path = input_data["import_path"]
        workspace_name = input_data.get("workspace_name")
        overwrite = input_data["overwrite"]

        try:
            db, user_id = _scope(context)
            source_path = _scoped_path(import_path, context)
            if not source_path.is_file():
                return self.create_result(success=False, error_message="Import file does not exist")
            if source_path.suffix.lower() == ".zip":
                with zipfile.ZipFile(source_path) as archive:
                    try:
                        encoded = archive.read("workspace.json")
                    except KeyError:
                        return self.create_result(success=False, error_message="ZIP archive lacks workspace.json")
            else:
                encoded = source_path.read_bytes()
            payload = json.loads(encoded.decode("utf-8"))
            snapshot = payload.get("workspace")
            if payload.get("format_version") != 1 or not isinstance(snapshot, dict):
                return self.create_result(success=False, error_message="Unsupported workspace transfer schema")
            workspace_name = (workspace_name or snapshot.get("name") or "Imported Workspace").strip()
            if not workspace_name:
                return self.create_result(success=False, error_message="Workspace name cannot be empty")
            slug = _slug(workspace_name)
            existing = (await db.execute(select(Workspace).where(
                Workspace.owner_id == user_id, Workspace.slug == slug
            ))).scalar_one_or_none()
            if existing is not None and not overwrite:
                slug = f"{slug[:80]}-{uuid4().hex[:8]}"
                existing = None
            if existing is not None:
                workspace = existing
                workspace.name = workspace_name
                workspace.description = snapshot.get("description")
                workspace.workspace_type = snapshot.get("workspace_type", workspace.workspace_type)
                workspace.authority_level = min(
                    int(snapshot.get("authority_level", 3)), int(self.config.authority_level.value))
                workspace.config = dict(snapshot.get("config") or {})
            else:
                workspace = Workspace(
                    id=uuid4(), owner_id=user_id, name=workspace_name, slug=slug,
                    description=snapshot.get("description"),
                    workspace_type=snapshot.get("workspace_type", "project"),
                    authority_level=min(
                        int(snapshot.get("authority_level", 3)), int(self.config.authority_level.value)),
                    config=dict(snapshot.get("config") or {}),
                    max_subagents=int(snapshot.get("max_subagents", 50)),
                    swarm_enabled=bool(snapshot.get("swarm_enabled", True)),
                    self_evolution_enabled=bool(snapshot.get("self_evolution_enabled", False)),
                    company_mode_enabled=bool(snapshot.get("company_mode_enabled", False)),
                    is_active=True,
                )
                db.add(workspace)
            await db.flush()
            logger.info(f"Importing workspace from {import_path}")

            return self.create_result(
                success=True,
                result_data={
                    "workspace_id": str(workspace.id),
                    "workspace_name": workspace_name,
                    "message": "Workspace metadata imported; files and runtime state were not included.",
                    "limitations": payload.get("limitations", []),
                },
                output_text=f"Imported workspace: {workspace_name}",
            )
        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to import workspace: {str(e)}")
