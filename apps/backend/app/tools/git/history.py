"""
JARV Backend - Git History Tools

Git history operations: diff, log, blame.
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.tools.git.basic import run_git_command

logger = logging.getLogger(__name__)


class GitDiffInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    ref1: Optional[str] = Field(None, description="First ref (default: HEAD)")
    ref2: Optional[str] = Field(None, description="Second ref (default: working tree)")
    files: Optional[list] = Field(None, description="Specific files to diff")


class GitDiffOutput(BaseModel):
    diff: str = Field(..., description="Diff output")


class GitDiffTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_diff"

    @property
    def description(self) -> str:
        return "Show differences between commits, branches, or working tree."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitDiffInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitDiffOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        repo_path = input_data["repo_path"]
        ref1 = input_data.get("ref1")
        ref2 = input_data.get("ref2")
        files = input_data.get("files") or []

        try:
            cmd = ["git", "diff"]
            if ref1:
                cmd.append(ref1)
            if ref2:
                cmd.append(ref2)
            cmd.extend(files)

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Git diff failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"diff": stdout},
                output_text="Generated diff",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")


class GitLogInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    max_count: int = Field(default=10, description="Maximum commits to show")
    oneline: bool = Field(default=False, description="Show one line per commit")
    author: Optional[str] = Field(None, description="Filter by author")


class GitLogOutput(BaseModel):
    log: str = Field(..., description="Log output")


class GitLogTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_log"

    @property
    def description(self) -> str:
        return "Show commit history."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitLogInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitLogOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        repo_path = input_data["repo_path"]
        max_count = input_data["max_count"]
        oneline = input_data["oneline"]
        author = input_data.get("author")

        try:
            cmd = ["git", "log", f"-{max_count}"]
            if oneline:
                cmd.append("--oneline")
            if author:
                cmd.extend(["--author", author])

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Git log failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"log": stdout},
                output_text=f"Retrieved {max_count} commits",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")


class GitBlameInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    file: str = Field(..., description="File to blame")


class GitBlameOutput(BaseModel):
    blame: str = Field(..., description="Blame output")


class GitBlameTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_blame"

    @property
    def description(self) -> str:
        return "Show line-by-line authorship for a file."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitBlameInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitBlameOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        repo_path = input_data["repo_path"]
        file = input_data["file"]

        try:
            cmd = ["git", "blame", file]
            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Git blame failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"blame": stdout},
                output_text=f"Generated blame for {file}",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")
