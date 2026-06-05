"""
JARV Backend - Coding Agent

Performs REAL, honest local code analysis on provided files.

This agent does NOT write or modify files and does NOT fabricate coverage,
lint, or quality scores. For each provided Python file it runs a real stdlib
`py_compile` check and counts real lines. When an LLM provider is configured and
a task description is present it may add a model-suggested approach, clearly
labelled as model-generated and unverified. It never claims it authored code.
"""
from typing import Dict, Any, List, Type
import os
import py_compile
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists._helpers import (
    resolve_files,
    read_file_safe,
    count_lines,
    provider_configured,
    llm_complete,
    no_provider_limitation,
    task_text,
)

logger = logging.getLogger(__name__)


class CodingAgentInput(BaseModel):
    """Coding agent input"""
    task: str = Field(..., description="Coding task description")
    language: str = Field(..., description="Programming language")
    files: list[str] = Field(default_factory=list, description="Files to modify")
    requirements: str = Field(default="", description="Specific requirements")
    context: Dict[str, Any] = Field(default_factory=dict)


class CodingAgentOutput(BaseModel):
    """Coding agent output (honest local analysis; every field has a default)."""
    code_generated: bool = False
    files_provided: int = 0
    files_analyzed: int = 0
    files_missing: int = 0
    compile_passed: int = 0
    compile_failed: int = 0
    file_reports: List[Dict[str, Any]] = Field(default_factory=list)
    total_code_lines: int = 0
    suggested_approach: str = ""
    provider_used: str = ""
    changes_summary: str = ""
    files_modified: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class CodingAgent(AgentBase):
    """
    Coding Agent - real local code analysis (compile + line metrics).

    It analyses the real Python files it is given, reports genuine compile
    pass/fail and real line counts, and (when a provider is configured) can
    offer a model-suggested approach. It never claims to have written files.
    """

    @property
    def name(self) -> str:
        return "coding_agent"

    @property
    def role(self) -> str:
        return "Writes, modifies, and reviews code across all languages and frameworks"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CodingAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CodingAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_3_CODE_EXECUTION

    @property
    def default_tools(self) -> list[str]:
        return [
            "file_read",
            "file_write",
            "file_search",
            "git_status",
            "git_diff",
            "command_run",
            "analyze_code",
        ]

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            task = task_text(input_data, "task", "requirements")
            language = (input_data.get("language") or "").strip()
            files = list(input_data.get("files", []) or [])

            self.logger.info(f"Coding analysis: task_len={len(task)} files={len(files)}")

            tools_used: List[str] = []
            limitations: List[str] = [
                "This agent analyses provided files; it does NOT write or modify "
                "any file and reports no fabricated coverage/lint/quality scores.",
            ]

            existing, missing = resolve_files(files, context)
            file_reports: List[Dict[str, Any]] = []
            compile_passed = 0
            compile_failed = 0
            files_analyzed = 0
            total_code_lines = 0

            for path in existing:
                report: Dict[str, Any] = {"file": path}
                content = read_file_safe(path)
                if content is not None:
                    metrics = count_lines(content)
                    report["lines"] = metrics
                    total_code_lines += metrics["code"]
                if path.endswith(".py"):
                    files_analyzed += 1
                    tools_used.append("py_compile")
                    try:
                        py_compile.compile(path, doraise=True)
                        compile_passed += 1
                        report["compile"] = "passed"
                    except py_compile.PyCompileError as e:
                        compile_failed += 1
                        report["compile"] = "failed"
                        report["compile_error"] = str(e).strip()[:500]
                    except Exception as e:  # noqa: BLE001 - real unexpected compile error
                        compile_failed += 1
                        report["compile"] = "error"
                        report["compile_error"] = f"{type(e).__name__}: {e}"[:500]
                else:
                    report["compile"] = "skipped_non_python"
                file_reports.append(report)
                if content is None:
                    report["read"] = "unreadable"

            for m in missing:
                file_reports.append({"file": m, "compile": "missing"})
                limitations.append(f"File not found, not analyzed: {m}")

            # Optional model-suggested approach (labelled, unverified).
            suggested_approach = ""
            provider_used = ""
            tokens: Dict[str, int] = {}
            if task and provider_configured():
                llm = await llm_complete(
                    self.config.model,
                    f"Programming language: {language or 'unspecified'}.\n"
                    f"Task: {task}\n\n"
                    "Briefly describe a concrete implementation approach. Do not "
                    "claim any files were written.",
                    system="You are a senior engineer suggesting an approach. You "
                           "have NOT written or run any code.",
                    temperature=self.config.temperature,
                )
                if llm is not None:
                    suggested_approach = llm["text"]
                    provider_used = llm["provider_used"]
                    tokens = llm["tokens"]
                    tools_used.append("model_router")
                    limitations.append(
                        "suggested_approach is model-generated and UNVERIFIED; no "
                        "code was written or executed from it."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; no "
                        "model-suggested approach was produced."
                    )
            elif task and not provider_configured():
                limitations.append(no_provider_limitation())

            if not existing:
                limitations.append(
                    "No existing target files were supplied/resolved; only a "
                    "limited analysis was possible."
                )

            if files_analyzed > 0:
                changes_summary = (
                    f"Analyzed {files_analyzed} Python file(s): "
                    f"{compile_passed} compiled, {compile_failed} failed; "
                    f"{total_code_lines} real code line(s) counted. No files written."
                )
            elif existing:
                changes_summary = (
                    f"Read {len(existing)} file(s) (no Python files to compile); "
                    f"{total_code_lines} real code line(s) counted. No files written."
                )
            else:
                changes_summary = "No files analyzed; no code written or modified."

            output_text = (
                f"Coding analysis: files_provided={len(files)} "
                f"analyzed={files_analyzed} compile_pass={compile_passed} "
                f"compile_fail={compile_failed} code_lines={total_code_lines} "
                f"provider={provider_used or 'none'} (no files written)."
            )

            return self.create_result(
                success=True,
                result_data={
                    "code_generated": False,
                    "files_provided": len(files),
                    "files_analyzed": files_analyzed,
                    "files_missing": len(missing),
                    "compile_passed": compile_passed,
                    "compile_failed": compile_failed,
                    "file_reports": file_reports,
                    "total_code_lines": total_code_lines,
                    "suggested_approach": suggested_approach,
                    "provider_used": provider_used,
                    "changes_summary": changes_summary,
                    "files_modified": [],
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=sorted(set(tools_used)),
                tokens_used=tokens or {},
            )

        except Exception as e:
            self.logger.error(f"Coding task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
