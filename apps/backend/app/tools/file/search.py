"""
JARV Backend - File Search Tools

File search and discovery tools: search, grep, list, tree.
"""
from typing import Dict, Any, Type, List
from pydantic import BaseModel, Field
from pathlib import Path
import re
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


# ===== FILE SEARCH TOOL =====

class FileSearchInput(BaseModel):
    """Input schema for file search tool"""
    directory: str = Field(..., description="Directory to search in")
    pattern: str = Field(..., description="File name pattern (glob pattern)")
    recursive: bool = Field(default=True, description="Search recursively")
    max_results: int = Field(default=100, ge=1, le=1000, description="Maximum results")


class FileSearchOutput(BaseModel):
    """Output schema for file search tool"""
    files: List[str] = Field(..., description="List of matching file paths")
    count: int = Field(..., description="Number of files found")
    truncated: bool = Field(..., description="Whether results were truncated")


class FileSearchTool(ToolBase):
    """Tool for searching files by name pattern"""

    @property
    def name(self) -> str:
        return "file_search"

    @property
    def description(self) -> str:
        return "Search for files by name pattern using glob syntax (e.g., *.py, test_*.txt)."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileSearchInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileSearchOutput

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
        """Execute file search"""
        directory = input_data["directory"]
        pattern = input_data["pattern"]
        recursive = input_data["recursive"]
        max_results = input_data["max_results"]

        try:
            # Resolve directory
            dir_path = Path(directory).resolve()

            # Check directory exists
            if not dir_path.exists():
                return self.create_result(
                    success=False,
                    error_message=f"Directory not found: {directory}",
                )

            # Check it's a directory
            if not dir_path.is_dir():
                return self.create_result(
                    success=False,
                    error_message=f"Path is not a directory: {directory}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(dir_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: Directory in banned folder {banned}",
                        )

            # Search for files
            files = []
            if recursive:
                matches = dir_path.rglob(pattern)
            else:
                matches = dir_path.glob(pattern)

            for match in matches:
                if match.is_file():
                    files.append(str(match))
                    if len(files) >= max_results:
                        break

            truncated = len(files) >= max_results

            return self.create_result(
                success=True,
                result_data={
                    "files": files,
                    "count": len(files),
                    "truncated": truncated,
                },
                output_text=f"Found {len(files)} files matching '{pattern}'",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to search files: {str(e)}",
            )


# ===== FILE GREP TOOL =====

class FileGrepInput(BaseModel):
    """Input schema for file grep tool"""
    path: str = Field(..., description="File or directory path to search")
    pattern: str = Field(..., description="Regex pattern to search for")
    case_sensitive: bool = Field(default=True, description="Case sensitive search")
    max_matches: int = Field(default=100, ge=1, le=1000, description="Maximum matches")
    context_lines: int = Field(default=0, ge=0, le=5, description="Context lines before/after")


class FileGrepMatch(BaseModel):
    """Single grep match"""
    file: str = Field(..., description="File path")
    line_number: int = Field(..., description="Line number")
    line: str = Field(..., description="Matching line")
    context_before: List[str] = Field(default_factory=list, description="Lines before match")
    context_after: List[str] = Field(default_factory=list, description="Lines after match")


class FileGrepOutput(BaseModel):
    """Output schema for file grep tool"""
    matches: List[FileGrepMatch] = Field(..., description="List of matches")
    count: int = Field(..., description="Number of matches")
    files_searched: int = Field(..., description="Number of files searched")
    truncated: bool = Field(..., description="Whether results were truncated")


