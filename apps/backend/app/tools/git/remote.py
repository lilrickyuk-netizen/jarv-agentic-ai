"""
JARV Backend - Git Remote Tools

Git remote operations: push, pull, fetch.
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.tools.git.basic import run_git_command

logger = logging.getLogger(__name__)


# ===== GIT PUSH TOOL =====

class GitPushInput(BaseModel):
    """Input schema for git push tool"""
    repo_path: str = Field(..., description="Repository path")
    remote: str = Field(default="origin", description="Remote name")
    branch: Optional[str] = Field(None, description="Branch to push")
    force: bool = Field(default=False, description="Force push")
    set_upstream: bool = Field(default=False, description="Set upstream tracking")


class GitPushOutput(BaseModel):
    """Output schema for git push tool"""
    remote: str = Field(..., description="Remote name")
    branch: str = Field(..., description="Branch pushed")
    output: str = Field(..., description="Git output")


class GitPushTool(ToolBase):
    """Tool for pushing to remote repository"""

    @property
    def name(self) -> str:
        return "git_push"

    @property
    def description(self) -> str:
        return "Push commits to remote repository."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitPushInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitPushOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True  # Network + potentially destructive

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute git push"""
        repo_path = input_data["repo_path"]
        remote = input_data["remote"]
        branch = input_data.get("branch")
        force = input_data["force"]
        set_upstream = input_data["set_upstream"]

        try:
            cmd = ["git", "push"]
            if set_upstream:
                cmd.append("-u")
            if force:
                cmd.append("--force")
            cmd.append(remote)
            if branch:
                cmd.append(branch)

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path, timeout=60)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Git push failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"remote": remote, "branch": branch or "current", "output": stderr},
                output_text=f"Pushed to {remote}",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to push: {str(e)}")


# ===== GIT PULL TOOL =====

class GitPullInput(BaseModel):
    """Input schema for git pull tool"""
    repo_path: str = Field(..., description="Repository path")
    remote: str = Field(default="origin", description="Remote name")
    branch: Optional[str] = Field(None, description="Branch to pull")
    rebase: bool = Field(default=False, description="Use rebase instead of merge")


class GitPullOutput(BaseModel):
    """Output schema for git pull tool"""
    remote: str = Field(..., description="Remote name")
    output: str = Field(..., description="Git output")


class GitPullTool(ToolBase):
    """Tool for pulling from remote repository"""

    @property
    def name(self) -> str:
        return "git_pull"

    @property
    def description(self) -> str:
        return "Pull changes from remote repository."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitPullInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitPullOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute git pull"""
        repo_path = input_data["repo_path"]
        remote = input_data["remote"]
        branch = input_data.get("branch")
        rebase = input_data["rebase"]

        try:
            cmd = ["git", "pull"]
            if rebase:
                cmd.append("--rebase")
            cmd.append(remote)
            if branch:
                cmd.append(branch)

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path, timeout=60)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Git pull failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"remote": remote, "output": stdout + stderr},
                output_text=f"Pulled from {remote}",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to pull: {str(e)}")


# ===== GIT FETCH TOOL =====

class GitFetchInput(BaseModel):
    """Input schema for git fetch tool"""
    repo_path: str = Field(..., description="Repository path")
    remote: str = Field(default="origin", description="Remote name")
    prune: bool = Field(default=False, description="Prune deleted branches")


class GitFetchOutput(BaseModel):
    """Output schema for git fetch tool"""
    remote: str = Field(..., description="Remote name")
    output: str = Field(..., description="Git output")


class GitFetchTool(ToolBase):
    """Tool for fetching from remote repository"""

    @property
    def name(self) -> str:
        return "git_fetch"

    @property
    def description(self) -> str:
        return "Fetch changes from remote repository without merging."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitFetchInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitFetchOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute git fetch"""
        repo_path = input_data["repo_path"]
        remote = input_data["remote"]
        prune = input_data["prune"]

        try:
            cmd = ["git", "fetch"]
            if prune:
                cmd.append("--prune")
            cmd.append(remote)

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path, timeout=60)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Git fetch failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"remote": remote, "output": stderr},
                output_text=f"Fetched from {remote}",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to fetch: {str(e)}")
