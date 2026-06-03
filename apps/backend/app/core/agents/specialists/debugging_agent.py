"""
JARV Backend - DebuggingAgent

Debugs code, identifies issues, and proposes fixes
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class DebuggingAgentInput(BaseModel):
    """DebuggingAgent input"""
    error_message: str = Field(..., description="Error message or description")
    stack_trace: str = Field(default="", description="Stack trace if available")
    affected_files: list[str] = Field(default_factory=list, description="Files involved")
    reproduction_steps: str = Field(default="", description="Steps to reproduce")
    context: Dict[str, Any] = Field(default_factory=dict)


class DebuggingAgentOutput(BaseModel):
    """DebuggingAgent output"""
    error_identified: bool
    error_category: str  # syntax, runtime, logic, performance, security
    root_cause: str
    affected_components: list[str]
    proposed_fix: str
    fix_confidence: float = Field(ge=0.0, le=1.0)
    requires_testing: bool = True
    related_issues: list[str] = Field(default_factory=list)


class DebuggingAgent(AgentBase):
    """
    DebuggingAgent - Debugs code, identifies issues, and proposes fixes
    """

    @property
    def name(self) -> str:
        return "debugging_agent"

    @property
    def role(self) -> str:
        return "Debugs code, identifies issues, and proposes fixes"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return DebuggingAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return DebuggingAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def default_tools(self) -> list[str]:
        return ['file_read', 'file_search', 'git_diff', 'command_run', 'analyze_code']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """
        Execute task.

        Args:
            input_data: Task input
            context: Execution context

        Returns:
            Agent result
        """
        try:
            error_msg = input_data.get("error_message", "")
            stack_trace = input_data.get("stack_trace", "")
            affected_files = input_data.get("affected_files", [])

            self.logger.info(f"Starting debugging task: {error_msg[:100]}")

            # Classify error
            error_category = self._classify_error(error_msg, stack_trace)

            # Analyze stack trace and files
            root_cause = self._analyze_root_cause(error_msg, stack_trace, error_category)

            # Identify affected components
            components = affected_files if affected_files else self._extract_components(stack_trace)

            # Propose fix
            proposed_fix = self._propose_fix(error_category, root_cause, error_msg)

            # Calculate confidence
            confidence = self._calculate_confidence(error_category, stack_trace, affected_files)

            result_data = {
                "error_identified": True,
                "error_category": error_category,
                "root_cause": root_cause,
                "affected_components": components,
                "proposed_fix": proposed_fix,
                "fix_confidence": confidence,
                "requires_testing": True,
                "related_issues": [],
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Debugged {error_category} error: {root_cause}",
                tools_used=["file_read", "analyze_code"],
            )

        except Exception as e:
            self.logger.error(f"debugging_agent task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )

    def _classify_error(self, error_msg: str, stack_trace: str) -> str:
        """Classify error type"""
        error_msg_lower = error_msg.lower()
        stack_lower = stack_trace.lower()

        if any(kw in error_msg_lower for kw in ["syntax", "invalid syntax", "unexpected token"]):
            return "syntax"
        elif any(kw in error_msg_lower for kw in ["null", "undefined", "not defined", "attributeerror"]):
            return "runtime"
        elif any(kw in error_msg_lower for kw in ["permission", "access denied", "forbidden"]):
            return "security"
        elif any(kw in error_msg_lower for kw in ["timeout", "slow", "performance"]):
            return "performance"
        elif "test" in error_msg_lower or "assert" in error_msg_lower:
            return "logic"
        else:
            return "runtime"

    def _analyze_root_cause(self, error_msg: str, stack_trace: str, category: str) -> str:
        """Analyze root cause"""
        if category == "syntax":
            return f"Syntax error in code: {error_msg[:100]}"
        elif category == "runtime":
            if "null" in error_msg.lower() or "undefined" in error_msg.lower():
                return "Variable accessed before initialization or null reference"
            return f"Runtime error: {error_msg[:100]}"
        elif category == "security":
            return "Permission or authentication issue"
        elif category == "performance":
            return "Performance bottleneck or timeout"
        elif category == "logic":
            return "Logic error in business rules or assertions"
        return "Unknown error"

    def _extract_components(self, stack_trace: str) -> list[str]:
        """Extract affected components from stack trace"""
        # Simple extraction - in production would parse stack trace properly
        if not stack_trace:
            return []
        lines = [l.strip() for l in stack_trace.split("\n") if l.strip()]
        components = []
        for line in lines[:5]:  # Top 5 stack frames
            if ".py" in line or ".js" in line or ".ts" in line:
                components.append(line.split()[0] if line.split() else line[:50])
        return components

    def _propose_fix(self, category: str, root_cause: str, error_msg: str) -> str:
        """Propose fix for the error"""
        if category == "syntax":
            return "Fix syntax error: review and correct the syntax at the indicated line"
        elif category == "runtime":
            if "null" in error_msg.lower():
                return "Add null/undefined check before accessing the variable"
            return "Add error handling and validate inputs"
        elif category == "security":
            return "Review and update permissions or authentication configuration"
        elif category == "performance":
            return "Optimize slow operation or increase timeout threshold"
        elif category == "logic":
            return "Review business logic and update assertions"
        return "Investigate further and apply appropriate fix"

    def _calculate_confidence(self, category: str, stack_trace: str, files: list) -> float:
        """Calculate confidence in diagnosis"""
        confidence = 0.5  # Base confidence
        if category in ["syntax", "runtime"]:
            confidence += 0.2
        if stack_trace:
            confidence += 0.2
        if files:
            confidence += 0.1
        return min(confidence, 1.0)