class FileGrepTool(ToolBase):
    """Tool for searching file contents with regex"""

    @property
    def name(self) -> str:
        return "file_grep"

    @property
    def description(self) -> str:
        return "Search file contents using regex patterns. Can search single file or directory."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileGrepInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileGrepOutput

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
        """Execute file grep"""
        path = input_data["path"]
        pattern = input_data["pattern"]
        case_sensitive = input_data["case_sensitive"]
        max_matches = input_data["max_matches"]
        context_lines = input_data["context_lines"]

        try:
            # Compile regex
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)

            # Resolve path
            search_path = Path(path).resolve()

            # Check path exists
            if not search_path.exists():
                return self.create_result(
                    success=False,
                    error_message=f"Path not found: {path}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(search_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: Path in banned folder {banned}",
                        )

            # Get files to search
            if search_path.is_file():
                files = [search_path]
            else:
                files = [f for f in search_path.rglob("*") if f.is_file()]

            # Search files
            matches = []
            files_searched = 0

            for file_path in files:
                if len(matches) >= max_matches:
                    break

                try:
                    # Read file
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    lines = content.splitlines()
                    files_searched += 1

                    # Search lines
                    for i, line in enumerate(lines):
                        if len(matches) >= max_matches:
                            break

                        if regex.search(line):
                            # Get context
                            context_before = []
                            context_after = []

                            if context_lines > 0:
                                start = max(0, i - context_lines)
                                end = min(len(lines), i + context_lines + 1)
                                context_before = lines[start:i]
                                context_after = lines[i + 1:end]

                            matches.append(
                                FileGrepMatch(
                                    file=str(file_path),
                                    line_number=i + 1,
                                    line=line,
                                    context_before=context_before,
                                    context_after=context_after,
                                ).dict()
                            )

                except Exception as e:
                    # Skip files we can't read
                    logger.debug(f"Skipped file {file_path}: {e}")
                    continue

            truncated = len(matches) >= max_matches

            return self.create_result(
                success=True,
                result_data={
                    "matches": matches,
                    "count": len(matches),
                    "files_searched": files_searched,
                    "truncated": truncated,
                },
                output_text=f"Found {len(matches)} matches in {files_searched} files",
            )

        except re.error as e:
            return self.create_result(
                success=False,
                error_message=f"Invalid regex pattern: {str(e)}",
            )
        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to grep files: {str(e)}",
            )


# ===== FILE LIST TOOL =====

class FileListInput(BaseModel):
    """Input schema for file list tool"""
    directory: str = Field(..., description="Directory to list")
    recursive: bool = Field(default=False, description="List recursively")
    include_hidden: bool = Field(default=False, description="Include hidden files")
    max_results: int = Field(default=1000, ge=1, le=10000, description="Maximum results")


class FileListEntry(BaseModel):
    """Single file list entry"""
    path: str = Field(..., description="File path")
    name: str = Field(..., description="File name")
    type: str = Field(..., description="Type: file or directory")
    size: int = Field(..., description="Size in bytes (0 for directories)")


class FileListOutput(BaseModel):
    """Output schema for file list tool"""
    entries: List[FileListEntry] = Field(..., description="Directory entries")
    count: int = Field(..., description="Number of entries")
    truncated: bool = Field(..., description="Whether results were truncated")


class FileListTool(ToolBase):
    """Tool for listing directory contents"""

    @property
    def name(self) -> str:
        return "file_list"

    @property
    def description(self) -> str:
        return "List contents of a directory. Can list recursively and include hidden files."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileListInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileListOutput

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
        """Execute file list"""
        directory = input_data["directory"]
        recursive = input_data["recursive"]
        include_hidden = input_data["include_hidden"]
        max_results = input_data["max_results"]

        try:
            # Resolve directory
            dir_path = Path(directory).resolve()

            # Check directory exists
            if not dir_path.exists():
                return self.create_result(
                    success=False,
                    error_message=f"Directory not found: {directory}",
                )

            # Check it's a directory
            if not dir_path.is_dir():
                return self.create_result(
                    success=False,
                    error_message=f"Path is not a directory: {directory}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(dir_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: Directory in banned folder {banned}",
                        )

            # List entries
            entries = []
            if recursive:
                paths = dir_path.rglob("*")
            else:
                paths = dir_path.iterdir()

            for p in paths:
                # Skip hidden files if requested
                if not include_hidden and p.name.startswith("."):
                    continue

                # Get entry info
                entry = FileListEntry(
                    path=str(p),
                    name=p.name,
                    type="directory" if p.is_dir() else "file",
                    size=p.stat().st_size if p.is_file() else 0,
                ).dict()

                entries.append(entry)

                if len(entries) >= max_results:
                    break

            truncated = len(entries) >= max_results

            return self.create_result(
                success=True,
                result_data={
                    "entries": entries,
                    "count": len(entries),
                    "truncated": truncated,
                },
                output_text=f"Listed {len(entries)} entries in {dir_path.name}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to list directory: {str(e)}",
            )


