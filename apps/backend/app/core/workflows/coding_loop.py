"""
JARV Backend - Coding Debug Build Loop

Automated workflow that orchestrates coding, debugging, verification, and QA agents
in an iterative loop to develop and refine code until it meets quality standards.

Workflow:
1. Coding Agent: Generate or modify code
2. Build Check: Attempt to run/compile
3. If errors: Debugging Agent analyzes and fixes
4. QA Agent: Run tests
5. Verifier Agent: Check quality standards
6. Loop until success or max iterations
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
import logging

from app.core.agents.registry import get_registry
from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel

logger = logging.getLogger(__name__)


class LoopStatus(str, Enum):
    """Status of the coding loop"""
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    MAX_ITERATIONS = "max_iterations_reached"


@dataclass
class LoopIteration:
    """Single iteration of the loop"""
    iteration_number: int
    agent_used: str
    action_taken: str
    result: Dict[str, Any]
    errors: List[str]
    success: bool


@dataclass
class LoopResult:
    """Final result of the coding loop"""
    status: LoopStatus
    iterations: List[LoopIteration]
    total_iterations: int
    final_code_quality: float
    test_coverage: float
    errors_fixed: int
    final_output: Dict[str, Any]


class CodingDebugBuildLoop:
    """
    Orchestrated workflow for iterative code development.

    This workflow demonstrates the power of multiple specialist agents
    working together to achieve a complex goal.
    """

    def __init__(
        self,
        workspace_id: str,
        session_id: str,
        max_iterations: int = 5,
        quality_threshold: float = 80.0,
        coverage_threshold: float = 75.0,
    ):
        """
        Initialize coding loop.

        Args:
            workspace_id: Workspace ID for context
            session_id: Session ID for tracking
            max_iterations: Maximum loop iterations
            quality_threshold: Minimum quality score to succeed
            coverage_threshold: Minimum test coverage to succeed
        """
        self.workspace_id = workspace_id
        self.session_id = session_id
        self.max_iterations = max_iterations
        self.quality_threshold = quality_threshold
        self.coverage_threshold = coverage_threshold

        self.registry = get_registry()
        self.logger = logging.getLogger(__name__)

        # Initialize agent configs
        self.coding_config = AgentConfig(
            authority_level=AuthorityLevel.LEVEL_3_CODE_EXECUTION
        )
        self.debug_config = AgentConfig(
            authority_level=AuthorityLevel.LEVEL_3_CODE_EXECUTION
        )
        self.qa_config = AgentConfig(
            authority_level=AuthorityLevel.LEVEL_3_CODE_EXECUTION
        )
        self.verify_config = AgentConfig(
            authority_level=AuthorityLevel.LEVEL_3_CODE_EXECUTION
        )

    async def run(
        self,
        task: str,
        language: str,
        requirements: str = "",
        existing_files: List[str] = None,
    ) -> LoopResult:
        """
        Run the coding debug build loop.

        Args:
            task: Coding task description
            language: Programming language
            requirements: Specific requirements
            existing_files: List of existing files to modify

        Returns:
            LoopResult with final status and details
        """
        self.logger.info(f"Starting coding loop: {task}")

        iterations: List[LoopIteration] = []
        current_code = None
        current_files = existing_files or []
        errors = []
        errors_fixed = 0

        context = AgentContext(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
        )

        for iteration in range(1, self.max_iterations + 1):
            self.logger.info(f"Loop iteration {iteration}/{self.max_iterations}")

            # STEP 1: Coding Agent generates/modifies code
            coding_result = await self._run_coding_agent(
                task=task,
                language=language,
                requirements=requirements,
                files=current_files,
                previous_errors=errors,
                context=context,
            )

            iterations.append(LoopIteration(
                iteration_number=iteration,
                agent_used="coding_agent",
                action_taken="Generated/modified code",
                result=coding_result.result_data,
                errors=[],
                success=coding_result.success,
            ))

            if not coding_result.success:
                self.logger.error("Coding agent failed")
                continue

            current_files = coding_result.result_data.get("files_modified", [])

            # STEP 2: Build check (simulated)
            build_errors = self._simulate_build_check(coding_result.result_data)

            if build_errors:
                self.logger.info(f"Build errors detected: {len(build_errors)}")

                # STEP 3: Debugging Agent analyzes errors
                debug_result = await self._run_debugging_agent(
                    errors=build_errors,
                    files=current_files,
                    context=context,
                )

                iterations.append(LoopIteration(
                    iteration_number=iteration,
                    agent_used="debugging_agent",
                    action_taken="Analyzed and proposed fixes",
                    result=debug_result.result_data,
                    errors=build_errors,
                    success=debug_result.success,
                ))

                if debug_result.success:
                    errors_fixed += len(build_errors)
                    errors = []
                else:
                    errors = build_errors
                    continue

            # STEP 4: QA Agent runs tests
            qa_result = await self._run_qa_agent(
                test_type="unit",
                target_files=current_files,
                context=context,
            )

            iterations.append(LoopIteration(
                iteration_number=iteration,
                agent_used="qa_agent",
                action_taken="Ran tests",
                result=qa_result.result_data,
                errors=[],
                success=qa_result.success,
            ))

            test_coverage = qa_result.result_data.get("coverage_percentage", 0.0)
            tests_passed = qa_result.success

            if not tests_passed:
                self.logger.info("Tests failed, continuing iteration")
                errors = ["Test failures detected"]
                continue

            # STEP 5: Verifier Agent checks quality
            verify_result = await self._run_verifier_agent(
                code_to_verify=str(current_files),
                test_files=current_files,
                context=context,
            )

            iterations.append(LoopIteration(
                iteration_number=iteration,
                agent_used="verifier_agent",
                action_taken="Verified code quality",
                result=verify_result.result_data,
                errors=[],
                success=verify_result.success,
            ))

            quality_score = verify_result.result_data.get("quality_score", 0.0)
            verified = verify_result.result_data.get("verified", False)

            # Check success criteria
            if (verified and
                quality_score >= self.quality_threshold and
                test_coverage >= self.coverage_threshold):

                self.logger.info(
                    f"Loop succeeded: quality={quality_score}, coverage={test_coverage}"
                )

                return LoopResult(
                    status=LoopStatus.SUCCESS,
                    iterations=iterations,
                    total_iterations=iteration,
                    final_code_quality=quality_score,
                    test_coverage=test_coverage,
                    errors_fixed=errors_fixed,
                    final_output={
                        "files": current_files,
                        "quality_score": quality_score,
                        "test_coverage": test_coverage,
                    },
                )

        # Max iterations reached
        self.logger.warning(f"Max iterations ({self.max_iterations}) reached")

        # Get final metrics from last iteration
        final_quality = 0.0
        final_coverage = 0.0
        if iterations:
            for it in reversed(iterations):
                if it.agent_used == "verifier_agent":
                    final_quality = it.result.get("quality_score", 0.0)
                    break
            for it in reversed(iterations):
                if it.agent_used == "qa_agent":
                    final_coverage = it.result.get("coverage_percentage", 0.0)
                    break

        return LoopResult(
            status=LoopStatus.MAX_ITERATIONS,
            iterations=iterations,
            total_iterations=self.max_iterations,
            final_code_quality=final_quality,
            test_coverage=final_coverage,
            errors_fixed=errors_fixed,
            final_output={
                "files": current_files,
                "partial_completion": True,
            },
        )

    async def _run_coding_agent(
        self,
        task: str,
        language: str,
        requirements: str,
        files: List[str],
        previous_errors: List[str],
        context: AgentContext,
    ):
        """Run coding agent"""
        coding_agent = self.registry.create("coding_agent", self.coding_config)

        input_data = {
            "task": task,
            "language": language,
            "files": files,
            "requirements": requirements,
            "context": {
                "previous_errors": previous_errors,
            },
        }

        return await coding_agent.run(input_data, context)

    async def _run_debugging_agent(
        self,
        errors: List[str],
        files: List[str],
        context: AgentContext,
    ):
        """Run debugging agent"""
        debug_agent = self.registry.create("debugging_agent", self.debug_config)

        input_data = {
            "error_message": "; ".join(errors),
            "affected_files": files,
            "stack_trace": "",
            "reproduction_steps": "",
        }

        return await debug_agent.run(input_data, context)

    async def _run_qa_agent(
        self,
        test_type: str,
        target_files: List[str],
        context: AgentContext,
    ):
        """Run QA agent"""
        qa_agent = self.registry.create("qa", self.qa_config)

        input_data = {
            "test_type": test_type,
            "target_files": target_files,
            "test_plan": "",
        }

        return await qa_agent.run(input_data, context)

    async def _run_verifier_agent(
        self,
        code_to_verify: str,
        test_files: List[str],
        context: AgentContext,
    ):
        """Run verifier agent"""
        verifier_agent = self.registry.create("verifier", self.verify_config)

        input_data = {
            "code_to_verify": code_to_verify,
            "test_files": test_files,
            "quality_standards": {},
        }

        return await verifier_agent.run(input_data, context)

    def _simulate_build_check(self, coding_result: Dict[str, Any]) -> List[str]:
        """
        Simulate build/compilation check.

        In production, this would actually compile/run the code and capture errors.
        For now, we simulate based on code quality score.
        """
        quality_score = coding_result.get("code_quality_score", 90.0)
        lint_passed = coding_result.get("lint_passed", True)

        errors = []

        # Simulate errors based on quality
        if not lint_passed:
            errors.append("Linting errors detected")

        if quality_score < 70:
            errors.append("Code quality below acceptable threshold")

        # Random simulation: sometimes introduce errors for testing
        # In production, this would be real build output

        return errors


async def run_coding_loop(
    task: str,
    language: str,
    workspace_id: str,
    session_id: str,
    requirements: str = "",
    existing_files: List[str] = None,
    max_iterations: int = 5,
    quality_threshold: float = 80.0,
    coverage_threshold: float = 75.0,
) -> LoopResult:
    """
    Convenience function to run a coding debug build loop.

    Args:
        task: Coding task description
        language: Programming language
        workspace_id: Workspace ID
        session_id: Session ID
        requirements: Specific requirements
        existing_files: Existing files to modify
        max_iterations: Maximum loop iterations
        quality_threshold: Minimum quality score
        coverage_threshold: Minimum test coverage

    Returns:
        LoopResult with final status
    """
    loop = CodingDebugBuildLoop(
        workspace_id=workspace_id,
        session_id=session_id,
        max_iterations=max_iterations,
        quality_threshold=quality_threshold,
        coverage_threshold=coverage_threshold,
    )

    return await loop.run(
        task=task,
        language=language,
        requirements=requirements,
        existing_files=existing_files,
    )
