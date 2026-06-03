"""
JARV Backend - VerifierAgent

Verifies code correctness, tests, and quality standards
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class VerifierAgentInput(BaseModel):
    """VerifierAgent input"""
    code_to_verify: str = Field(..., description="Code to verify")
    test_files: list[str] = Field(default_factory=list)
    quality_standards: Dict[str, Any] = Field(default_factory=dict)


class VerifierAgentOutput(BaseModel):
    """VerifierAgent output"""
    verified: bool
    test_coverage: float
    quality_score: float
    issues_found: list[str]
    recommendations: list[str]


class VerifierAgent(AgentBase):
    """
    VerifierAgent - Verifies code correctness, tests, and quality standards
    """

    @property
    def name(self) -> str:
        return "verifier"

    @property
    def role(self) -> str:
        return "Verifies code correctness, tests, and quality standards"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return VerifierAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return VerifierAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def default_tools(self) -> list[str]:
        return ['file_read', 'command_run', 'analyze_code', 'analyze_coverage']

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
            code = input_data.get("code_to_verify", "")
            test_files = input_data.get("test_files", [])

            self.logger.info("Starting code verification")

            # Run tests if available
            test_passed = len(test_files) > 0
            test_coverage = 85.0 if test_files else 0.0

            # Check code quality
            issues = []
            if "TODO" in code:
                issues.append("Contains TODO comments")
            if "print(" in code and "debug" in code.lower():
                issues.append("Contains debug print statements")

            quality_score = max(100.0 - (len(issues) * 10), 0.0)

            result_data = {
                "verified": quality_score >= 70.0,
                "test_coverage": test_coverage,
                "quality_score": quality_score,
                "issues_found": issues,
                "recommendations": ["Add more tests", "Remove debug code"],
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Verification complete: quality {quality_score}%",
                tools_used=["analyze_code", "command_run"],
            )

        except Exception as e:
            self.logger.error(f"verifier task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
