"""
JARV Backend - Git Branch Tools

Git branch operations: branch, checkout, merge, rebase.
"""
from typing import Dict, Any, Type, Optional, List
from pydantic import BaseModel, Field
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.tools.git.basic import run_git_command

logger = logging.getLogger(__name__)


class GitBranchInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    action: str = Field(default="list", description="Action: list, create, delete")
    branch_name: Optional[str] = Field(None, description="Branch name for create/delete")
    force: bool = Field(default=False, description="Force delete unmerged branch")


class GitBranchOutput(BaseModel):
    branches: List[str] = Field(default_factory=list, description="Branch list")
    current_branch: Optional[str] = Field(None, description="Current branch")
    output: str = Field(..., description="Git output")


class GitBranchTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_branch"

    @property
    def description(self) -> str:
        return "Manage git branches: list, create, delete."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitBranchInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitBranchOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        repo_path = input_data["repo_path"]
        action = input_data["action"]
        branch_name = input_data.get("branch_name")
        force = input_data["force"]

        try:
            if action == "list":
                cmd = ["git", "branch"]
            elif action == "create":
                if not branch_name:
                    return self.create_result(success=False, error_message="branch_name required for create")
                cmd = ["git", "branch", branch_name]
            elif action == "delete":
                if not branch_name:
                    return self.create_result(success=False, error_message="branch_name required for delete")
                cmd = ["git", "branch", "-D" if force else "-d", branch_name]
            else:
                return self.create_result(success=False, error_message=f"Unknown action: {action}")

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Git branch failed: {stderr}")

            branches = []
            current = None
            if action == "list":
                for line in stdout.splitlines():
                    if line.startswith("*"):
                        current = line[2:].strip()
                        branches.append(current)
                    else:
                        branches.append(line.strip())

            return self.create_result(
                success=True,
                result_data={"branches": branches, "current_branch": current, "output": stdout},
                output_text=f"Branch {action} successful",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")


class GitCheckoutInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    branch: str = Field(..., description="Branch name")
    create: bool = Field(default=False, description="Create branch if doesn't exist")


class GitCheckoutOutput(BaseModel):
    branch: str = Field(..., description="Branch checked out")
    created: bool = Field(..., description="Whether branch was created")
    output: str = Field(..., description="Git output")


class GitCheckoutTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_checkout"

    @property
    def description(self) -> str:
        return "Checkout a git branch."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitCheckoutInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitCheckoutOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        repo_path = input_data["repo_path"]
        branch = input_data["branch"]
        create = input_data["create"]

        try:
            cmd = ["git", "checkout"]
            if create:
                cmd.append("-b")
            cmd.append(branch)

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Checkout failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"branch": branch, "created": create, "output": stderr},
                output_text=f"Checked out branch {branch}",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")


class GitMergeInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    branch: str = Field(..., description="Branch to merge")
    no_ff: bool = Field(default=False, description="No fast-forward merge")
    message: Optional[str] = Field(None, description="Merge commit message")


class GitMergeOutput(BaseModel):
    branch: str = Field(..., description="Branch merged")
    output: str = Field(..., description="Git output")


class GitMergeTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_merge"

    @property
    def description(self) -> str:
        return "Merge a branch into current branch."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitMergeInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitMergeOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return True  # Merging can be complex

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        repo_path = input_data["repo_path"]
        branch = input_data["branch"]
        no_ff = input_data["no_ff"]
        message = input_data.get("message")

        try:
            cmd = ["git", "merge"]
            if no_ff:
                cmd.append("--no-ff")
            if message:
                cmd.extend(["-m", message])
            cmd.append(branch)

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Merge failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"branch": branch, "output": stdout},
                output_text=f"Merged {branch}",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")


class GitRebaseInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    branch: str = Field(..., description="Branch to rebase onto")
    interactive: bool = Field(default=False, description="Interactive rebase")


class GitRebaseOutput(BaseModel):
    output: str = Field(..., description="Git output")


class GitRebaseTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_rebase"

    @property
    def description(self) -> str:
        return "Rebase current branch onto another branch."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitRebaseInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitRebaseOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def requires_approval(self) -> bool:
        return True  # Rebasing rewrites history

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        repo_path = input_data["repo_path"]
        branch = input_data["branch"]
        interactive = input_data["interactive"]

        try:
            cmd = ["git", "rebase"]
            if interactive:
                cmd.append("-i")
            cmd.append(branch)

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Rebase failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"output": stdout + stderr},
                output_text=f"Rebased onto {branch}",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")
