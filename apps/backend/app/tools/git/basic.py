"""
JARV Backend - Basic Git Tools

Basic git operations: init, clone, status, add, commit.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
import asyncio
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


async def run_git_command(
    command: List[str],
    cwd: Optional[str] = None,
    timeout: int = 30,
) -> tuple[str, str, int]:
    """Helper to run git commands"""
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )

        return (
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
            process.returncode,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise TimeoutError(f"Git command timed out after {timeout}s")


# ===== GIT INIT TOOL =====

class GitInitInput(BaseModel):
    """Input schema for git init tool"""
    path: str = Field(..., description="Path to initialize repository")
    bare: bool = Field(default=False, description="Create bare repository")
    initial_branch: Optional[str] = Field(None, description="Initial branch name")


class GitInitOutput(BaseModel):
    """Output schema for git init tool"""
    path: str = Field(..., description="Repository path")
    message: str = Field(..., description="Git output message")


class GitInitTool(ToolBase):
    """Tool for initializing git repository"""

    @property
    def name(self) -> str:
        return "git_init"

    @property
    def description(self) -> str:
        return "Initialize a new git repository."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitInitInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitInitOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "git"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute git init"""
        path = input_data["path"]
        bare = input_data["bare"]
        initial_branch = input_data.get("initial_branch")

        try:
            # Build command
            cmd = ["git", "init"]
            if bare:
                cmd.append("--bare")
            if initial_branch:
                cmd.extend(["--initial-branch", initial_branch])
            cmd.append(path)

            # Execute
            stdout, stderr, exit_code = await run_git_command(cmd, timeout=10)

            if exit_code != 0:
                return self.create_result(
                    success=False,
                    error_message=f"Git init failed: {stderr}",
                )

            return self.create_result(
                success=True,
                result_data={
                    "path": path,
                    "message": stdout or stderr,
                },
                output_text=f"Initialized git repository at {path}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to initialize repository: {str(e)}",
            )


# ===== GIT CLONE TOOL =====

class GitCloneInput(BaseModel):
    """Input schema for git clone tool"""
    url: str = Field(..., description="Repository URL to clone")
    destination: Optional[str] = Field(None, description="Destination directory")
    branch: Optional[str] = Field(None, description="Branch to clone")
    depth: Optional[int] = Field(None, description="Clone depth (shallow clone)")


class GitCloneOutput(BaseModel):
    """Output schema for git clone tool"""
    url: str = Field(..., description="Cloned repository URL")
    destination: str = Field(..., description="Destination path")
    message: str = Field(..., description="Git output message")


class GitCloneTool(ToolBase):
    """Tool for cloning git repository"""

    @property
    def name(self) -> str:
        return "git_clone"

    @property
    def description(self) -> str:
        return "Clone a git repository from URL."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitCloneInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitCloneOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True  # Network access

    @property
    def category(self) -> str:
        return "git"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute git clone"""
        url = input_data["url"]
        destination = input_data.get("destination")
        branch = input_data.get("branch")
        depth = input_data.get("depth")

        try:
            # Build command
            cmd = ["git", "clone"]
            if branch:
                cmd.extend(["--branch", branch])
            if depth:
                cmd.extend(["--depth", str(depth)])
            cmd.append(url)
            if destination:
                cmd.append(destination)

            # Execute (allow longer timeout for cloning)
            stdout, stderr, exit_code = await run_git_command(cmd, timeout=300)

            if exit_code != 0:
                return self.create_result(
                    success=False,
                    error_message=f"Git clone failed: {stderr}",
                )

            dest_path = destination or url.split("/")[-1].replace(".git", "")

            return self.create_result(
                success=True,
                result_data={
                    "url": url,
                    "destination": dest_path,
                    "message": stderr,  # Git clone outputs to stderr
                },
                output_text=f"Cloned repository to {dest_path}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to clone repository: {str(e)}",
            )


# ===== GIT STATUS TOOL =====

class GitStatusInput(BaseModel):
    """Input schema for git status tool"""
    repo_path: str = Field(..., description="Repository path")
    short: bool = Field(default=False, description="Use short format")


class GitStatusOutput(BaseModel):
    """Output schema for git status tool"""
    status: str = Field(..., description="Git status output")
    clean: bool = Field(..., description="Whether working tree is clean")


class GitStatusTool(ToolBase):
    """Tool for checking git repository status"""

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def description(self) -> str:
        return "Get git repository status showing changes, staged files, etc."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitStatusInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitStatusOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "git"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute git status"""
        repo_path = input_data["repo_path"]
        short = input_data["short"]

        try:
            # Build command
            cmd = ["git", "status"]
            if short:
                cmd.append("--short")

            # Execute
            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(
                    success=False,
                    error_message=f"Git status failed: {stderr}",
                )

            # Check if working tree is clean
            clean = "nothing to commit" in stdout or "working tree clean" in stdout

            return self.create_result(
                success=True,
                result_data={
                    "status": stdout,
                    "clean": clean,
                },
                output_text=f"Repository status: {'clean' if clean else 'has changes'}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to get status: {str(e)}",
            )


