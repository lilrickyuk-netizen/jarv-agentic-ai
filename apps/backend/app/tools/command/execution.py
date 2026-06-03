"""
JARV Backend - Command Execution Tools

Command execution tools: run, background, pipe, sudo, timeout, env.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
import subprocess
import asyncio
import logging
import shlex

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


# ===== COMMAND RUN TOOL =====

class CommandRunInput(BaseModel):
    """Input schema for command run tool"""
    command: str = Field(..., description="Command to execute")
    working_dir: Optional[str] = Field(None, description="Working directory")
    timeout: int = Field(default=30, ge=1, le=300, description="Timeout in seconds")
    capture_output: bool = Field(default=True, description="Capture stdout/stderr")
    shell: bool = Field(default=True, description="Execute through shell")


class CommandRunOutput(BaseModel):
    """Output schema for command run tool"""
    command: str = Field(..., description="Command executed")
    stdout: str = Field(..., description="Standard output")
    stderr: str = Field(..., description="Standard error")
    exit_code: int = Field(..., description="Exit code")
    timed_out: bool = Field(..., description="Whether command timed out")


class CommandRunTool(ToolBase):
    """Tool for running shell commands"""

    @property
    def name(self) -> str:
        return "command_run"

    @property
    def description(self) -> str:
        return "Execute a shell command and return output. Supports timeout and working directory."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CommandRunInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CommandRunOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def requires_approval(self) -> bool:
        return True  # Command execution is risky

    @property
    def category(self) -> str:
        return "command"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute command"""
        command = input_data["command"]
        working_dir = input_data.get("working_dir")
        timeout = input_data["timeout"]
        capture_output = input_data["capture_output"]
        shell = input_data["shell"]

        try:
            # Check banned commands
            if context.banned_commands:
                for banned in context.banned_commands:
                    if banned in command:
                        return self.create_result(
                            success=False,
                            error_message=f"Command contains banned string: {banned}",
                        )

            # Check approved commands if whitelist exists
            if context.approved_commands:
                command_name = command.split()[0] if not shell else command
                if not any(cmd in command_name for cmd in context.approved_commands):
                    return self.create_result(
                        success=False,
                        error_message=f"Command not in approved list",
                    )

            # Execute command
            timed_out = False
            try:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE if capture_output else None,
                    stderr=asyncio.subprocess.PIPE if capture_output else None,
                    cwd=working_dir,
                )

                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )

                exit_code = process.returncode
                stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
                stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

            except asyncio.TimeoutError:
                timed_out = True
                process.kill()
                await process.wait()
                return self.create_result(
                    success=False,
                    error_message=f"Command timed out after {timeout} seconds",
                    result_data={
                        "command": command,
                        "stdout": "",
                        "stderr": "",
                        "exit_code": -1,
                        "timed_out": True,
                    },
                )

            return self.create_result(
                success=exit_code == 0,
                result_data={
                    "command": command,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "exit_code": exit_code,
                    "timed_out": timed_out,
                },
                output_text=f"Command exited with code {exit_code}",
                error_message=stderr_str if exit_code != 0 else None,
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to execute command: {str(e)}",
            )


# ===== COMMAND BACKGROUND TOOL =====

class CommandBackgroundInput(BaseModel):
    """Input schema for background command tool"""
    command: str = Field(..., description="Command to execute in background")
    working_dir: Optional[str] = Field(None, description="Working directory")
    log_file: Optional[str] = Field(None, description="File to redirect output to")


class CommandBackgroundOutput(BaseModel):
    """Output schema for background command tool"""
    command: str = Field(..., description="Command executed")
    pid: int = Field(..., description="Process ID")
    message: str = Field(..., description="Status message")