# ===== FILE TREE TOOL =====

class FileTreeInput(BaseModel):
    """Input schema for file tree tool"""
    directory: str = Field(..., description="Directory to show tree for")
    max_depth: int = Field(default=3, ge=1, le=10, description="Maximum depth")
    include_hidden: bool = Field(default=False, description="Include hidden files")


class FileTreeOutput(BaseModel):
    """Output schema for file tree tool"""
    tree: str = Field(..., description="Tree representation as text")
    total_files: int = Field(..., description="Total files")
    total_dirs: int = Field(..., description="Total directories")


class FileTreeTool(ToolBase):
    """Tool for displaying directory tree structure"""

    @property
    def name(self) -> str:
        return "file_tree"

    @property
    def description(self) -> str:
        return "Display directory structure as a tree. Useful for understanding project layout."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FileTreeInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FileTreeOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "file"

    def _build_tree(
        self,
        path: Path,
        prefix: str,
        max_depth: int,
        current_depth: int,
        include_hidden: bool,
        stats: Dict[str, int],
    ) -> List[str]:
        """Recursively build tree structure"""
        if current_depth >= max_depth:
            return []

        lines = []
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))

            # Filter hidden files
            if not include_hidden:
                entries = [e for e in entries if not e.name.startswith(".")]

            for i, entry in enumerate(entries):
                is_last = i == len(entries) - 1
                connector = "└── " if is_last else "├── "
                extension = "    " if is_last else "│   "

                # Add entry
                if entry.is_dir():
                    lines.append(f"{prefix}{connector}{entry.name}/")
                    stats["dirs"] += 1

                    # Recurse
                    lines.extend(
                        self._build_tree(
                            entry,
                            prefix + extension,
                            max_depth,
                            current_depth + 1,
                            include_hidden,
                            stats,
                        )
                    )
                else:
                    lines.append(f"{prefix}{connector}{entry.name}")
                    stats["files"] += 1

        except PermissionError:
            lines.append(f"{prefix}[Permission Denied]")

        return lines

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute file tree"""
        directory = input_data["directory"]
        max_depth = input_data["max_depth"]
        include_hidden = input_data["include_hidden"]

        try:
            # Resolve directory
            dir_path = Path(directory).resolve()

            # Check directory exists
            if not dir_path.exists():
                return self.create_result(
                    success=False,
                    error_message=f"Directory not found: {directory}",
                )

            # Check it's a directory
            if not dir_path.is_dir():
                return self.create_result(
                    success=False,
                    error_message=f"Path is not a directory: {directory}",
                )

            # Check folder permissions
            if context.banned_folders:
                for banned in context.banned_folders:
                    if str(dir_path).startswith(banned):
                        return self.create_result(
                            success=False,
                            error_message=f"Access denied: Directory in banned folder {banned}",
                        )

            # Build tree
            stats = {"files": 0, "dirs": 0}
            tree_lines = [f"{dir_path.name}/"]
            tree_lines.extend(
                self._build_tree(
                    dir_path,
                    "",
                    max_depth,
                    0,
                    include_hidden,
                    stats,
                )
            )

            tree = "\n".join(tree_lines)

            return self.create_result(
                success=True,
                result_data={
                    "tree": tree,
                    "total_files": stats["files"],
                    "total_dirs": stats["dirs"],
                },
                output_text=f"Tree: {stats['dirs']} directories, {stats['files']} files",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to generate tree: {str(e)}",
            )
