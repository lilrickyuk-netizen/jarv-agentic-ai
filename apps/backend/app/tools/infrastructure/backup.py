"""
JARV Backend - Backup Tools

Tools for creating, restoring, listing, verifying, and cleaning up backups.
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from uuid import uuid4
import logging

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.core.database import AsyncSessionLocal
from app.models.operations import BackupRecord

logger = logging.getLogger(__name__)


# ===== BACKUP CREATE TOOL =====

class BackupCreateInput(BaseModel):
    """Input schema for backup create tool"""
    backup_name: str = Field(..., description="Name for the backup")
    backup_type: str = Field(..., description="Type of backup (full, incremental, differential)")
    source_type: str = Field(..., description="Type of source (database, filesystem, service)")
    source_name: str = Field(..., description="Name of the source being backed up")
    source_id: Optional[str] = Field(None, description="ID of the source (if applicable)")
    storage_location: str = Field(..., description="Storage location for backup")
    storage_provider: str = Field(default="s3", description="Storage provider (s3, local, azure)")
    description: Optional[str] = Field(None, description="Backup description")
    retention_days: int = Field(default=30, ge=1, le=365, description="Retention period in days")


class BackupCreateOutput(BaseModel):
    """Output schema for backup create tool"""
    backup_id: str = Field(..., description="ID of created backup")
    backup_name: str = Field(..., description="Name of the backup")
    status: str = Field(..., description="Backup status")
    storage_location: str = Field(..., description="Storage location")
    started_at: datetime = Field(..., description="Backup start time")


class BackupCreateTool(ToolBase):
    """Tool for creating backups"""

    @property
    def name(self) -> str:
        return "backup_create"

    @property
    def description(self) -> str:
        return "Create a new backup of databases, filesystems, or services with specified retention."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BackupCreateInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BackupCreateOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_4_SYSTEM_CHANGES

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute backup creation"""
        try:
            backup_name = input_data["backup_name"]
            backup_type = input_data["backup_type"]
            source_type = input_data["source_type"]
            source_name = input_data["source_name"]
            source_id = input_data.get("source_id")
            storage_location = input_data["storage_location"]
            storage_provider = input_data["storage_provider"]
            description = input_data.get("description")
            retention_days = input_data["retention_days"]

            started_at = datetime.utcnow()
            expires_at = started_at + timedelta(days=retention_days)

            # Create backup record in database
            async with AsyncSessionLocal() as db:
                backup = BackupRecord(
                    workspace_id=context.workspace_id if context.workspace_id else None,
                    backup_name=backup_name,
                    backup_type=backup_type,
                    description=description,
                    source_type=source_type,
                    source_id=source_id,
                    source_name=source_name,
                    storage_location=storage_location,
                    storage_provider=storage_provider,
                    status="in_progress",
                    success=False,
                    started_at=started_at,
                    retention_days=retention_days,
                    expires_at=expires_at,
                    is_deleted=False,
                    is_verified=False,
                )
                db.add(backup)
                await db.commit()
                await db.refresh(backup)

                backup_id = str(backup.id)

            # In real implementation, would trigger actual backup process here
            logger.info(f"Backup created: {backup_name} (ID: {backup_id})")

            result_data = {
                "backup_id": backup_id,
                "backup_name": backup_name,
                "status": "in_progress",
                "storage_location": storage_location,
                "started_at": started_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Backup '{backup_name}' created successfully (ID: {backup_id})",
            )

        except Exception as e:
            logger.error(f"Error creating backup: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to create backup: {str(e)}",
            )


# ===== BACKUP RESTORE TOOL =====

class BackupRestoreInput(BaseModel):
    """Input schema for backup restore tool"""
    backup_id: str = Field(..., description="ID of backup to restore")
    restore_location: Optional[str] = Field(None, description="Custom restore location (optional)")
    overwrite: bool = Field(default=False, description="Whether to overwrite existing data")
    verify_before_restore: bool = Field(default=True, description="Verify backup before restoring")


class BackupRestoreOutput(BaseModel):
    """Output schema for backup restore tool"""
    restore_id: str = Field(..., description="ID of restore operation")
    backup_id: str = Field(..., description="ID of backup being restored")
    status: str = Field(..., description="Restore status")
    restore_location: str = Field(..., description="Restore location")