class CommandBackgroundTool(ToolBase):
    """Tool for running commands in background"""

    @property
    def name(self) -> str:
        return "command_background"

    @property
    def description(self) -> str:
        return "Execute a command in the background and return immediately with process ID."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CommandBackgroundInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CommandBackgroundOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "command"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute background command"""
        command = input_data["command"]
        working_dir = input_data.get("working_dir")
        log_file = input_data.get("log_file")

        try:
            # Check banned commands
            if context.banned_commands:
                for banned in context.banned_commands:
                    if banned in command:
                        return self.create_result(
                            success=False,
                            error_message=f"Command contains banned string: {banned}",
                        )

            # Start process
            if log_file:
                # Redirect to log file
                process = await asyncio.create_subprocess_shell(
                    f"{command} > {log_file} 2>&1",
                    cwd=working_dir,
                )
            else:
                # Discard output
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    cwd=working_dir,
                )

            return self.create_result(
                success=True,
                result_data={
                    "command": command,
                    "pid": process.pid,
                    "message": f"Process started in background with PID {process.pid}",
                },
                output_text=f"Background process started (PID: {process.pid})",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to start background command: {str(e)}",
            )


# ===== COMMAND PIPE TOOL =====

class CommandPipeInput(BaseModel):
    """Input schema for pipe command tool"""
    commands: List[str] = Field(..., description="List of commands to pipe together")
    working_dir: Optional[str] = Field(None, description="Working directory")
    timeout: int = Field(default=30, ge=1, le=300, description="Timeout in seconds")


class CommandPipeOutput(BaseModel):
    """Output schema for pipe command tool"""
    commands: List[str] = Field(..., description="Commands executed")
    stdout: str = Field(..., description="Final output")
    stderr: str = Field(..., description="Error output")
    exit_code: int = Field(..., description="Exit code of last command")


class CommandPipeTool(ToolBase):
    """Tool for piping commands together"""

    @property
    def name(self) -> str:
        return "command_pipe"

    @property
    def description(self) -> str:
        return "Pipe multiple commands together (e.g., ['ls -la', 'grep txt'])."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CommandPipeInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CommandPipeOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "command"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute piped commands"""
        commands = input_data["commands"]
        working_dir = input_data.get("working_dir")
        timeout = input_data["timeout"]

        try:
            # Check banned commands
            if context.banned_commands:
                for cmd in commands:
                    for banned in context.banned_commands:
                        if banned in cmd:
                            return self.create_result(
                                success=False,
                                error_message=f"Command contains banned string: {banned}",
                            )

            # Build piped command
            piped_command = " | ".join(commands)

            # Execute
            process = await asyncio.create_subprocess_shell(
                piped_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return self.create_result(
                    success=False,
                    error_message=f"Piped commands timed out after {timeout} seconds",
                )

            exit_code = process.returncode
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            return self.create_result(
                success=exit_code == 0,
                result_data={
                    "commands": commands,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "exit_code": exit_code,
                },
                output_text=f"Piped commands completed with exit code {exit_code}",
                error_message=stderr_str if exit_code != 0 else None,
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to execute piped commands: {str(e)}",
            )


# ===== COMMAND SUDO TOOL =====

class CommandSudoInput(BaseModel):
    """Input schema for sudo command tool"""
    command: str = Field(..., description="Command to execute with sudo")
    password: Optional[str] = Field(None, description="Sudo password if required")
    timeout: int = Field(default=30, ge=1, le=300, description="Timeout in seconds")


class CommandSudoOutput(BaseModel):
    """Output schema for sudo command tool"""
    command: str = Field(..., description="Command executed")
    stdout: str = Field(..., description="Standard output")
    stderr: str = Field(..., description="Standard error")
    exit_code: int = Field(..., description="Exit code")


class CommandSudoTool(ToolBase):
    """Tool for executing commands with sudo"""

    @property
    def name(self) -> str:
        return "command_sudo"

    @property
    def description(self) -> str:
        return "Execute a command with elevated privileges (sudo). Requires high authority level."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CommandSudoInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CommandSudoOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_4_SYSTEM_CHANGES

    @property
    def requires_approval(self) -> bool:
        return True  # Elevated privileges

    @property
    def category(self) -> str:
        return "command"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute sudo command"""
        command = input_data["command"]
        password = input_data.get("password")
        timeout = input_data["timeout"]

        try:
            # Check banned commands
            if context.banned_commands:
                for banned in context.banned_commands:
                    if banned in command:
                        return self.create_result(
                            success=False,
                            error_message=f"Command contains banned string: {banned}",
                        )

            # Build sudo command
            sudo_command = f"sudo {command}"

            # Execute
            process = await asyncio.create_subprocess_shell(
                sudo_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if password else None,
            )

            try:
                if password:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(input=f"{password}\n".encode()),
                        timeout=timeout,
                    )
                else:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout,
                    )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return self.create_result(
                    success=False,
                    error_message=f"Sudo command timed out after {timeout} seconds",
                )

            exit_code = process.returncode
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            return self.create_result(
                success=exit_code == 0,
                result_data={
                    "command": command,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "exit_code": exit_code,
                },
                output_text=f"Sudo command exited with code {exit_code}",
                error_message=stderr_str if exit_code != 0 else None,
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to execute sudo command: {str(e)}",
            )


# ===== COMMAND TIMEOUT TOOL =====

class CommandTimeoutInput(BaseModel):
    """Input schema for timeout command tool"""
    command: str = Field(..., description="Command to execute")
    timeout: int = Field(..., ge=1, le=300, description="Timeout in seconds")
    kill_after: Optional[int] = Field(None, description="Force kill after N additional seconds")
    working_dir: Optional[str] = Field(None, description="Working directory")


class CommandTimeoutOutput(BaseModel):
    """Output schema for timeout command tool"""
    command: str = Field(..., description="Command executed")
    stdout: str = Field(..., description="Standard output")
    stderr: str = Field(..., description="Standard error")
    exit_code: int = Field(..., description="Exit code")
    timed_out: bool = Field(..., description="Whether command timed out")
    killed: bool = Field(..., description="Whether command was force killed")


class CommandTimeoutTool(ToolBase):
    """Tool for executing commands with strict timeout"""

    @property
    def name(self) -> str:
        return "command_timeout"

    @property
    def description(self) -> str:
        return "Execute a command with strict timeout control. Can force-kill if needed."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CommandTimeoutInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CommandTimeoutOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "command"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute command with timeout"""
        command = input_data["command"]
        timeout = input_data["timeout"]
        kill_after = input_data.get("kill_after")
        working_dir = input_data.get("working_dir")

        try:
            # Check banned commands
            if context.banned_commands:
                for banned in context.banned_commands:
                    if banned in command:
                        return self.create_result(
                            success=False,
                            error_message=f"Command contains banned string: {banned}",
                        )

            # Execute with timeout
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )

            timed_out = False
            killed = False

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                timed_out = True

                # Try graceful termination
                process.terminate()

                if kill_after:
                    # Wait for kill_after seconds before force kill
                    try:
                        await asyncio.wait_for(process.wait(), timeout=kill_after)
                    except asyncio.TimeoutError:
                        killed = True
                        process.kill()
                        await process.wait()
                else:
                    await process.wait()

                return self.create_result(
                    success=False,
                    result_data={
                        "command": command,
                        "stdout": "",
                        "stderr": "",
                        "exit_code": -1,
                        "timed_out": timed_out,
                        "killed": killed,
                    },
                    error_message=f"Command timed out after {timeout} seconds" +
                                  (f" and was force killed after {kill_after}s" if killed else ""),
                )

            exit_code = process.returncode
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            return self.create_result(
                success=exit_code == 0,
                result_data={
                    "command": command,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "exit_code": exit_code,
                    "timed_out": timed_out,
                    "killed": killed,
                },
                output_text=f"Command completed within timeout with exit code {exit_code}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to execute command with timeout: {str(e)}",
            )


