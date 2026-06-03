"""
JARV Backend - Advanced Git Tools

Advanced git operations: tag, stash, reset, revert, config.
"""
from typing import Dict, Any, Type, Optional, List
from pydantic import BaseModel, Field
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.tools.git.basic import run_git_command

logger = logging.getLogger(__name__)


class GitTagInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    action: str = Field(default="list", description="Action: list, create, delete")
    tag_name: Optional[str] = Field(None, description="Tag name")
    message: Optional[str] = Field(None, description="Tag message (annotated tag)")


class GitTagOutput(BaseModel):
    tags: List[str] = Field(default_factory=list, description="Tag list")
    output: str = Field(..., description="Git output")


class GitTagTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_tag"

    @property
    def description(self) -> str:
        return "Manage git tags: list, create, delete."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitTagInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitTagOutput

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
        tag_name = input_data.get("tag_name")
        message = input_data.get("message")

        try:
            if action == "list":
                cmd = ["git", "tag"]
            elif action == "create":
                if not tag_name:
                    return self.create_result(success=False, error_message="tag_name required for create")
                cmd = ["git", "tag"]
                if message:
                    cmd.extend(["-a", tag_name, "-m", message])
                else:
                    cmd.append(tag_name)
            elif action == "delete":
                if not tag_name:
                    return self.create_result(success=False, error_message="tag_name required for delete")
                cmd = ["git", "tag", "-d", tag_name]
            else:
                return self.create_result(success=False, error_message=f"Unknown action: {action}")

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Git tag failed: {stderr}")

            tags = stdout.splitlines() if action == "list" else []

            return self.create_result(
                success=True,
                result_data={"tags": tags, "output": stdout or stderr},
                output_text=f"Tag {action} successful",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")


class GitStashInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    action: str = Field(default="list", description="Action: list, push, pop, apply, drop")
    message: Optional[str] = Field(None, description="Stash message")


class GitStashOutput(BaseModel):
    output: str = Field(..., description="Git output")


class GitStashTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_stash"

    @property
    def description(self) -> str:
        return "Stash changes: save, restore, list, or drop stashed changes."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitStashInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitStashOutput

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
        message = input_data.get("message")

        try:
            cmd = ["git", "stash", action]
            if action == "push" and message:
                cmd.extend(["-m", message])

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Git stash failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"output": stdout or stderr},
                output_text=f"Stash {action} successful",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")


class GitResetInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    mode: str = Field(default="mixed", description="Mode: soft, mixed, hard")
    ref: str = Field(default="HEAD", description="Reference to reset to")


class GitResetOutput(BaseModel):
    output: str = Field(..., description="Git output")


class GitResetTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_reset"

    @property
    def description(self) -> str:
        return "Reset current HEAD to specified state."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitResetInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitResetOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def requires_approval(self) -> bool:
        return True  # Can lose changes

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        repo_path = input_data["repo_path"]
        mode = input_data["mode"]
        ref = input_data["ref"]

        try:
            cmd = ["git", "reset", f"--{mode}", ref]
            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Git reset failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"output": stdout or stderr},
                output_text=f"Reset to {ref} ({mode})",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")


class GitRevertInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    commit: str = Field(..., description="Commit to revert")
    no_commit: bool = Field(default=False, description="Don't auto-commit")


class GitRevertOutput(BaseModel):
    output: str = Field(..., description="Git output")


class GitRevertTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_revert"

    @property
    def description(self) -> str:
        return "Revert a commit by creating a new commit that undoes the changes."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitRevertInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitRevertOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "git"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        repo_path = input_data["repo_path"]
        commit = input_data["commit"]
        no_commit = input_data["no_commit"]

        try:
            cmd = ["git", "revert"]
            if no_commit:
                cmd.append("--no-commit")
            cmd.append(commit)

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(success=False, error_message=f"Git revert failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"output": stdout or stderr},
                output_text=f"Reverted commit {commit}",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")


class GitConfigInput(BaseModel):
    repo_path: str = Field(..., description="Repository path")
    action: str = Field(default="get", description="Action: get, set, unset, list")
    key: Optional[str] = Field(None, description="Config key")
    value: Optional[str] = Field(None, description="Config value for set")
    global_scope: bool = Field(default=False, description="Use global config")


class GitConfigOutput(BaseModel):
    config: str = Field(..., description="Config output")


class GitConfigTool(ToolBase):
    @property
    def name(self) -> str:
        return "git_config"

    @property
    def description(self) -> str:
        return "Get or set git configuration."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitConfigInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitConfigOutput

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
        key = input_data.get("key")
        value = input_data.get("value")
        global_scope = input_data["global_scope"]

        try:
            cmd = ["git", "config"]
            if global_scope:
                cmd.append("--global")

            if action == "list":
                cmd.append("--list")
            elif action == "get":
                if not key:
                    return self.create_result(success=False, error_message="key required for get")
                cmd.append(key)
            elif action == "set":
                if not key or not value:
                    return self.create_result(success=False, error_message="key and value required for set")
                cmd.extend([key, value])
            elif action == "unset":
                if not key:
                    return self.create_result(success=False, error_message="key required for unset")
                cmd.extend(["--unset", key])
            else:
                return self.create_result(success=False, error_message=f"Unknown action: {action}")

            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            # Git config --get returns exit code 1 if key not found, which is expected
            if exit_code != 0 and action != "get":
                return self.create_result(success=False, error_message=f"Git config failed: {stderr}")

            return self.create_result(
                success=True,
                result_data={"config": stdout},
                output_text=f"Config {action} successful",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed: {str(e)}")
