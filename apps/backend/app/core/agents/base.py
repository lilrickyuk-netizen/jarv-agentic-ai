"""
JARV Backend - Agent Base Class

Abstract base class for all JARV agents with standardized interface,
logging, error handling, and authority management.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Type
from pydantic import BaseModel, Field, validator
from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
import logging
import traceback

logger = logging.getLogger(__name__)


class AuthorityLevel(int, Enum):
    """Agent authority levels for action approval"""
    LEVEL_0_READ_ONLY = 0
    LEVEL_1_BASIC_TOOLS = 1
    LEVEL_2_FILE_OPERATIONS = 2
    LEVEL_3_CODE_EXECUTION = 3
    LEVEL_4_SYSTEM_CHANGES = 4
    LEVEL_5_NETWORK_ACCESS = 5
    LEVEL_6_DATABASE_WRITE = 6
    LEVEL_7_DEPLOYMENT = 7
    LEVEL_8_FINANCIAL = 8
    LEVEL_9_SWARM_CREATION = 9
    LEVEL_10_FULL_AUTONOMY = 10


class AgentConfig(BaseModel):
    """Configuration for agent initialization"""
    agent_id: Optional[UUID] = Field(default_factory=uuid4, description="Unique agent instance ID")
    workspace_id: Optional[UUID] = Field(None, description="Associated workspace ID")
    user_id: Optional[UUID] = Field(None, description="User who owns this agent instance")
    session_id: Optional[UUID] = Field(None, description="Current session ID")
    authority_level: AuthorityLevel = Field(
        default=AuthorityLevel.LEVEL_1_BASIC_TOOLS,
        description="Maximum authority level for this agent"
    )
    allowed_tools: List[str] = Field(
        default_factory=list,
        description="List of tool names this agent is allowed to use"
    )
    enable_memory: bool = Field(
        default=True,
        description="Whether agent can access memory system"
    )
    enable_self_evolution: bool = Field(
        default=False,
        description="Whether agent can trigger self-evolution"
    )
    max_iterations: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum execution iterations"
    )
    timeout_seconds: int = Field(
        default=300,
        ge=1,
        le=3600,
        description="Execution timeout in seconds"
    )
    model: str = Field(
        default="claude-sonnet-4-6",
        description="LLM model to use for this agent"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="LLM temperature setting"
    )
    extra_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional agent-specific configuration"
    )


class AgentContext(BaseModel):
    """Context provided to agent during execution"""
    workspace_id: Optional[UUID] = Field(None, description="Current workspace")
    user_id: Optional[UUID] = Field(None, description="Current user")
    session_id: Optional[UUID] = Field(None, description="Current session")
    task_id: Optional[UUID] = Field(None, description="Current task being executed")
    parent_agent_id: Optional[UUID] = Field(None, description="Parent agent if spawned by another")
    memory_context: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Relevant memories for this execution"
    )
    knowledge_context: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Retrieved, source-attributed specialist knowledge for this task"
    )
    workspace_rules: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Active workspace rules"
    )
    operating_plan: Optional[Dict[str, Any]] = Field(
        None,
        description="Current operating plan if in company mode"
    )
    previous_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Results from previous steps or agents"
    )
    db_session: Optional[Any] = Field(
        default=None,
        description="Optional AsyncSession carried through for tool ToolRun/persistence "
                    "(not required; no-session execution stays safe)"
    )
    request_id: Optional[UUID] = Field(
        None, description="Mission/request id, if available"
    )
    approval_granted: bool = Field(
        default=False,
        description="True if an approval has been granted for this execution context"
    )
    approved_tools: List[str] = Field(
        default_factory=list,
        description="Tool names explicitly approved for execution in this context"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context metadata"
    )

    class Config:
        arbitrary_types_allowed = True


class AgentResult(BaseModel):
    """Standardized result from agent execution"""
    success: bool = Field(..., description="Whether execution succeeded")
    agent_name: str = Field(..., description="Name of agent that produced this result")
    agent_id: UUID = Field(..., description="ID of agent instance")
    result_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured result data"
    )
    output_text: Optional[str] = Field(None, description="Human-readable output")
    tools_used: List[str] = Field(
        default_factory=list,
        description="Tools used during execution"
    )
    iterations_used: int = Field(default=0, description="Number of iterations executed")
    tokens_used: Dict[str, int] = Field(
        default_factory=dict,
        description="Token usage (input_tokens, output_tokens, total_tokens)"
    )
    cost_estimate: float = Field(default=0.0, description="Estimated cost in USD")
    execution_time_seconds: float = Field(default=0.0, description="Execution time")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    requires_approval: bool = Field(
        default=False,
        description="Whether next step requires approval"
    )
    requires_human_input: bool = Field(
        default=False,
        description="Whether next step requires human input"
    )
    checkpoint_created: bool = Field(
        default=False,
        description="Whether checkpoint was created for resume"
    )
    next_actions: List[str] = Field(
        default_factory=list,
        description="Suggested next actions"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional result metadata"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        arbitrary_types_allowed = True


class AgentError(Exception):
    """Base exception for agent errors"""
    def __init__(self, message: str, agent_name: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.agent_name = agent_name
        self.details = details or {}
        super().__init__(self.message)


class AgentValidationError(AgentError):
    """Raised when agent input validation fails"""
    pass


class AgentExecutionError(AgentError):
    """Raised when agent execution fails"""
    pass


class AgentAuthorizationError(AgentError):
    """Raised when agent lacks authority for an action"""
    pass


class AgentBase(ABC):
    """
    Abstract base class for all JARV agents.

    All agents must inherit from this class and implement the required methods.
    This ensures consistent interface, logging, error handling, and authority
    management across all agents.
    """

    def __init__(self, config: AgentConfig):
        """
        Initialize agent with configuration.

        Args:
            config: Agent configuration including authority, tools, and settings
        """
        self.config = config
        self.logger = logging.getLogger(f"agent.{self.name}")
        self._execution_start_time: Optional[float] = None

        # Log agent initialization
        self.logger.info(
            f"Initialized {self.name} agent",
            extra={
                "agent_id": str(config.agent_id),
                "authority_level": config.authority_level.value,
                "allowed_tools": config.allowed_tools,
                "model": config.model,
            }
        )

    # ===== Required Properties =====

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Agent name (unique identifier).

        Example: "orchestrator", "code-writer", "test-runner"
        """
        pass

    @property
    @abstractmethod
    def role(self) -> str:
        """
        Agent role description.

        Example: "Coordinates tasks and delegates to specialist agents"
        """
        pass

    @property
    @abstractmethod
    def input_schema(self) -> Type[BaseModel]:
        """
        Pydantic model defining expected input structure.

        Must be a Pydantic BaseModel subclass that validates agent inputs.
        """
        pass

    @property
    @abstractmethod
    def output_schema(self) -> Type[BaseModel]:
        """
        Pydantic model defining output structure.

        Must be a Pydantic BaseModel subclass that validates agent outputs.
        """
        pass

    @property
    @abstractmethod
    def required_authority_level(self) -> AuthorityLevel:
        """
        Minimum authority level required to run this agent.

        Agents cannot execute if user authority < required authority.
        """
        pass

    @property
    def default_tools(self) -> List[str]:
        """
        Default tools this agent typically uses.

        Can be overridden by config.allowed_tools. Empty list means no tools.
        """
        return []

    # ===== Core Methods =====

    @abstractmethod
    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """
        Execute agent with given input and context.

        This is the main execution method that must be implemented by all agents.

        Args:
            input_data: Input data validated against input_schema
            context: Execution context with workspace, memory, etc.

        Returns:
            AgentResult with execution results

        Raises:
            AgentValidationError: If input validation fails
            AgentExecutionError: If execution fails
            AgentAuthorizationError: If agent lacks required authority
        """
        pass

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """
        Execute agent with validation, logging, and error handling.

        This is the public entry point that wraps run() with standard
        validation, logging, and error handling.

        Every execution is logged to the AuditLog table for complete traceability.

        Args:
            input_data: Raw input data (will be validated)
            context: Execution context

        Returns:
            AgentResult with execution results
        """
        import time

        self._execution_start_time = time.time()
        knowledge_token = None

        # Audit log: Agent execution start
        await self._audit_start(input_data, context)

        try:
            # Log execution start
            self.logger.info(
                f"Starting execution of {self.name}",
                extra={
                    "agent_id": str(self.config.agent_id),
                    "workspace_id": str(context.workspace_id) if context.workspace_id else None,
                    "task_id": str(context.task_id) if context.task_id else None,
                }
            )

            # Validate authority
            self._validate_authority()

            # Validate input
            validated_input = self._validate_input(input_data)

            from app.core.agents.registry import get_registry
            from app.core.knowledge.context import set_knowledge_context
            from app.core.knowledge.service import knowledge_service

            if (self.name in get_registry().REQUIRED_AGENTS
                    and not context.metadata.get("specialist_knowledge_ids")):
                from app.core.config import settings

                if context.db_session is not None:
                    knowledge = await knowledge_service.retrieve(
                        context.db_session, agent_name=self.name,
                        query=" ".join(str(value) for value in validated_input.values()
                                       if isinstance(value, (str, list))),
                        limit=3,
                    )
                elif settings.TESTING:
                    knowledge = []
                else:
                    from app.core.database import AsyncSessionLocal

                    async with AsyncSessionLocal() as knowledge_db:
                        knowledge = await knowledge_service.retrieve(
                            knowledge_db, agent_name=self.name,
                            query=" ".join(str(value) for value in validated_input.values()
                                           if isinstance(value, (str, list))),
                            limit=3,
                        )
                if not knowledge and not settings.TESTING:
                    raise AgentExecutionError(
                        message=f"No verified specialist knowledge available for {self.name}",
                        agent_name=self.name,
                    )
                if knowledge:
                    context.knowledge_context = knowledge
                    context.metadata["specialist_knowledge_ids"] = [
                        item["id"] for item in knowledge
                    ]
            if context.knowledge_context:
                knowledge_token = set_knowledge_context(context.knowledge_context)

            # Recall workspace memory and verified lessons (Repair 11).
            task_query = " ".join(str(value) for value in validated_input.values()
                                  if isinstance(value, (str, list)))[:2000]
            applied_lessons, recall_token = await self._recall(context, task_query)

            # Execute agent
            try:
                result = await self.run(validated_input, context)
            except Exception as run_error:
                await self._learn(context, task_query, None, applied_lessons, run_error)
                raise
            finally:
                if recall_token is not None:
                    from app.core.memory.context import set_recall_context

                    set_recall_context([], [], reset_token=recall_token)
            await self._learn(context, task_query, result, applied_lessons, None)
            result.metadata["recalled_memory_ids"] = [m["id"] for m in context.memory_context
                                                      if isinstance(m, dict) and "id" in m]
            result.metadata["applied_lessons"] = [{"id": item["id"], "lesson_key": item["lesson_key"]}
                                                  for item in applied_lessons]
            result.metadata["specialist_knowledge"] = [{
                "id": item["id"],
                "title": item["title"],
                "source_url": item["source_url"],
                "version": item["version"],
            } for item in context.knowledge_context]

            # Calculate execution time
            execution_time = time.time() - self._execution_start_time
            result.execution_time_seconds = execution_time

            # Log execution completion
            self.logger.info(
                f"Completed execution of {self.name}",
                extra={
                    "agent_id": str(self.config.agent_id),
                    "success": result.success,
                    "execution_time": f"{execution_time:.2f}s",
                    "tokens_used": result.tokens_used.get("total_tokens", 0),
                    "cost_estimate": f"${result.cost_estimate:.6f}",
                }
            )

            # Audit log: Agent execution complete
            await self._audit_complete(result, context)

            return result

        except AgentError as e:
            # Audit log: Agent execution error
            await self._audit_error(e, context)
            # Re-raise agent-specific errors
            raise

        except Exception as e:
            # Wrap unexpected errors
            self.logger.error(
                f"Unexpected error in {self.name}",
                extra={
                    "agent_id": str(self.config.agent_id),
                    "error": str(e),
                },
                exc_info=True,
            )
            error = AgentExecutionError(
                message=f"Unexpected error in {self.name}: {str(e)}",
                agent_name=self.name,
                details={"original_error": str(e)},
            )
            # Audit log: Agent execution error
            await self._audit_error(error, context)
            raise error
        finally:
            if knowledge_token is not None:
                from app.core.knowledge.context import set_knowledge_context

                set_knowledge_context((), reset_token=knowledge_token)

    # ===== Memory and verified learning (Repair 11) =====

    def _learning_enabled(self, context: AgentContext) -> bool:
        """Recall and capture run whenever the agent has a database session and a
        workspace. The unit-test suite opts in per test via
        ``context.metadata["learning_enabled"]`` so unrelated tests see no extra rows."""
        if context.db_session is None or context.workspace_id is None:
            return False
        from app.core.config import settings

        return bool(context.metadata.get("learning_enabled", not settings.TESTING))

    async def _recall(self, context: AgentContext, task_query: str):
        """Load relevant workspace memory and verified lessons into this task's prompt."""
        if not self._learning_enabled(context) or not task_query.strip():
            return [], None
        from app.core.jarv_memory import memory_service
        from app.core.learning import learning_service
        from app.core.memory.context import set_recall_context

        try:
            hits = await memory_service.search_scored(
                context.db_session, task_query, limit=5, workspace_id=context.workspace_id,
            )
            memories = [hit.as_dict() for hit in hits]
            lessons = await learning_service.retrieve_lessons(
                context.db_session, workspace_id=context.workspace_id,
                agent_name=self.name, query=task_query, limit=3,
            )
        except Exception as exc:  # noqa: BLE001 - recall is advisory; the task still runs
            self.logger.warning(f"Memory recall failed for {self.name}: {exc}")
            return [], None
        known = {m.get("id") for m in context.memory_context if isinstance(m, dict)}
        context.memory_context = list(context.memory_context) + [
            m for m in memories if m["id"] not in known]
        if not memories and not lessons:
            return [], None
        self.logger.info(
            f"{self.name} recalled {len(memories)} memories and {len(lessons)} verified lessons",
            extra={"workspace_id": str(context.workspace_id)},
        )
        return lessons, set_recall_context(memories, lessons)

    async def _learn(
        self,
        context: AgentContext,
        task_query: str,
        result: Optional["AgentResult"],
        applied_lessons: List[Dict[str, Any]],
        error: Optional[BaseException],
    ) -> None:
        """Record the outcome as experience, memory, and lesson performance."""
        if not self._learning_enabled(context):
            return
        from app.core.learning import learning_service

        succeeded = error is None and result is not None and result.success
        if error is not None:
            outcome, observed = "failure", f"{type(error).__name__}: {error}"
        elif result is None:
            return
        else:
            outcome = "success" if result.success else "failure"
            observed = result.error_message or result.output_text or ""
        tools = list(result.tools_used) if result is not None else []
        try:
            await learning_service.record_experience(
                context.db_session,
                workspace_id=context.workspace_id,
                agent_name=self.name,
                situation=task_query or self.role,
                action=(f"{self.role}; tools: {', '.join(tools)}" if tools else self.role),
                result=observed[:1500] or outcome,
                outcome=outcome,
                task_id=context.task_id,
                tools_used=tools,
                agent_id=self.config.agent_id,
                meta={"parent_agent_id": str(context.parent_agent_id) if context.parent_agent_id else None},
            )
            if applied_lessons:
                await learning_service.record_application(
                    context.db_session, workspace_id=context.workspace_id,
                    lesson_keys=[item["lesson_key"] for item in applied_lessons],
                    success=succeeded,
                )
        except Exception as exc:  # noqa: BLE001 - never mask the task's own result
            self.logger.warning(f"Experience capture failed for {self.name}: {exc}")

    # ===== Validation Methods =====

    def _validate_authority(self) -> None:
        """
        Validate agent has required authority level.

        Raises:
            AgentAuthorizationError: If authority level insufficient
        """
        if self.config.authority_level < self.required_authority_level:
            raise AgentAuthorizationError(
                message=f"Agent {self.name} requires authority level "
                        f"{self.required_authority_level.value} but has "
                        f"{self.config.authority_level.value}",
                agent_name=self.name,
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
            AgentValidationError: If validation fails
        """
        try:
            validated = self.input_schema(**input_data)
            return validated.dict()
        except Exception as e:
            raise AgentValidationError(
                message=f"Input validation failed for {self.name}: {str(e)}",
                agent_name=self.name,
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
            AgentValidationError: If validation fails
        """
        try:
            validated = self.output_schema(**output_data)
            return validated.dict()
        except Exception as e:
            self.logger.warning(
                f"Output validation failed for {self.name}: {str(e)}",
                extra={"output_data": output_data}
            )
            raise AgentValidationError(
                message=f"Output validation failed for {self.name}: {str(e)}",
                agent_name=self.name,
                details={"validation_error": str(e), "output_data": output_data}
            )

    # ===== Tool Management =====

    def can_use_tool(self, tool_name: str) -> bool:
        """
        Check if agent is allowed to use a specific tool.

        Args:
            tool_name: Name of tool to check

        Returns:
            True if tool is allowed, False otherwise
        """
        # If no tools are explicitly configured, fall back to this agent's
        # declared defaults. An empty catalog means NO tool access -- never
        # wildcard access.
        allowed = self.config.allowed_tools or self.default_tools
        return tool_name in allowed

    def get_allowed_tools(self) -> List[str]:
        """
        Get list of tools this agent can use.

        Returns:
            List of allowed tool names
        """
        return self.config.allowed_tools or self.default_tools

    async def execute_tool(
        self,
        tool_name: str,
        input_data: Dict[str, Any],
        context: "AgentContext",
    ):
        """Execute a registered tool through the real tool path, carrying context.

        This is the normal agent -> tool path. It builds a ToolConfig from the
        agent's own config (authority, workspace, agent, user, session) and a
        ToolContext that carries the DB session and approval state from the
        AgentContext, then runs the tool via ToolBase.execute (which enforces
        approval and writes a ToolRun when a DB session + agent_id are present).

        Returns the tool's ToolResult, or a ToolResult-shaped error object if the
        tool is unavailable / not permitted. Never raises for a missing tool.
        """
        from app.core.tools.base import ToolConfig, ToolContext, ToolResult
        from app.core.tools.registry import create_tool

        if not self.can_use_tool(tool_name):
            return ToolResult(
                success=False, tool_name=tool_name, tool_id=uuid4(),
                result_data={"blocked": True, "reason": f"agent {self.name} is not permitted tool {tool_name}"},
                error_message="tool not permitted for this agent",
            )

        tool_config = ToolConfig(
            workspace_id=context.workspace_id or self.config.workspace_id,
            user_id=context.user_id or self.config.user_id,
            agent_id=self.config.agent_id,
            task_id=context.task_id,
            session_id=context.session_id or self.config.session_id,
            authority_level=self.config.authority_level,
        )
        tool = create_tool(tool_name, tool_config)
        if tool is None:
            return ToolResult(
                success=False, tool_name=tool_name, tool_id=tool_config.tool_id,
                result_data={"reason": f"tool {tool_name} not found in registry"},
                error_message="tool not found",
            )

        tool_context = ToolContext(
            workspace_id=context.workspace_id or self.config.workspace_id,
            user_id=context.user_id or self.config.user_id,
            agent_id=self.config.agent_id,
            task_id=context.task_id,
            session_id=context.session_id or self.config.session_id,
            approval_granted=bool(getattr(context, "approval_granted", False)),
            approved_tools=list(getattr(context, "approved_tools", []) or []),
            db_session=getattr(context, "db_session", None),
            metadata=dict(getattr(context, "metadata", {}) or {}),
        )
        return await tool.execute(input_data, tool_context)

    # ===== Memory Access =====

    def can_access_memory(self) -> bool:
        """
        Check if agent can access memory system.

        Returns:
            True if memory access is enabled
        """
        return self.config.enable_memory

    # ===== Utility Methods =====

    def create_result(
        self,
        success: bool,
        result_data: Optional[Dict[str, Any]] = None,
        output_text: Optional[str] = None,
        error_message: Optional[str] = None,
        **kwargs
    ) -> AgentResult:
        """
        Create standardized AgentResult.

        Args:
            success: Whether execution succeeded
            result_data: Structured result data
            output_text: Human-readable output
            error_message: Error message if failed
            **kwargs: Additional AgentResult fields

        Returns:
            AgentResult instance
        """
        return AgentResult(
            success=success,
            agent_name=self.name,
            agent_id=self.config.agent_id,
            result_data=result_data or {},
            output_text=output_text,
            error_message=error_message,
            **kwargs
        )

    # ===== Audit Logging Methods =====

    async def _audit_start(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> None:
        """
        Log agent execution start to audit trail.

        Args:
            input_data: Agent input data
            context: Execution context
        """
        try:
            if context.db_session is not None:
                from app.core.audit import AuditLogger

                await AuditLogger.log_agent_start(
                    session=context.db_session,
                    agent_name=self.name,
                    user_id=context.user_id,
                    workspace_id=context.workspace_id,
                    agent_id=self.config.agent_id,
                    task_id=context.task_id,
                    session_id=context.session_id,
                    parent_agent_id=context.parent_agent_id,
                    input_data=input_data,
                )
            else:
                from app.core.audit import audit_agent_start

                await audit_agent_start(
                    agent_name=self.name,
                    user_id=context.user_id,
                    workspace_id=context.workspace_id,
                    agent_id=self.config.agent_id,
                    task_id=context.task_id,
                    session_id=context.session_id,
                    parent_agent_id=context.parent_agent_id,
                    input_data=input_data,
                )
        except Exception as e:
            # Don't fail execution if audit logging fails
            self.logger.warning(
                f"Failed to audit agent start: {e}",
                extra={"agent_name": self.name}
            )

    async def _audit_complete(
        self,
        result: "AgentResult",
        context: AgentContext,
    ) -> None:
        """
        Log agent execution completion to audit trail.

        Args:
            result: Agent execution result
            context: Execution context
        """
        try:
            if context.db_session is not None:
                from app.core.audit import AuditLogger

                await AuditLogger.log_agent_complete(
                    session=context.db_session,
                    agent_name=self.name,
                    result="success" if result.success else "failure",
                    execution_time=result.execution_time_seconds,
                    tokens_used=result.tokens_used,
                    cost_estimate=result.cost_estimate,
                    user_id=context.user_id,
                    workspace_id=context.workspace_id,
                    agent_id=self.config.agent_id,
                    task_id=context.task_id,
                    session_id=context.session_id,
                    parent_agent_id=context.parent_agent_id,
                    output_data=result.result_data,
                )
            else:
                from app.core.audit import audit_agent_complete

                await audit_agent_complete(
                    agent_name=self.name,
                    result="success" if result.success else "failure",
                    execution_time=result.execution_time_seconds,
                    tokens_used=result.tokens_used,
                    cost_estimate=result.cost_estimate,
                    user_id=context.user_id,
                    workspace_id=context.workspace_id,
                    agent_id=self.config.agent_id,
                    task_id=context.task_id,
                    session_id=context.session_id,
                    parent_agent_id=context.parent_agent_id,
                    output_data=result.result_data,
                )
        except Exception as e:
            # Don't fail execution if audit logging fails
            self.logger.warning(
                f"Failed to audit agent completion: {e}",
                extra={"agent_name": self.name}
            )

    async def _audit_error(
        self,
        error: Exception,
        context: AgentContext,
    ) -> None:
        """
        Log agent execution error to audit trail.

        Args:
            error: Exception that occurred
            context: Execution context
        """
        try:
            if context.db_session is not None:
                from app.core.audit import AuditLogger

                await AuditLogger.log_agent_error(
                    session=context.db_session,
                    agent_name=self.name,
                    error_message=str(error),
                    error_type=type(error).__name__,
                    user_id=context.user_id,
                    workspace_id=context.workspace_id,
                    agent_id=self.config.agent_id,
                    task_id=context.task_id,
                    session_id=context.session_id,
                    parent_agent_id=context.parent_agent_id,
                    stack_trace=traceback.format_exc(),
                )
            else:
                from app.core.audit import audit_agent_error

                await audit_agent_error(
                    agent_name=self.name,
                    error_message=str(error),
                    error_type=type(error).__name__,
                    user_id=context.user_id,
                    workspace_id=context.workspace_id,
                    agent_id=self.config.agent_id,
                    task_id=context.task_id,
                    session_id=context.session_id,
                    parent_agent_id=context.parent_agent_id,
                    stack_trace=traceback.format_exc(),
                )
        except Exception as e:
            # Don't fail execution if audit logging fails
            self.logger.warning(
                f"Failed to audit agent error: {e}",
                extra={"agent_name": self.name}
            )

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"name={self.name} "
            f"authority={self.config.authority_level.value}>"
        )