# ===== COMMAND ENV TOOL =====

class CommandEnvInput(BaseModel):
    """Input schema for env command tool"""
    command: str = Field(..., description="Command to execute")
    env_vars: Dict[str, str] = Field(..., description="Environment variables")
    working_dir: Optional[str] = Field(None, description="Working directory")
    timeout: int = Field(default=30, ge=1, le=300, description="Timeout in seconds")


class CommandEnvOutput(BaseModel):
    """Output schema for env command tool"""
    command: str = Field(..., description="Command executed")
    env_vars: Dict[str, str] = Field(..., description="Environment variables used")
    stdout: str = Field(..., description="Standard output")
    stderr: str = Field(..., description="Standard error")
    exit_code: int = Field(..., description="Exit code")


class CommandEnvTool(ToolBase):
    """Tool for executing commands with custom environment variables"""

    @property
    def name(self) -> str:
        return "command_env"

    @property
    def description(self) -> str:
        return "Execute a command with custom environment variables."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CommandEnvInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CommandEnvOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "command"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute command with env vars"""
        command = input_data["command"]
        env_vars = input_data["env_vars"]
        working_dir = input_data.get("working_dir")
        timeout = input_data["timeout"]

        try:
            # Check banned commands
            if context.banned_commands:
                for banned in context.banned_commands:
                    if banned in command:
                        return self.create_result(
                            success=False,
                            error_message=f"Command contains banned string: {banned}",
                        )

            # Merge with current environment
            import os
            env = os.environ.copy()
            env.update(env_vars)

            # Execute
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return self.create_result(
                    success=False,
                    error_message=f"Command timed out after {timeout} seconds",
                )

            exit_code = process.returncode
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            return self.create_result(
                success=exit_code == 0,
                result_data={
                    "command": command,
                    "env_vars": env_vars,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "exit_code": exit_code,
                },
                output_text=f"Command with env vars exited with code {exit_code}",
                error_message=stderr_str if exit_code != 0 else None,
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to execute command with env vars: {str(e)}",
            )
