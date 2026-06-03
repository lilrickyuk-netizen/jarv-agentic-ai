"""
JARV Backend - File Operations Tools

File operation tools: delete, move, copy.
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
from pathlib import Path
import shutil
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


# ===== FILE DELETE TOOL =====

class FileDeleteInput(BaseModel):
    """Input schema for file delete tool"""
    path: str = Field(..., description="Path to file to delete")
    missing_ok: bool = Field(default=False, description="Don't fail if file doesn't exist")


class FileDeleteOutput(BaseModel):
    """Output schema for file delete tool"""
    path: str = Field(..., description="Deleted file path")
    deleted: bool = Field(..., description="Whether file was actually deleted")


class FileDeleteTool(ToolBase):
    """Tool for deleting files"""

    @property
    def name(self) -> str:
        return "file_delete"

    @property
    def description(self) -> str:
        return "Delete a file. Requires approval due to destructive nature."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileDeleteInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileDeleteOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return True  # Destructive operation

    @property
    def category(self) -> str:
        return "file"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute file delete"""
        path = input_data["path"]
        missing_ok = input_data["missing_ok"]

        try:
            # Resolve path
            file_path = Path(path).resolve()

            # Check if file exists
            if not file_path.exists():
                if missing_ok:
                    return self.create_result(
                        success=True,
                        result_data={
                            "path": str(file_path),
                            "deleted": False,
                        },
                        output_text=f"File does not exist: {file_path.name}",
                    )
                else:
                    return self.create_result(
                        success=False,
                        error_message=f"File not found: {path}",
                    )

            # Check if it's a file
            if not file_path.is_file():
                return self.create_result(
                    success=False,
                    error_message=f"Path is not a file: {path}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(file_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: File in banned folder {banned}",
                        )

            # Delete file
            file_path.unlink()

            return self.create_result(
                success=True,
                result_data={
                    "path": str(file_path),
                    "deleted": True,
                },
                output_text=f"Deleted file: {file_path.name}",
                files_affected=[str(file_path)],
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to delete file: {str(e)}",
            )


# ===== FILE MOVE TOOL =====

class FileMoveInput(BaseModel):
    """Input schema for file move tool"""
    source: str = Field(..., description="Source file path")
    destination: str = Field(..., description="Destination file path")
    overwrite: bool = Field(default=False, description="Overwrite destination if exists")


class FileMoveOutput(BaseModel):
    """Output schema for file move tool"""
    source: str = Field(..., description="Original source path")
    destination: str = Field(..., description="New destination path")
    overwritten: bool = Field(..., description="Whether destination was overwritten")


class FileMoveTool(ToolBase):
    """Tool for moving/renaming files"""

    @property
    def name(self) -> str:
        return "file_move"

    @property
    def description(self) -> str:
        return "Move or rename a file. Can overwrite destination if specified."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileMoveInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileMoveOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

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
        """Execute file move"""
        source = input_data["source"]
        destination = input_data["destination"]
        overwrite = input_data["overwrite"]

        try:
            # Resolve paths
            source_path = Path(source).resolve()
            dest_path = Path(destination).resolve()

            # Check source exists
            if not source_path.exists():
                return self.create_result(
                    success=False,
                    error_message=f"Source file not found: {source}",
                )

            # Check source is file
            if not source_path.is_file():
                return self.create_result(
                    success=False,
                    error_message=f"Source is not a file: {source}",
                )

            # Check destination
            dest_exists = dest_path.exists()
            if dest_exists and not overwrite:
                return self.create_result(
                    success=False,
                    error_message=f"Destination already exists and overwrite=False: {destination}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(source_path).startswith(banned) or str(dest_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: Path in banned folder {banned}",
                        )

            # Create destination parent directory if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Move file
            shutil.move(str(source_path), str(dest_path))

            return self.create_result(
                success=True,
                result_data={
                    "source": str(source_path),
                    "destination": str(dest_path),
                    "overwritten": dest_exists,
                },
                output_text=f"Moved {source_path.name} to {dest_path}",
                files_affected=[str(source_path), str(dest_path)],
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to move file: {str(e)}",
            )


# ===== FILE COPY TOOL =====

class FileCopyInput(BaseModel):
    """Input schema for file copy tool"""
    source: str = Field(..., description="Source file path")
    destination: str = Field(..., description="Destination file path")
    overwrite: bool = Field(default=False, description="Overwrite destination if exists")
    preserve_metadata: bool = Field(default=True, description="Preserve file metadata")


class FileCopyOutput(BaseModel):
    """Output schema for file copy tool"""
    source: str = Field(..., description="Source path")
    destination: str = Field(..., description="Destination path")
    size: int = Field(..., description="Bytes copied")
    overwritten: bool = Field(..., description="Whether destination was overwritten")


class FileCopyTool(ToolBase):
    """Tool for copying files"""

    @property
    def name(self) -> str:
        return "file_copy"

    @property
    def description(self) -> str:
        return "Copy a file to a new location. Can preserve metadata and overwrite destination."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileCopyInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileCopyOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

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
        """Execute file copy"""
        source = input_data["source"]
        destination = input_data["destination"]
        overwrite = input_data["overwrite"]
        preserve_metadata = input_data["preserve_metadata"]

        try:
            # Resolve paths
            source_path = Path(source).resolve()
            dest_path = Path(destination).resolve()

            # Check source exists
            if not source_path.exists():
                return self.create_result(
                    success=False,
                    error_message=f"Source file not found: {source}",
                )

            # Check source is file
            if not source_path.is_file():
                return self.create_result(
                    success=False,
                    error_message=f"Source is not a file: {source}",
                )

            # Check destination
            dest_exists = dest_path.exists()
            if dest_exists and not overwrite:
                return self.create_result(
                    success=False,
                    error_message=f"Destination already exists and overwrite=False: {destination}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(source_path).startswith(banned) or str(dest_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: Path in banned folder {banned}",
                        )

            # Create destination parent directory if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy file
            if preserve_metadata:
                shutil.copy2(str(source_path), str(dest_path))
            else:
                shutil.copy(str(source_path), str(dest_path))

            # Get file size
            size = dest_path.stat().st_size

            return self.create_result(
                success=True,
                result_data={
                    "source": str(source_path),
                    "destination": str(dest_path),
                    "size": size,
                    "overwritten": dest_exists,
                },
                output_text=f"Copied {size} bytes from {source_path.name} to {dest_path}",
                files_affected=[str(dest_path)],
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to copy file: {str(e)}",
            )