# ===== GIT ADD TOOL =====

class GitAddInput(BaseModel):
    """Input schema for git add tool"""
    repo_path: str = Field(..., description="Repository path")
    files: List[str] = Field(..., description="Files to stage (use ['.'] for all)")
    force: bool = Field(default=False, description="Force add ignored files")


class GitAddOutput(BaseModel):
    """Output schema for git add tool"""
    files: List[str] = Field(..., description="Files staged")
    message: str = Field(..., description="Git output message")


class GitAddTool(ToolBase):
    """Tool for staging files in git"""

    @property
    def name(self) -> str:
        return "git_add"

    @property
    def description(self) -> str:
        return "Stage files for commit in git repository."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitAddInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitAddOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "git"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute git add"""
        repo_path = input_data["repo_path"]
        files = input_data["files"]
        force = input_data["force"]

        try:
            # Build command
            cmd = ["git", "add"]
            if force:
                cmd.append("--force")
            cmd.extend(files)

            # Execute
            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(
                    success=False,
                    error_message=f"Git add failed: {stderr}",
                )

            return self.create_result(
                success=True,
                result_data={
                    "files": files,
                    "message": stdout or "Files staged successfully",
                },
                output_text=f"Staged {len(files)} file(s)",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to stage files: {str(e)}",
            )


# ===== GIT COMMIT TOOL =====

class GitCommitInput(BaseModel):
    """Input schema for git commit tool"""
    repo_path: str = Field(..., description="Repository path")
    message: str = Field(..., description="Commit message")
    author: Optional[str] = Field(None, description="Author name <email>")
    amend: bool = Field(default=False, description="Amend previous commit")
    all: bool = Field(default=False, description="Automatically stage modified files")


class GitCommitOutput(BaseModel):
    """Output schema for git commit tool"""
    commit_hash: str = Field(..., description="Commit hash")
    message: str = Field(..., description="Commit message")
    output: str = Field(..., description="Git output")


class GitCommitTool(ToolBase):
    """Tool for committing changes in git"""

    @property
    def name(self) -> str:
        return "git_commit"

    @property
    def description(self) -> str:
        return "Create a git commit with staged changes."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GitCommitInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GitCommitOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "git"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute git commit"""
        repo_path = input_data["repo_path"]
        message = input_data["message"]
        author = input_data.get("author")
        amend = input_data["amend"]
        all_files = input_data["all"]

        try:
            # Build command
            cmd = ["git", "commit", "-m", message]
            if author:
                cmd.extend(["--author", author])
            if amend:
                cmd.append("--amend")
            if all_files:
                cmd.append("-a")

            # Execute
            stdout, stderr, exit_code = await run_git_command(cmd, cwd=repo_path)

            if exit_code != 0:
                return self.create_result(
                    success=False,
                    error_message=f"Git commit failed: {stderr}",
                )

            # Get commit hash
            hash_cmd = ["git", "rev-parse", "HEAD"]
            hash_out, _, _ = await run_git_command(hash_cmd, cwd=repo_path)
            commit_hash = hash_out.strip()

            return self.create_result(
                success=True,
                result_data={
                    "commit_hash": commit_hash,
                    "message": message,
                    "output": stdout,
                },
                output_text=f"Created commit {commit_hash[:7]}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to commit: {str(e)}",
            )
