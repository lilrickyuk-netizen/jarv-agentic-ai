"""
JARV Backend - Basic File Tools

Basic file operation tools: read, write, append.
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
from pathlib import Path
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


# ===== FILE READ TOOL =====

class FileReadInput(BaseModel):
    """Input schema for file read tool"""
    path: str = Field(..., description="Path to file to read")
    encoding: str = Field(default="utf-8", description="File encoding")
    max_size_mb: int = Field(default=10, ge=1, le=100, description="Maximum file size in MB")


class FileReadOutput(BaseModel):
    """Output schema for file read tool"""
    content: str = Field(..., description="File content")
    size: int = Field(..., description="File size in bytes")
    lines: int = Field(..., description="Number of lines")
    path: str = Field(..., description="Absolute path to file")


class FileReadTool(ToolBase):
    """Tool for reading file contents"""

    @property
    def name(self) -> str:
        return "file_read"

    @property
    def description(self) -> str:
        return "Read contents of a file. Supports text files with configurable encoding."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileReadInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileReadOutput

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
        """Execute file read"""
        path = input_data["path"]
        encoding = input_data["encoding"]
        max_size_mb = input_data["max_size_mb"]

        try:
            # Resolve path
            file_path = Path(path).resolve()

            # Check if file exists
            if not file_path.exists():
                return self.create_result(
                    success=False,
                    error_message=f"File not found: {path}",
                )

            # Check if it's a file (not directory)
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

            # Check file size
            size = file_path.stat().st_size
            max_size_bytes = max_size_mb * 1024 * 1024
            if size > max_size_bytes:
                return self.create_result(
                    success=False,
                    error_message=f"File too large: {size} bytes (max: {max_size_bytes} bytes)",
                )

            # Read file
            content = file_path.read_text(encoding=encoding)
            lines = len(content.splitlines())

            return self.create_result(
                success=True,
                result_data={
                    "content": content,
                    "size": size,
                    "lines": lines,
                    "path": str(file_path),
                },
                output_text=f"Read {size} bytes from {file_path.name}",
            )

        except UnicodeDecodeError as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to decode file with encoding {encoding}: {str(e)}",
            )
        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to read file: {str(e)}",
            )


# ===== FILE WRITE TOOL =====

class FileWriteInput(BaseModel):
    """Input schema for file write tool"""
    path: str = Field(..., description="Path to file to write")
    content: str = Field(..., description="Content to write to file")
    encoding: str = Field(default="utf-8", description="File encoding")
    create_dirs: bool = Field(default=True, description="Create parent directories if needed")
    overwrite: bool = Field(default=True, description="Overwrite if file exists")


class FileWriteOutput(BaseModel):
    """Output schema for file write tool"""
    path: str = Field(..., description="Absolute path to file")
    size: int = Field(..., description="Bytes written")
    lines: int = Field(..., description="Lines written")
    created: bool = Field(..., description="Whether file was created (vs overwritten)")


class FileWriteTool(ToolBase):
    """Tool for writing content to files"""

    @property
    def name(self) -> str:
        return "file_write"

    @property
    def description(self) -> str:
        return "Write content to a file. Can create directories and overwrite existing files."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileWriteInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileWriteOutput

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
        """Execute file write"""
        path = input_data["path"]
        content = input_data["content"]
        encoding = input_data["encoding"]
        create_dirs = input_data["create_dirs"]
        overwrite = input_data["overwrite"]

        try:
            # Resolve path
            file_path = Path(path).resolve()

            # Check if file exists
            file_exists = file_path.exists()

            # Check overwrite permission
            if file_exists and not overwrite:
                return self.create_result(
                    success=False,
                    error_message=f"File already exists and overwrite=False: {path}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(file_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: File in banned folder {banned}",
                        )

            # Create parent directories if needed
            if create_dirs:
                file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            file_path.write_text(content, encoding=encoding)

            # Get file stats
            size = file_path.stat().st_size
            lines = len(content.splitlines())

            return self.create_result(
                success=True,
                result_data={
                    "path": str(file_path),
                    "size": size,
                    "lines": lines,
                    "created": not file_exists,
                },
                output_text=f"Wrote {size} bytes to {file_path.name}",
                files_affected=[str(file_path)],
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to write file: {str(e)}",
            )


# ===== FILE APPEND TOOL =====

class FileAppendInput(BaseModel):
    """Input schema for file append tool"""
    path: str = Field(..., description="Path to file to append to")
    content: str = Field(..., description="Content to append to file")
    encoding: str = Field(default="utf-8", description="File encoding")
    create_if_missing: bool = Field(default=True, description="Create file if it doesn't exist")
    add_newline: bool = Field(default=True, description="Add newline before content")


class FileAppendOutput(BaseModel):
    """Output schema for file append tool"""
    path: str = Field(..., description="Absolute path to file")
    appended_size: int = Field(..., description="Bytes appended")
    total_size: int = Field(..., description="Total file size after append")
    created: bool = Field(..., description="Whether file was created")


class FileAppendTool(ToolBase):
    """Tool for appending content to files"""

    @property
    def name(self) -> str:
        return "file_append"

    @property
    def description(self) -> str:
        return "Append content to the end of a file. Can create file if missing."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileAppendInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileAppendOutput

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
        """Execute file append"""
        path = input_data["path"]
        content = input_data["content"]
        encoding = input_data["encoding"]
        create_if_missing = input_data["create_if_missing"]
        add_newline = input_data["add_newline"]

        try:
            # Resolve path
            file_path = Path(path).resolve()

            # Check if file exists
            file_exists = file_path.exists()

            # Check if we should create
            if not file_exists and not create_if_missing:
                return self.create_result(
                    success=False,
                    error_message=f"File not found and create_if_missing=False: {path}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(file_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: File in banned folder {banned}",
                        )

            # Prepare content to append
            append_content = content
            if add_newline and file_exists and file_path.stat().st_size > 0:
                # Add newline before content if file exists and is not empty
                append_content = "\n" + content

            # Append to file
            with open(file_path, "a", encoding=encoding) as f:
                f.write(append_content)

            # Get file stats
            total_size = file_path.stat().st_size
            appended_size = len(append_content.encode(encoding))

            return self.create_result(
                success=True,
                result_data={
                    "path": str(file_path),
                    "appended_size": appended_size,
                    "total_size": total_size,
                    "created": not file_exists,
                },
                output_text=f"Appended {appended_size} bytes to {file_path.name}",
                files_affected=[str(file_path)],
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to append to file: {str(e)}",
            )
