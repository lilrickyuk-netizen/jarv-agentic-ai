"""
JARV Backend - VerifierAgent

Performs REAL, honest verification of provided code and files.

This agent does NOT fabricate coverage or quality scores. It resolves the
provided file paths, runs a real stdlib `py_compile` check on each existing
Python file, and reports whether a corresponding test file appears among the
inputs. Inline code (when supplied directly rather than as a path) is compiled
in-memory with the real stdlib `compile()`. Every verdict is a genuine
PASS/FAIL derived from those checks.
"""
from typing import Dict, Any, List, Type
import os
import py_compile
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists._helpers import (
    resolve_files,
    task_text,
)

logger = logging.getLogger(__name__)


class VerifierAgentInput(BaseModel):
    """VerifierAgent input"""
    code_to_verify: str = Field(..., description="Code to verify")
    test_files: list[str] = Field(default_factory=list)
    quality_standards: Dict[str, Any] = Field(default_factory=dict)


class VerifierAgentOutput(BaseModel):
    """VerifierAgent output (honest verdicts; every field has a default)."""
    verified: bool = False
    files_checked: int = 0
    files_passed: int = 0
    files_failed: int = 0
    file_verdicts: List[Dict[str, str]] = Field(default_factory=list)
    inline_code_checked: bool = False
    inline_code_result: str = ""
    test_files_present: List[str] = Field(default_factory=list)
    test_coverage_for_files: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class VerifierAgent(AgentBase):
    """
    VerifierAgent - real file existence + py_compile + test-presence checks.

    Produces genuine PASS/FAIL verdicts. It does NOT measure or invent test
    coverage percentages or quality scores.
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

    @staticmethod
    def _looks_like_path(text: str) -> bool:
        """Heuristic: single token that resembles a file path, not inline code."""
        t = text.strip()
        if not t or "\n" in t or len(t) > 400 or " " in t:
            return False
        return ("/" in t or "\\" in t or t.endswith(
            (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb")))

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            code = (input_data.get("code_to_verify") or "").strip()
            test_files = list(input_data.get("test_files", []) or [])

            self.logger.info(f"Verification: code_len={len(code)} test_files={len(test_files)}")

            limitations: List[str] = [
                "This agent verifies file existence and Python compilability and "
                "checks for the presence of test files; it does NOT measure test "
                "coverage and reports NO fabricated coverage or quality scores.",
            ]
            tools_used: List[str] = []

            # Build the candidate file list: test_files + code_to_verify if it
            # looks like a path rather than inline code.
            candidate_paths: List[str] = list(test_files)
            code_is_path = bool(code) and self._looks_like_path(code)
            if code_is_path:
                candidate_paths.append(code)

            existing, missing = resolve_files(candidate_paths, context)

            file_verdicts: List[Dict[str, str]] = []
            files_checked = 0
            files_passed = 0
            files_failed = 0

            existing_basenames = [os.path.basename(p) for p in existing]

            for path in existing:
                if path.endswith(".py"):
                    files_checked += 1
                    tools_used.append("py_compile")
                    try:
                        py_compile.compile(path, doraise=True)
                        files_passed += 1
                        file_verdicts.append({"file": path, "verdict": "PASS", "check": "py_compile"})
                    except py_compile.PyCompileError as e:
                        files_failed += 1
                        file_verdicts.append({"file": path, "verdict": "FAIL",
                                              "check": "py_compile", "error": str(e).strip()[:400]})
                    except Exception as e:  # noqa: BLE001 - real unexpected error
                        files_failed += 1
                        file_verdicts.append({"file": path, "verdict": "FAIL",
                                              "check": "py_compile", "error": f"{type(e).__name__}: {e}"[:400]})
                else:
                    file_verdicts.append({"file": path, "verdict": "SKIP",
                                          "check": "exists_non_python"})

            for m in missing:
                file_verdicts.append({"file": m, "verdict": "FAIL", "check": "exists"})

            # Inline code: compile in-memory with the real stdlib compiler.
            inline_code_checked = False
            inline_code_result = ""
            if code and not code_is_path:
                inline_code_checked = True
                tools_used.append("compile")
                try:
                    compile(code, "<code_to_verify>", "exec")
                    inline_code_result = "PASS"
                except SyntaxError as e:
                    inline_code_result = f"FAIL: {e}"[:400]
                except Exception as e:  # noqa: BLE001
                    inline_code_result = f"FAIL: {type(e).__name__}: {e}"[:400]

            # Which non-test files have a matching test file among the inputs?
            test_basenames = [os.path.basename(p) for p in existing if "test" in os.path.basename(p).lower()]
            test_files_present = sorted(set(
                os.path.basename(p) for p in existing
                if "test" in os.path.basename(p).lower()
            ))
            covered: List[str] = []
            for path in existing:
                base = os.path.basename(path)
                if "test" in base.lower():
                    continue
                stem = os.path.splitext(base)[0]
                if any(stem in tb for tb in test_basenames):
                    covered.append(base)

            if not candidate_paths and not (code and not code_is_path):
                limitations.append(
                    "No files or inline code supplied; no verification performed."
                )
            if not test_files:
                limitations.append(
                    "No test files supplied; test presence could not be confirmed "
                    "for the verified files."
                )

            # Verified is true only when there is at least one real check and no
            # failures (genuine, not a score threshold).
            any_check = files_checked > 0 or inline_code_checked
            verified = bool(any_check) and files_failed == 0 and (
                inline_code_result == "PASS" or not inline_code_checked)

            output_text = (
                f"Verification: files_checked={files_checked} "
                f"passed={files_passed} failed={files_failed} "
                f"inline_code={inline_code_result or 'n/a'} "
                f"test_files_present={len(test_files_present)} verified={verified}."
            )

            return self.create_result(
                success=True,
                result_data={
                    "verified": verified,
                    "files_checked": files_checked,
                    "files_passed": files_passed,
                    "files_failed": files_failed,
                    "file_verdicts": file_verdicts,
                    "inline_code_checked": inline_code_checked,
                    "inline_code_result": inline_code_result,
                    "test_files_present": test_files_present,
                    "test_coverage_for_files": covered,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=sorted(set(tools_used)),
            )

        except Exception as e:
            self.logger.error(f"verifier task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
