"""
JARV Backend - Tool Base Class

Abstract base class for all JARV tools with standardized interface,
logging, error handling, and authority management.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Type
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID, uuid4
import logging
import traceback

from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


class ToolConfig(BaseModel):
    """Configuration for tool execution"""
    tool_id: UUID = Field(default_factory=uuid4, description="Unique tool execution ID")
    workspace_id: Optional[UUID] = Field(None, description="Associated workspace ID")
    user_id: Optional[UUID] = Field(None, description="User executing tool")
    agent_id: Optional[UUID] = Field(None, description="Agent using this tool")
    task_id: Optional[UUID] = Field(None, description="Task context")
    session_id: Optional[UUID] = Field(None, description="Session ID")
    authority_level: AuthorityLevel = Field(
        default=AuthorityLevel.LEVEL_1_BASIC_TOOLS,
        description="User/agent authority level"
    )
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Tool execution timeout"
    )
    dry_run: bool = Field(
        default=False,
        description="If true, validate but don't execute"
    )
    extra_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional tool-specific configuration"
    )


class ToolContext(BaseModel):
    """Context provided to tool during execution"""
    workspace_id: Optional[UUID] = Field(None, description="Current workspace")
    user_id: Optional[UUID] = Field(None, description="Current user")
    agent_id: Optional[UUID] = Field(None, description="Agent using tool")
    task_id: Optional[UUID] = Field(None, description="Task being executed")
    session_id: Optional[UUID] = Field(None, description="Execution session")
    approved_folders: List[str] = Field(
        default_factory=list,
        description="Folders tool is allowed to access"
    )
    banned_folders: List[str] = Field(
        default_factory=list,
        description="Folders tool must not access"
    )
    approved_commands: List[str] = Field(
        default_factory=list,
        description="Commands tool is allowed to run"
    )
    banned_commands: List[str] = Field(
        default_factory=list,
        description="Commands tool must not run"
    )
    approval_granted: bool = Field(
        default=False,
        description="True if an approval has been granted for this action/context"
    )
    approved_tools: List[str] = Field(
        default_factory=list,
        description="Tool names explicitly approved for execution in this context"
    )
    db_session: Optional[Any] = Field(
        default=None,
        description="Optional AsyncSession for ToolRun/audit logging (not required)"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context metadata"
    )

    class Config:
        arbitrary_types_allowed = True


class ToolResult(BaseModel):
    """Standardized result from tool execution"""
    success: bool = Field(..., description="Whether execution succeeded")
    tool_name: str = Field(..., description="Name of tool that executed")
    tool_id: UUID = Field(..., description="Tool execution ID")
    result_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured result data"
    )
    output_text: Optional[str] = Field(None, description="Human-readable output")
    execution_time_seconds: float = Field(default=0.0, description="Execution time")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    requires_approval: bool = Field(
        default=False,
        description="Whether action requires approval"
    )
    was_dry_run: bool = Field(
        default=False,
        description="Whether this was a dry run"
    )
    files_affected: List[str] = Field(
        default_factory=list,
        description="Files modified by tool"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional result metadata"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        arbitrary_types_allowed = True


class ToolError(Exception):
    """Base exception for tool errors"""
    def __init__(self, message: str, tool_name: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.tool_name = tool_name
        self.details = details or {}
        super().__init__(self.message)


class ToolValidationError(ToolError):
    """Raised when tool input validation fails"""
    pass


class ToolExecutionError(ToolError):
    """Raised when tool execution fails"""
    pass


class ToolAuthorizationError(ToolError):
    """Raised when tool lacks authority for an action"""
    pass


class ToolBase(ABC):
    """
    Abstract base class for all JARV tools.

    All tools must inherit from this class and implement the required methods.
    This ensures consistent interface, logging, error handling, and authority
    management across all tools.
    """

    def __init__(self, config: ToolConfig):
        """
        Initialize tool with configuration.

        Args:
            config: Tool configuration including authority and settings
        """
        self.config = config
        self.logger = logging.getLogger(f"tool.{self.name}")
        self._execution_start_time: Optional[float] = None

        # Log tool initialization
        self.logger.debug(
            f"Initialized {self.name} tool",
            extra={
                "tool_id": str(config.tool_id),
                "authority_level": config.authority_level.value,
            }
        )

    # ===== Required Properties =====

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Tool name (unique identifier).

        Example: "file_read", "git_commit", "run_command"
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Tool description for agents.

        Should explain what the tool does and when to use it.
        """
        pass

    @property
    @abstractmethod
    def input_schema(self) -> Type[BaseModel]:
        """
        Pydantic model defining expected input structure.

        Must be a Pydantic BaseModel subclass that validates tool inputs.
        """
        pass

    @property
    @abstractmethod
    def output_schema(self) -> Type[BaseModel]:
        """
        Pydantic model defining output structure.

        Must be a Pydantic BaseModel subclass that validates tool outputs.
        """
        pass

    @property
    @abstractmethod
    def required_authority_level(self) -> AuthorityLevel:
        """
        Minimum authority level required to use this tool.

        Tools cannot execute if user authority < required authority.
        """
        pass

    @property
    def requires_approval(self) -> bool:
        """
        Whether this tool requires approval before execution.

        Override to True for risky operations like file deletion, git push, etc.
        """
        return False

    @property
    def category(self) -> str:
        """
        Tool category for organization.

        Override with appropriate category: file, command, git, workspace, etc.
        """
        return "general"

    # ===== Core Methods =====

    @abstractmethod
    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """
        Execute tool with given input and context.

        This is the main execution method that must be implemented by all tools.

        Args:
            input_data: Input data validated against input_schema
            context: Execution context with workspace, permissions, etc.

        Returns:
            ToolResult with execution results

        Raises:
            ToolValidationError: If input validation fails
            ToolExecutionError: If execution fails
            ToolAuthorizationError: If tool lacks required authority
        """
        pass

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """
        Execute tool with validation, logging, and error handling.

        This is the public entry point that wraps run() with standard
        validation, logging, and error handling.

        Args:
            input_data: Raw input data (will be validated)
            context: Execution context

        Returns:
            ToolResult with execution results
        """
        import time

        self._execution_start_time = time.time()
        self._started_at = datetime.utcnow()

        # Audit log: Tool execution start
        await self._audit_start(input_data, context)

        try:
            # Log execution start
            self.logger.info(
                f"Starting execution of {self.name}",
                extra={
                    "tool_id": str(self.config.tool_id),
                    "workspace_id": str(context.workspace_id) if context.workspace_id else None,
                    "agent_id": str(context.agent_id) if context.agent_id else None,
                }
            )

            # Validate authority
            self._validate_authority()

            # Validate input
            validated_input = self._validate_input(input_data)

            # ENFORCE APPROVAL: a tool that requires approval must NOT execute
            # unless a valid approval is present in the context. We do not fake
            # approval and we do not silently continue — we return a structured
            # blocked result and log it. (dry_run is validation-only, so it is
            # allowed to proceed without approval.)
            if self.requires_approval and not self.config.dry_run \
                    and not self._has_approval(context):
                blocked = self._blocked_result(
                    reason=(
                        f"Tool '{self.name}' requires approval but no approval was "
                        "granted in this execution context; execution was not "
                        "performed."
                    )
                )
                self.logger.warning(
                    f"Tool {self.name} BLOCKED: requires approval, none granted"
                )
                blocked.metadata["tool_run_logged"] = await self._log_tool_run(
                    context, status="blocked", input_data=validated_input,
                    result=blocked, error_message=None,
                )
                await self._audit_complete(blocked, context)
                return blocked

            # Execute tool
            result = await self.run(validated_input, context)

            # Calculate execution time
            execution_time = time.time() - self._execution_start_time
            result.execution_time_seconds = execution_time
            result.was_dry_run = self.config.dry_run

            # Log execution completion
            self.logger.info(
                f"Completed execution of {self.name}",
                extra={
                    "tool_id": str(self.config.tool_id),
                    "success": result.success,
                    "execution_time": f"{execution_time:.2f}s",
                }
            )

            # ToolRun logging (best-effort; marks tool_run_logged on the result)
            result.metadata["tool_run_logged"] = await self._log_tool_run(
                context,
                status=("success" if result.success else "failed"),
                input_data=validated_input,
                result=result,
                error_message=result.error_message,
            )

            # Audit log: Tool execution complete
            await self._audit_complete(result, context)

            return result

        except ToolError as e:
            # Audit log: Tool execution error
            await self._audit_error(e, context)
            # Re-raise tool-specific errors
            raise

        except Exception as e:
            # Wrap unexpected errors
            self.logger.error(
                f"Unexpected error in {self.name}",
                extra={
                    "tool_id": str(self.config.tool_id),
                    "error": str(e),
                },
                exc_info=True,
            )
            error = ToolExecutionError(
                message=f"Unexpected error in {self.name}: {str(e)}",
                tool_name=self.name,
                details={"original_error": str(e)},
            )
            # Audit log: Tool execution error
            await self._audit_error(error, context)
            raise error

    # ===== Validation Methods =====

    def _validate_authority(self) -> None:
        """
        Validate tool has required authority level.

        Raises:
            ToolAuthorizationError: If authority level insufficient
        """
        if self.config.authority_level < self.required_authority_level:
            raise ToolAuthorizationError(
                message=f"Tool {self.name} requires authority level "
                        f"{self.required_authority_level.value} but has "
                        f"{self.config.authority_level.value}",
                tool_name=self.name,
                details={
                    "required_level": self.required_authority_level.value,
                    "current_level": self.config.authority_level.value,
                }
            )

    def _validate_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate input data against input schema.

        Args:
            input_data: Raw input data

        Returns:
            Validated input data as dict

        Raises:
            ToolValidationError: If validation fails
        """
        try:
            validated = self.input_schema(**input_data)
            return validated.dict()
        except Exception as e:
            raise ToolValidationError(
                message=f"Input validation failed for {self.name}: {str(e)}",
                tool_name=self.name,
                details={"validation_error": str(e), "input_data": input_data}
            )

    def _validate_output(self, output_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate output data against output schema.

        Args:
            output_data: Raw output data

        Returns:
            Validated output data as dict

        Raises:
            ToolValidationError: If validation fails
        """
        try:
            validated = self.output_schema(**output_data)
            return validated.dict()
        except Exception as e:
            self.logger.warning(
                f"Output validation failed for {self.name}: {str(e)}",
                extra={"output_data": output_data}
            )
            raise ToolValidationError(
                message=f"Output validation failed for {self.name}: {str(e)}",
                tool_name=self.name,
                details={"validation_error": str(e), "output_data": output_data}
            )

    # ===== Utility Methods =====

    def create_result(
        self,
        success: bool,
        result_data: Optional[Dict[str, Any]] = None,
        output_text: Optional[str] = None,
        error_message: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """
        Create standardized ToolResult.

        Args:
            success: Whether execution succeeded
            result_data: Structured result data
            output_text: Human-readable output
            error_message: Error message if failed
            **kwargs: Additional ToolResult fields

        Returns:
            ToolResult instance
        """
        return ToolResult(
            success=success,
            tool_name=self.name,
            tool_id=self.config.tool_id,
            result_data=result_data or {},
            output_text=output_text,
            error_message=error_message,
            **kwargs
        )

    # ===== Approval Enforcement =====

    def _has_approval(self, context: ToolContext) -> bool:
        """Whether a valid approval is present for this tool in the context.

        Minimal, honest gate (NOT the full Richard Boundary / approval-resume
        system): an approval must be explicitly signalled by the caller via
        approval_granted, an approved_tools allowlist, or a metadata flag.
        Defaults to False so risky tools are blocked rather than auto-run.
        """
        if getattr(context, "approval_granted", False):
            return True
        if self.name in (getattr(context, "approved_tools", None) or []):
            return True
        meta = getattr(context, "metadata", None) or {}
        if meta.get("approval_granted") is True:
            return True
        approved = meta.get("approved_tools") or []
        return self.name in approved

    def _blocked_result(self, reason: str) -> ToolResult:
        """Structured blocked result for an action that needs approval."""
        risk_level = "high" if self.requires_approval else "normal"
        return self.create_result(
            success=False,
            result_data={
                "blocked": True,
                "reason": reason,
                "requires_approval": True,
                "tool": self.name,
                "risk_level": risk_level,
                "recommended_next_action": (
                    "Obtain approval for this action (set approval_granted / add "
                    f"'{self.name}' to approved_tools in the tool context), then retry."
                ),
            },
            output_text=f"BLOCKED: {reason}",
            requires_approval=True,
        )

    # ===== ToolRun Logging =====

    async def _log_tool_run(
        self,
        context: ToolContext,
        status: str,
        input_data: Dict[str, Any],
        result: Optional[ToolResult],
        error_message: Optional[str],
    ) -> bool:
        """Write a real ToolRun if a DB session + agent are available.

        Best-effort: returns True if a row was written, False otherwise. Never
        raises (tool execution must not fail because logging failed).
        """
        try:
            from app.core.tools.run_logging import write_tool_run

            started_at = getattr(self, "_started_at", None) or datetime.utcnow()
            return await write_tool_run(
                getattr(context, "db_session", None),
                tool_name=self.name,
                tool_group=self.category,
                description=self.description,
                input_schema_json=self._schema_json(self.input_schema),
                output_schema_json=self._schema_json(self.output_schema),
                minimum_authority_level=self.required_authority_level.value,
                requires_approval=self.requires_approval,
                status=status,
                success=(result.success if result is not None else None),
                input_data=input_data,
                output_data=(result.result_data if result is not None else None),
                error_message=error_message,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                authority_level_used=self.config.authority_level.value,
                agent_id=context.agent_id,
                session_id=context.session_id,
                meta={"tool_id": str(self.config.tool_id), "status": status},
            )
        except Exception as e:  # noqa: BLE001
            self.logger.warning(f"ToolRun logging skipped for {self.name}: {e}")
            return False

    @staticmethod
    def _schema_json(schema_cls: Any) -> Dict[str, Any]:
        """Best-effort JSON schema for a pydantic model (empty dict on failure)."""
        try:
            if hasattr(schema_cls, "model_json_schema"):
                return schema_cls.model_json_schema()
            if hasattr(schema_cls, "schema"):
                return schema_cls.schema()
        except Exception:  # noqa: BLE001
            pass
        return {}

    # ===== Audit Logging Methods =====

    async def _audit_start(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> None:
        """
        Log tool execution start to audit trail.

        Args:
            input_data: Tool input data
            context: Execution context
        """
        try:
            from app.core.audit import AuditLogger
            from app.core.database import get_db

            async for session in get_db():
                await AuditLogger.log_tool_use(
                    session=session,
                    agent_name=f"tool.{self.name}",
                    tool_name=self.name,
                    tool_result="started",
                    user_id=context.user_id,
                    workspace_id=context.workspace_id,
                    agent_id=context.agent_id,
                    task_id=context.task_id,
                    session_id=context.session_id,
                    tool_input=input_data,
                )
                break
        except Exception as e:
            # Don't fail execution if audit logging fails
            self.logger.warning(
                f"Failed to audit tool start: {e}",
                extra={"tool_name": self.name}
            )

    async def _audit_complete(
        self,
        result: ToolResult,
        context: ToolContext,
    ) -> None:
        """
        Log tool execution completion to audit trail.

        Args:
            result: Tool execution result
            context: Execution context
        """
        try:
            from app.core.audit import AuditLogger
            from app.core.database import get_db

            async for session in get_db():
                await AuditLogger.log_tool_use(
                    session=session,
                    agent_name=f"tool.{self.name}",
                    tool_name=self.name,
                    tool_result="success" if result.success else "failure",
                    user_id=context.user_id,
                    workspace_id=context.workspace_id,
                    agent_id=context.agent_id,
                    task_id=context.task_id,
                    session_id=context.session_id,
                    tool_output=result.result_data,
                )
                break
        except Exception as e:
            # Don't fail execution if audit logging fails
            self.logger.warning(
                f"Failed to audit tool completion: {e}",
                extra={"tool_name": self.name}
            )

    async def _audit_error(
        self,
        error: Exception,
        context: ToolContext,
    ) -> None:
        """
        Log tool execution error to audit trail.

        Args:
            error: Exception that occurred
            context: Execution context
        """
        try:
            from app.core.audit import AuditLogger
            from app.core.database import get_db

            async for session in get_db():
                await AuditLogger.log_tool_use(
                    session=session,
                    agent_name=f"tool.{self.name}",
                    tool_name=self.name,
                    tool_result="error",
                    user_id=context.user_id,
                    workspace_id=context.workspace_id,
                    agent_id=context.agent_id,
                    task_id=context.task_id,
                    session_id=context.session_id,
                    tool_output={
                        "error_message": str(error),
                        "error_type": type(error).__name__,
                        "stack_trace": traceback.format_exc(),
                    },
                )
                break
        except Exception as e:
            # Don't fail execution if audit logging fails
            self.logger.warning(
                f"Failed to audit tool error: {e}",
                extra={"tool_name": self.name}
            )

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"name={self.name} "
            f"authority={self.config.authority_level.value}>"
        )
