"""
JARV Backend - QAAgent

Performs real, honest quality assurance on target files.

This agent does NOT simulate test execution and does NOT invent coverage
numbers. It runs a real static compile check (Python stdlib `py_compile`) on
the Python files it is given — that genuinely executes and either passes or
fails with a real error. It reports exactly what it attempted, what it could
not do, and the real failures.

Arbitrary shell/test-runner commands are NOT executed here: running approved
build/test commands requires the authority/approval pipeline (the DB-backed
CommandService), which is not available to an isolated agent. When such a
command is requested, the agent returns a truthful blocked / needs-approval
result instead of pretending it ran.
"""
from typing import Dict, Any, List, Type
import os
import py_compile
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class QAAgentInput(BaseModel):
    """QAAgent input"""
    test_type: str = Field(..., description="Type of QA: compile, unit, integration, e2e")
    target_files: List[str] = Field(default_factory=list, description="Files to check")
    test_plan: str = Field(default="")
    test_command: str = Field(default="", description="Optional shell test command (gated)")


class QAAgentOutput(BaseModel):
    """QAAgent output (honest; no fabricated coverage or test counts)."""
    test_type: str
    targets_provided: int
    files_checked: int
    files_passed: int
    files_failed: int
    checks: List[Dict[str, str]]
    commands_attempted: List[str]
    commands_blocked: List[str]
    failures: List[Dict[str, str]]
    limitations: List[str]
    recommended_next_action: str


class QAAgent(AgentBase):
    """QAAgent - real static-check QA with honest blocked/limitations reporting."""

    @property
    def name(self) -> str:
        return "qa"

    @property
    def role(self) -> str:
        return "Performs quality assurance, testing, and validation"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return QAAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return QAAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def default_tools(self) -> List[str]:
        return ['file_read', 'command_run', 'analyze_code']

    def _resolve(self, candidate: str, context: AgentContext) -> str:
        """Resolve a target file path against likely roots (no fabrication)."""
        if not candidate:
            return candidate
        if os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
        # Try a workspace path from context metadata if present.
        meta = getattr(context, "metadata", None) or {}
        ws_path = meta.get("workspace_path") or meta.get("folder_path")
        if ws_path:
            p = os.path.join(ws_path, candidate)
            if os.path.exists(p):
                return p
        # Fall back to current working directory.
        cwd_p = os.path.abspath(candidate)
        return cwd_p

    async def run(self, input_data: Dict[str, Any], context: AgentContext) -> AgentResult:
        try:
            test_type = input_data.get("test_type", "compile")
            target_files = list(input_data.get("target_files", []) or [])
            test_command = (input_data.get("test_command") or "").strip()

            self.logger.info(
                f"QA run: type={test_type} targets={len(target_files)} "
                f"command={'yes' if test_command else 'no'}"
            )

            checks: List[Dict[str, str]] = []
            commands_attempted: List[str] = []
            commands_blocked: List[str] = []
            failures: List[Dict[str, str]] = []
            limitations: List[str] = []

            files_checked = 0
            files_passed = 0
            files_failed = 0

            # ---- Real static checks on provided target files -----------------
            for raw in target_files:
                path = self._resolve(raw, context)
                if not os.path.exists(path):
                    checks.append({"file": raw, "check": "exists", "result": "missing"})
                    limitations.append(f"Target not found, skipped: {raw}")
                    continue
                if not path.endswith(".py"):
                    checks.append({"file": raw, "check": "py_compile", "result": "skipped_non_python"})
                    limitations.append(f"Non-Python file not statically checked: {raw}")
                    continue

                files_checked += 1
                commands_attempted.append(f"py_compile {path}")
                try:
                    py_compile.compile(path, doraise=True)
                    files_passed += 1
                    checks.append({"file": raw, "check": "py_compile", "result": "passed"})
                except py_compile.PyCompileError as e:
                    files_failed += 1
                    detail = str(e).strip()[:500]
                    checks.append({"file": raw, "check": "py_compile", "result": "failed"})
                    failures.append({"file": raw, "error": detail})
                except Exception as e:  # noqa: BLE001 - real, unexpected compile error
                    files_failed += 1
                    detail = f"{type(e).__name__}: {e}"[:500]
                    checks.append({"file": raw, "check": "py_compile", "result": "error"})
                    failures.append({"file": raw, "error": detail})

            # ---- Shell/test-runner command: honestly gated -------------------
            if test_command:
                commands_blocked.append(test_command)
                limitations.append(
                    "Arbitrary shell/test-runner command execution requires the "
                    "authority/approval pipeline (DB-backed CommandService), which "
                    "is not available to this standalone agent. Command was NOT run."
                )

            # ---- Honest summary + recommendation -----------------------------
            if not target_files and not test_command:
                limitations.append(
                    "No target files and no test command supplied; no checks were "
                    "executed."
                )
                recommended = (
                    "Provide target_files (e.g. .py modules) for a real compile "
                    "check, or route a test command through the approval pipeline."
                )
            elif files_failed > 0:
                recommended = (
                    f"Fix {files_failed} file(s) that failed py_compile before "
                    "release; see failures for the real errors."
                )
            elif commands_blocked:
                recommended = (
                    "Run the blocked test command through the authority/approval "
                    "pipeline (DevOps/command service) to obtain real test results."
                )
            elif files_checked > 0:
                recommended = (
                    f"{files_passed}/{files_checked} file(s) passed static compile; "
                    "add and run a real test suite via the approval pipeline for "
                    "functional coverage (not measured here)."
                )
            else:
                recommended = (
                    "No Python files were statically checkable; supply Python "
                    "targets or a gated test command."
                )

            limitations.append(
                "This QA pass measures static compilability only; it does not run "
                "a test suite and reports NO coverage percentage."
            )

            output_text = (
                f"QA[{test_type}]: targets={len(target_files)} "
                f"checked={files_checked} passed={files_passed} failed={files_failed} "
                f"blocked_cmds={len(commands_blocked)}"
            )

            # QA is an assessment agent: producing a truthful structured
            # assessment is success, even when some files fail or a command is
            # blocked (those facts live in the result data).
            return self.create_result(
                success=True,
                result_data={
                    "test_type": test_type,
                    "targets_provided": len(target_files),
                    "files_checked": files_checked,
                    "files_passed": files_passed,
                    "files_failed": files_failed,
                    "checks": checks,
                    "commands_attempted": commands_attempted,
                    "commands_blocked": commands_blocked,
                    "failures": failures,
                    "limitations": limitations,
                    "recommended_next_action": recommended,
                },
                output_text=output_text,
                tools_used=(["py_compile"] if commands_attempted else []),
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"qa task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
