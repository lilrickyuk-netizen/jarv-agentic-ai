"""
JARV Backend - Advanced File Tools

Advanced file tools: watch, diff, patch.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from pathlib import Path
import difflib
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


# ===== FILE WATCH TOOL =====

class FileWatchInput(BaseModel):
    """Input schema for file watch tool"""
    path: str = Field(..., description="Path to file or directory to watch")
    timeout: int = Field(default=30, ge=1, le=300, description="Watch timeout in seconds")


class FileWatchOutput(BaseModel):
    """Output schema for file watch tool"""
    path: str = Field(..., description="Watched path")
    changed: bool = Field(..., description="Whether path changed during watch period")
    message: str = Field(..., description="Status message")


class FileWatchTool(ToolBase):
    """Tool for watching files for changes"""

    @property
    def name(self) -> str:
        return "file_watch"

    @property
    def description(self) -> str:
        return "Watch a file or directory for changes. Returns when change detected or timeout reached."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileWatchInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileWatchOutput

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
        """Execute file watch"""
        path = input_data["path"]
        timeout = input_data["timeout"]

        try:
            # Resolve path
            watch_path = Path(path).resolve()

            # Check if path exists
            if not watch_path.exists():
                return self.create_result(
                    success=False,
                    error_message=f"Path not found: {path}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(watch_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: Path in banned folder {banned}",
                        )

            # Get initial modification time
            initial_mtime = watch_path.stat().st_mtime

            # Note: Full implementation would use watchdog library or inotify
            # For now, return immediate status with instructions
            return self.create_result(
                success=True,
                result_data={
                    "path": str(watch_path),
                    "changed": False,
                    "message": f"File watch not yet fully implemented. Initial mtime: {initial_mtime}",
                },
                output_text=f"Watch started for {watch_path.name} (implementation pending)",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to watch file: {str(e)}",
            )


# ===== FILE DIFF TOOL =====

class FileDiffInput(BaseModel):
    """Input schema for file diff tool"""
    file1: str = Field(..., description="First file path")
    file2: str = Field(..., description="Second file path")
    context_lines: int = Field(default=3, ge=0, le=10, description="Context lines in diff")
    unified: bool = Field(default=True, description="Use unified diff format")


class FileDiffOutput(BaseModel):
    """Output schema for file diff tool"""
    file1: str = Field(..., description="First file path")
    file2: str = Field(..., description="Second file path")
    identical: bool = Field(..., description="Whether files are identical")
    diff: str = Field(..., description="Diff output")
    changes: int = Field(..., description="Number of changed lines")


class FileDiffTool(ToolBase):
    """Tool for comparing two files"""

    @property
    def name(self) -> str:
        return "file_diff"

    @property
    def description(self) -> str:
        return "Compare two files and generate diff. Shows additions, deletions, and changes."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileDiffInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileDiffOutput

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
        """Execute file diff"""
        file1 = input_data["file1"]
        file2 = input_data["file2"]
        context_lines = input_data["context_lines"]
        unified = input_data["unified"]

        try:
            # Resolve paths
            path1 = Path(file1).resolve()
            path2 = Path(file2).resolve()

            # Check files exist
            if not path1.exists():
                return self.create_result(
                    success=False,
                    error_message=f"First file not found: {file1}",
                )

            if not path2.exists():
                return self.create_result(
                    success=False,
                    error_message=f"Second file not found: {file2}",
                )

            # Check they are files
            if not path1.is_file() or not path2.is_file():
                return self.create_result(
                    success=False,
                    error_message="Both paths must be files",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(path1).startswith(banned) or str(path2).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: Path in banned folder {banned}",
                        )

            # Read files
            content1 = path1.read_text(encoding="utf-8").splitlines(keepends=True)
            content2 = path2.read_text(encoding="utf-8").splitlines(keepends=True)

            # Generate diff
            if unified:
                diff_lines = list(
                    difflib.unified_diff(
                        content1,
                        content2,
                        fromfile=str(path1),
                        tofile=str(path2),
                        n=context_lines,
                    )
                )
            else:
                diff_lines = list(
                    difflib.context_diff(
                        content1,
                        content2,
                        fromfile=str(path1),
                        tofile=str(path2),
                        n=context_lines,
                    )
                )

            # Check if identical
            identical = len(diff_lines) == 0

            # Count changes
            changes = sum(
                1
                for line in diff_lines
                if line.startswith("+") or line.startswith("-")
            )

            diff_text = "".join(diff_lines) if diff_lines else "Files are identical"

            return self.create_result(
                success=True,
                result_data={
                    "file1": str(path1),
                    "file2": str(path2),
                    "identical": identical,
                    "diff": diff_text,
                    "changes": changes,
                },
                output_text=f"Diff: {changes} changes between {path1.name} and {path2.name}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to diff files: {str(e)}",
            )


# ===== FILE PATCH TOOL =====

class FilePatchInput(BaseModel):
    """Input schema for file patch tool"""
    file: str = Field(..., description="File to patch")
    patch: str = Field(..., description="Patch content (unified diff format)")
    dry_run: bool = Field(default=False, description="Validate without applying")


class FilePatchOutput(BaseModel):
    """Output schema for file patch tool"""
    file: str = Field(..., description="Patched file path")
    applied: bool = Field(..., description="Whether patch was applied")
    changes: int = Field(..., description="Number of changes made")
    message: str = Field(..., description="Status message")


class FilePatchTool(ToolBase):
    """Tool for applying patches to files"""

    @property
    def name(self) -> str:
        return "file_patch"

    @property
    def description(self) -> str:
        return "Apply a patch to a file. Supports unified diff format. Can dry-run to validate."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FilePatchInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FilePatchOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return True  # Modifies files

    @property
    def category(self) -> str:
        return "file"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute file patch"""
        file = input_data["file"]
        patch = input_data["patch"]
        dry_run = input_data["dry_run"]

        try:
            # Resolve path
            file_path = Path(file).resolve()

            # Check file exists
            if not file_path.exists():
                return self.create_result(
                    success=False,
                    error_message=f"File not found: {file}",
                )

            # Check it's a file
            if not file_path.is_file():
                return self.create_result(
                    success=False,
                    error_message=f"Path is not a file: {file}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(file_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: File in banned folder {banned}",
                        )

            # Note: Full implementation would use patch library or subprocess
            # For now, return status with instructions
            if dry_run:
                message = "Patch validation not yet fully implemented (dry_run=True)"
            else:
                message = "Patch application not yet fully implemented"

            return self.create_result(
                success=True,
                result_data={
                    "file": str(file_path),
                    "applied": False,
                    "changes": 0,
                    "message": message,
                },
                output_text=message,
                files_affected=[str(file_path)] if not dry_run else [],
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to patch file: {str(e)}",
            )