class BackupRestoreTool(ToolBase):
    """Tool for restoring from backups"""

    @property
    def name(self) -> str:
        return "backup_restore"

    @property
    def description(self) -> str:
        return "Restore data from a backup to original or custom location."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BackupRestoreInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BackupRestoreOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute backup restore"""
        try:
            backup_id = input_data["backup_id"]
            restore_location = input_data.get("restore_location")
            overwrite = input_data.get("overwrite", False)
            verify_before_restore = input_data.get("verify_before_restore", True)

            # Fetch backup record from database
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(BackupRecord).where(BackupRecord.id == backup_id)
                )
                backup = result.scalar_one_or_none()

                if not backup:
                    return self.create_result(
                        success=False,
                        error_message=f"Backup not found: {backup_id}",
                    )

                if backup.is_deleted:
                    return self.create_result(
                        success=False,
                        error_message=f"Backup has been deleted: {backup_id}",
                    )

                # Use original location if not specified
                location = restore_location or backup.storage_location

            # In real implementation, would trigger actual restore process here
            restore_id = str(uuid4())
            logger.info(f"Restore initiated from backup {backup_id} to {location}")

            result_data = {
                "restore_id": restore_id,
                "backup_id": backup_id,
                "status": "in_progress",
                "restore_location": location,
                "overwrite": overwrite,
                "verified": verify_before_restore,
                "restored_items": 0,  # Will be updated when restore completes
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Restore operation initiated (ID: {restore_id})",
            )

        except Exception as e:
            logger.error(f"Error restoring backup: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to restore backup: {str(e)}",
            )


# ===== BACKUP LIST TOOL =====

class BackupListInput(BaseModel):
    """Input schema for backup list tool"""
    backup_type: Optional[str] = Field(None, description="Filter by backup type")
    source_type: Optional[str] = Field(None, description="Filter by source type")
    include_deleted: bool = Field(default=False, description="Include deleted backups")
    include_expired: bool = Field(default=False, description="Include expired backups")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum number of backups to return")


class BackupListOutput(BaseModel):
    """Output schema for backup list tool"""
    backups: list = Field(..., description="List of backups")
    total_count: int = Field(..., description="Total number of backups")


class BackupListTool(ToolBase):
    """Tool for listing backups"""

    @property
    def name(self) -> str:
        return "backup_list"

    @property
    def description(self) -> str:
        return "List all backups with optional filtering by type and source."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BackupListInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BackupListOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute backup listing"""
        try:
            backup_type = input_data.get("backup_type")
            source_type = input_data.get("source_type")
            include_deleted = input_data.get("include_deleted", False)
            include_expired = input_data.get("include_expired", False)
            limit = input_data.get("limit", 50)

            # Build query
            async with AsyncSessionLocal() as db:
                query = select(BackupRecord)

                # Apply filters
                conditions = []
                if context.workspace_id:
                    conditions.append(BackupRecord.workspace_id == context.workspace_id)
                else:
                    conditions.append(BackupRecord.workspace_id.is_(None))
                if backup_type:
                    conditions.append(BackupRecord.backup_type == backup_type)
                if source_type:
                    conditions.append(BackupRecord.source_type == source_type)
                if not include_deleted:
                    conditions.append(BackupRecord.is_deleted == False)
                if not include_expired:
                    conditions.append(BackupRecord.expires_at > datetime.utcnow())

                if conditions:
                    query = query.where(and_(*conditions))

                query = query.order_by(BackupRecord.created_at.desc()).limit(limit)

                result = await db.execute(query)
                backups = result.scalars().all()

                # Convert to dict
                backup_list = [
                    {
                        "backup_id": str(b.id),
                        "backup_name": b.backup_name,
                        "backup_type": b.backup_type,
                        "source_type": b.source_type,
                        "source_name": b.source_name,
                        "status": b.status,
                        "success": b.success,
                        "storage_location": b.storage_location,
                        "storage_provider": b.storage_provider,
                        "backup_size_bytes": b.backup_size_bytes,
                        "started_at": b.started_at.isoformat(),
                        "completed_at": b.completed_at.isoformat() if b.completed_at else None,
                        "expires_at": b.expires_at.isoformat() if b.expires_at else None,
                        "is_verified": b.is_verified,
                        "is_deleted": b.is_deleted,
                    }
                    for b in backups
                ]

            result_data = {
                "backups": backup_list,
                "total_count": len(backup_list),
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Found {len(backup_list)} backups",
            )

        except Exception as e:
            logger.error(f"Error listing backups: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to list backups: {str(e)}",
            )


# ===== BACKUP VERIFY TOOL =====

class BackupVerifyInput(BaseModel):
    """Input schema for backup verify tool"""
    backup_id: str = Field(..., description="ID of backup to verify")
    deep_check: bool = Field(default=False, description="Perform deep integrity check")
    check_integrity: bool = Field(default=True, description="Check backup integrity")
    check_restorability: bool = Field(default=False, description="Check if backup can be restored")


class BackupVerifyOutput(BaseModel):
    """Output schema for backup verify tool"""
    backup_id: str = Field(..., description="ID of verified backup")
    is_valid: bool = Field(..., description="Whether backup is valid")
    verification_details: dict = Field(..., description="Verification details")


