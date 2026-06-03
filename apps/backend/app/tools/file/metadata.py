"""
JARV Backend - File Metadata Tools

File metadata tools: metadata, permissions.
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime
import stat
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


# ===== FILE METADATA TOOL =====

class FileMetadataInput(BaseModel):
    """Input schema for file metadata tool"""
    path: str = Field(..., description="Path to file")


class FileMetadataOutput(BaseModel):
    """Output schema for file metadata tool"""
    path: str = Field(..., description="Absolute file path")
    name: str = Field(..., description="File name")
    size: int = Field(..., description="File size in bytes")
    created: Optional[str] = Field(None, description="Creation time (ISO format)")
    modified: str = Field(..., description="Modification time (ISO format)")
    accessed: str = Field(..., description="Access time (ISO format)")
    is_file: bool = Field(..., description="Whether path is a file")
    is_dir: bool = Field(..., description="Whether path is a directory")
    is_symlink: bool = Field(..., description="Whether path is a symlink")
    extension: Optional[str] = Field(None, description="File extension")
    permissions: str = Field(..., description="File permissions (e.g., 0o644)")


class FileMetadataTool(ToolBase):
    """Tool for getting file metadata and statistics"""

    @property
    def name(self) -> str:
        return "file_metadata"

    @property
    def description(self) -> str:
        return "Get metadata and statistics about a file or directory (size, timestamps, permissions, etc.)."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileMetadataInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileMetadataOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "file"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute file metadata retrieval"""
        path = input_data["path"]

        try:
            # Resolve path
            file_path = Path(path).resolve()

            # Check if path exists
            if not file_path.exists():
                return self.create_result(
                    success=False,
                    error_message=f"Path not found: {path}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(file_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: Path in banned folder {banned}",
                        )

            # Get file stats
            file_stat = file_path.stat()

            # Get timestamps
            modified = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
            accessed = datetime.fromtimestamp(file_stat.st_atime).isoformat()

            # Creation time (platform dependent)
            created = None
            if hasattr(file_stat, "st_birthtime"):
                created = datetime.fromtimestamp(file_stat.st_birthtime).isoformat()
            elif hasattr(file_stat, "st_ctime"):
                created = datetime.fromtimestamp(file_stat.st_ctime).isoformat()

            # Get extension
            extension = file_path.suffix if file_path.is_file() else None

            # Get permissions
            permissions = oct(file_stat.st_mode)

            return self.create_result(
                success=True,
                result_data={
                    "path": str(file_path),
                    "name": file_path.name,
                    "size": file_stat.st_size,
                    "created": created,
                    "modified": modified,
                    "accessed": accessed,
                    "is_file": file_path.is_file(),
                    "is_dir": file_path.is_dir(),
                    "is_symlink": file_path.is_symlink(),
                    "extension": extension,
                    "permissions": permissions,
                },
                output_text=f"Metadata for {file_path.name}: {file_stat.st_size} bytes, modified {modified}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to get metadata: {str(e)}",
            )


# ===== FILE PERMISSIONS TOOL =====

class FilePermissionsInput(BaseModel):
    """Input schema for file permissions tool"""
    path: str = Field(..., description="Path to file")
    mode: Optional[str] = Field(None, description="New permissions mode (e.g., '0o644', '644')")
    set_mode: bool = Field(default=False, description="Whether to set new permissions")


class FilePermissionsOutput(BaseModel):
    """Output schema for file permissions tool"""
    path: str = Field(..., description="File path")
    current_mode: str = Field(..., description="Current permissions mode")
    new_mode: Optional[str] = Field(None, description="New permissions mode (if set)")
    readable: bool = Field(..., description="Whether file is readable")
    writable: bool = Field(..., description="Whether file is writable")
    executable: bool = Field(..., description="Whether file is executable")


class FilePermissionsTool(ToolBase):
    """Tool for getting and setting file permissions"""

    @property
    def name(self) -> str:
        return "file_permissions"

    @property
    def description(self) -> str:
        return "Get or set file permissions. Can read current permissions or set new ones."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FilePermissionsInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FilePermissionsOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        # Reading permissions is level 1, setting is level 2
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "file"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute file permissions operation"""
        path = input_data["path"]
        mode = input_data.get("mode")
        set_mode = input_data["set_mode"]

        try:
            # Resolve path
            file_path = Path(path).resolve()

            # Check if path exists
            if not file_path.exists():
                return self.create_result(
                    success=False,
                    error_message=f"Path not found: {path}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(file_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: Path in banned folder {banned}",
                        )

            # Get current permissions
            current_stat = file_path.stat()
            current_mode = oct(current_stat.st_mode)

            # Check if we should set new permissions
            new_mode = None
            if set_mode:
                if not mode:
                    return self.create_result(
                        success=False,
                        error_message="mode parameter required when set_mode=True",
                    )

                # Check authority for setting permissions
                if self.config.authority_level < AuthorityLevel.LEVEL_2_FILE_OPERATIONS:
                    return self.create_result(
                        success=False,
                        error_message=f"Setting permissions requires authority level {AuthorityLevel.LEVEL_2_FILE_OPERATIONS.value}",
                    )

                # Parse mode
                try:
                    # Handle both "0o644" and "644" formats
                    mode_str = mode.strip()
                    if mode_str.startswith("0o"):
                        mode_int = int(mode_str, 8)
                    else:
                        mode_int = int(mode_str, 8)

                    # Set permissions
                    file_path.chmod(mode_int)
                    new_mode = oct(mode_int)

                except ValueError as e:
                    return self.create_result(
                        success=False,
                        error_message=f"Invalid mode format: {mode}. Use octal format like '0o644' or '644'",
                    )

            # Check permissions
            readable = current_stat.st_mode & stat.S_IRUSR != 0
            writable = current_stat.st_mode & stat.S_IWUSR != 0
            executable = current_stat.st_mode & stat.S_IXUSR != 0

            return self.create_result(
                success=True,
                result_data={
                    "path": str(file_path),
                    "current_mode": current_mode,
                    "new_mode": new_mode,
                    "readable": readable,
                    "writable": writable,
                    "executable": executable,
                },
                output_text=f"Permissions for {file_path.name}: {new_mode or current_mode}",
                files_affected=[str(file_path)] if set_mode else [],
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to handle permissions: {str(e)}",
            )
