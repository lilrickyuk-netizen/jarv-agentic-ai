"""
JARV Backend - Terminal Management Tools

Terminal session management tools: open, send, read, close.
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field
import asyncio
import uuid
import logging

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)

# Global terminal session storage (in production, use Redis or database)
_terminal_sessions: Dict[str, Any] = {}


# ===== TERMINAL OPEN TOOL =====

class TerminalOpenInput(BaseModel):
    """Input schema for terminal open tool"""
    shell: str = Field(default="/bin/bash", description="Shell to use")
    working_dir: Optional[str] = Field(None, description="Working directory")
    env_vars: Optional[Dict[str, str]] = Field(None, description="Environment variables")


class TerminalOpenOutput(BaseModel):
    """Output schema for terminal open tool"""
    session_id: str = Field(..., description="Terminal session ID")
    shell: str = Field(..., description="Shell being used")
    message: str = Field(..., description="Status message")


class TerminalOpenTool(ToolBase):
    """Tool for opening a terminal session"""

    @property
    def name(self) -> str:
        return "terminal_open"

    @property
    def description(self) -> str:
        return "Open a persistent terminal session. Returns session ID for future interactions."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return TerminalOpenInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return TerminalOpenOutput

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
        """Open terminal session"""
        shell = input_data["shell"]
        working_dir = input_data.get("working_dir")
        env_vars = input_data.get("env_vars")

        try:
            # Generate session ID
            session_id = str(uuid.uuid4())

            # Prepare environment
            import os
            env = os.environ.copy()
            if env_vars:
                env.update(env_vars)

            # Start process
            process = await asyncio.create_subprocess_shell(
                shell,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=env,
            )

            # Store session
            _terminal_sessions[session_id] = {
                "process": process,
                "shell": shell,
                "working_dir": working_dir,
                "created_at": asyncio.get_event_loop().time(),
            }

            return self.create_result(
                success=True,
                result_data={
                    "session_id": session_id,
                    "shell": shell,
                    "message": f"Terminal session opened with ID {session_id}",
                },
                output_text=f"Opened terminal session: {session_id}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to open terminal: {str(e)}",
            )


# ===== TERMINAL SEND TOOL =====

class TerminalSendInput(BaseModel):
    """Input schema for terminal send tool"""
    session_id: str = Field(..., description="Terminal session ID")
    command: str = Field(..., description="Command to send")
    append_newline: bool = Field(default=True, description="Append newline to command")


class TerminalSendOutput(BaseModel):
    """Output schema for terminal send tool"""
    session_id: str = Field(..., description="Terminal session ID")
    command: str = Field(..., description="Command sent")
    message: str = Field(..., description="Status message")


class TerminalSendTool(ToolBase):
    """Tool for sending input to terminal session"""

    @property
    def name(self) -> str:
        return "terminal_send"

    @property
    def description(self) -> str:
        return "Send a command to an open terminal session."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return TerminalSendInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return TerminalSendOutput

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
        """Send to terminal"""
        session_id = input_data["session_id"]
        command = input_data["command"]
        append_newline = input_data["append_newline"]

        try:
            # Get session
            session = _terminal_sessions.get(session_id)
            if not session:
                return self.create_result(
                    success=False,
                    error_message=f"Terminal session not found: {session_id}",
                )

            process = session["process"]

            # Check if process is still running
            if process.returncode is not None:
                return self.create_result(
                    success=False,
                    error_message=f"Terminal session has terminated",
                )

            # Check banned commands
            if context.banned_commands:
                for banned in context.banned_commands:
                    if banned in command:
                        return self.create_result(
                            success=False,
                            error_message=f"Command contains banned string: {banned}",
                        )

            # Send command
            text = command + "\n" if append_newline else command
            process.stdin.write(text.encode())
            await process.stdin.drain()

            return self.create_result(
                success=True,
                result_data={
                    "session_id": session_id,
                    "command": command,
                    "message": "Command sent to terminal",
                },
                output_text=f"Sent command to terminal {session_id}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to send to terminal: {str(e)}",
            )


# ===== TERMINAL READ TOOL =====

class TerminalReadInput(BaseModel):
    """Input schema for terminal read tool"""
    session_id: str = Field(..., description="Terminal session ID")
    timeout: int = Field(default=5, ge=1, le=60, description="Read timeout in seconds")
    max_bytes: int = Field(default=10240, ge=1, le=1048576, description="Maximum bytes to read")


class TerminalReadOutput(BaseModel):
    """Output schema for terminal read tool"""
    session_id: str = Field(..., description="Terminal session ID")
    output: str = Field(..., description="Terminal output")
    bytes_read: int = Field(..., description="Bytes read")
    timed_out: bool = Field(..., description="Whether read timed out")


class TerminalReadTool(ToolBase):
    """Tool for reading output from terminal session"""

    @property
    def name(self) -> str:
        return "terminal_read"

    @property
    def description(self) -> str:
        return "Read output from an open terminal session. Returns available output or times out."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return TerminalReadInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return TerminalReadOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "command"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Read from terminal"""
        session_id = input_data["session_id"]
        timeout = input_data["timeout"]
        max_bytes = input_data["max_bytes"]

        try:
            # Get session
            session = _terminal_sessions.get(session_id)
            if not session:
                return self.create_result(
                    success=False,
                    error_message=f"Terminal session not found: {session_id}",
                )

            process = session["process"]

            # Check if process is still running
            if process.returncode is not None:
                return self.create_result(
                    success=False,
                    error_message=f"Terminal session has terminated",
                )

            # Read output
            timed_out = False
            try:
                output_bytes = await asyncio.wait_for(
                    process.stdout.read(max_bytes),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                timed_out = True
                output_bytes = b""

            output_str = output_bytes.decode("utf-8", errors="replace")

            return self.create_result(
                success=True,
                result_data={
                    "session_id": session_id,
                    "output": output_str,
                    "bytes_read": len(output_bytes),
                    "timed_out": timed_out,
                },
                output_text=f"Read {len(output_bytes)} bytes from terminal",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to read from terminal: {str(e)}",
            )


# ===== TERMINAL CLOSE TOOL =====

class TerminalCloseInput(BaseModel):
    """Input schema for terminal close tool"""
    session_id: str = Field(..., description="Terminal session ID")
    force: bool = Field(default=False, description="Force kill if not responding")


class TerminalCloseOutput(BaseModel):
    """Output schema for terminal close tool"""
    session_id: str = Field(..., description="Terminal session ID")
    exit_code: Optional[int] = Field(None, description="Exit code if available")
    message: str = Field(..., description="Status message")


class TerminalCloseTool(ToolBase):
    """Tool for closing a terminal session"""

    @property
    def name(self) -> str:
        return "terminal_close"

    @property
    def description(self) -> str:
        return "Close an open terminal session. Can force-kill if needed."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return TerminalCloseInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return TerminalCloseOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "command"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Close terminal"""
        session_id = input_data["session_id"]
        force = input_data["force"]

        try:
            # Get session
            session = _terminal_sessions.get(session_id)
            if not session:
                return self.create_result(
                    success=False,
                    error_message=f"Terminal session not found: {session_id}",
                )

            process = session["process"]

            # Close stdin to signal exit
            if process.stdin:
                process.stdin.close()

            # Wait for termination
            if force:
                # Force kill
                process.kill()
                await process.wait()
            else:
                # Graceful termination
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    # Force kill if doesn't terminate
                    process.kill()
                    await process.wait()

            exit_code = process.returncode

            # Remove session
            del _terminal_sessions[session_id]

            return self.create_result(
                success=True,
                result_data={
                    "session_id": session_id,
                    "exit_code": exit_code,
                    "message": f"Terminal session closed with exit code {exit_code}",
                },
                output_text=f"Closed terminal session {session_id}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to close terminal: {str(e)}",
            )