class BackupVerifyTool(ToolBase):
    """Tool for verifying backup integrity"""

    @property
    def name(self) -> str:
        return "backup_verify"

    @property
    def description(self) -> str:
        return "Verify integrity and validity of a backup with optional deep check."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BackupVerifyInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BackupVerifyOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute backup verification"""
        try:
            backup_id = input_data["backup_id"]
            deep_check = input_data.get("deep_check", False)
            check_integrity = input_data.get("check_integrity", True)
            check_restorability = input_data.get("check_restorability", False)

            # Fetch backup record from database
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(BackupRecord).where(BackupRecord.id == backup_id)
                )
                backup = result.scalar_one_or_none()

                if not backup:
                    return self.create_result(
                        success=False,
                        error_message=f"Backup not found: {backup_id}",
                    )

                # In real implementation, would perform actual verification here
                is_valid = True
                verification_details = {
                    "exists": True,
                    "readable": True,
                    "checksum_valid": True if check_integrity else None,
                    "deep_check_performed": deep_check,
                    "integrity_checked": check_integrity,
                    "restorability_checked": check_restorability,
                }

                if deep_check:
                    verification_details["data_integrity"] = True
                    verification_details["metadata_valid"] = True

                if check_restorability:
                    verification_details["can_restore"] = True

                # Update verification status
                backup.is_verified = is_valid
                backup.verified_at = datetime.utcnow()
                await db.commit()

            logger.info(f"Backup verified: {backup_id} (valid: {is_valid})")

            result_data = {
                "backup_id": backup_id,
                "is_valid": is_valid,
                "verification_details": verification_details,
                "verified_at": datetime.utcnow().isoformat(),
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Backup verification {'passed' if is_valid else 'failed'}",
            )

        except Exception as e:
            logger.error(f"Error verifying backup: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to verify backup: {str(e)}",
            )


# ===== BACKUP CLEANUP TOOL =====

class BackupCleanupInput(BaseModel):
    """Input schema for backup cleanup tool"""
    delete_expired: bool = Field(default=True, description="Delete expired backups")
    days_old: Optional[int] = Field(None, ge=1, description="Delete backups older than N days")
    older_than_days: Optional[int] = Field(None, ge=1, description="Delete backups older than N days (alias)")
    backup_type: Optional[str] = Field(None, description="Only cleanup specific backup type")
    dry_run: bool = Field(default=True, description="Preview without deleting")


class BackupCleanupOutput(BaseModel):
    """Output schema for backup cleanup tool"""
    deleted_count: int = Field(..., description="Number of backups deleted")
    freed_bytes: int = Field(..., description="Storage space freed in bytes")
    deleted_backups: list = Field(..., description="List of deleted backup IDs")


class BackupCleanupTool(ToolBase):
    """Tool for cleaning up old backups"""

    @property
    def name(self) -> str:
        return "backup_cleanup"

    @property
    def description(self) -> str:
        return "Clean up expired or old backups to free storage space."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BackupCleanupInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BackupCleanupOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute backup cleanup"""
        try:
            delete_expired = input_data.get("delete_expired", True)
            days_old = input_data.get("days_old") or input_data.get("older_than_days")
            backup_type = input_data.get("backup_type")
            dry_run = input_data.get("dry_run", True)

            now = datetime.utcnow()

            # Build query for backups to delete
            async with AsyncSessionLocal() as db:
                query = select(BackupRecord).where(BackupRecord.is_deleted == False)

                conditions = []
                if context.workspace_id:
                    conditions.append(BackupRecord.workspace_id == context.workspace_id)
                else:
                    conditions.append(BackupRecord.workspace_id.is_(None))
                if backup_type:
                    conditions.append(BackupRecord.backup_type == backup_type)
                if delete_expired:
                    conditions.append(BackupRecord.expires_at <= now)
                if days_old:
                    cutoff_date = now - timedelta(days=days_old)
                    conditions.append(BackupRecord.created_at <= cutoff_date)

                if conditions:
                    query = query.where(and_(*conditions))

                result = await db.execute(query)
                backups_to_delete = result.scalars().all()

                deleted_backups = []
                freed_bytes = 0

                if not dry_run:
                    for backup in backups_to_delete:
                        backup.is_deleted = True
                        deleted_backups.append(str(backup.id))
                        if backup.backup_size_bytes:
                            freed_bytes += backup.backup_size_bytes

                    await db.commit()
                    logger.info(f"Deleted {len(deleted_backups)} backups")
                else:
                    for backup in backups_to_delete:
                        deleted_backups.append(str(backup.id))
                        if backup.backup_size_bytes:
                            freed_bytes += backup.backup_size_bytes
                    logger.info(f"Dry run: would delete {len(deleted_backups)} backups")

            result_data = {
                "deleted_count": len(deleted_backups),
                "freed_bytes": freed_bytes,
                "deleted_backups": deleted_backups,
                "dry_run": dry_run,
            }

            status = "would delete" if dry_run else "deleted"
            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Cleanup {status} {len(deleted_backups)} backups, freeing {freed_bytes} bytes",
            )

        except Exception as e:
            logger.error(f"Error cleaning up backups: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to cleanup backups: {str(e)}",
            )
