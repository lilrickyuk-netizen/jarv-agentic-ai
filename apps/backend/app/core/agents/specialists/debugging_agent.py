"""
JARV Backend - DebuggingAgent

Performs REAL, honest diagnosis of provided error/log/stack-trace text.

This agent does NOT fix code and does NOT fabricate a confidence score. It
parses the supplied text with real regex to extract exception type names and
file:line references, and reports exactly what it found. When an LLM provider
is configured it may add a model diagnosis, clearly labelled as model-generated
and unverified. It never claims a fix was applied.
"""
from typing import Dict, Any, List, Type
import re
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists._helpers import (
    resolve_files,
    provider_configured,
    llm_complete,
    no_provider_limitation,
    task_text,
)

logger = logging.getLogger(__name__)

# Real extraction patterns (no fabrication).
_EXC_PATTERN = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning))\b")
_FILELINE_PATTERNS = [
    re.compile(r'File "([^"]+)", line (\d+)'),                 # Python traceback
    re.compile(r'([\w./\\-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|rb)):(\d+)'),  # path:line
]


class DebuggingAgentInput(BaseModel):
    """DebuggingAgent input"""
    error_message: str = Field(..., description="Error message or description")
    stack_trace: str = Field(default="", description="Stack trace if available")
    affected_files: list[str] = Field(default_factory=list, description="Files involved")
    reproduction_steps: str = Field(default="", description="Steps to reproduce")
    context: Dict[str, Any] = Field(default_factory=dict)


class DebuggingAgentOutput(BaseModel):
    """DebuggingAgent output (honest parse; every field has a default)."""
    error_identified: bool = False
    exception_types: List[str] = Field(default_factory=list)
    file_references: List[Dict[str, str]] = Field(default_factory=list)
    affected_components: List[str] = Field(default_factory=list)
    resolved_files: List[str] = Field(default_factory=list)
    missing_files: List[str] = Field(default_factory=list)
    model_diagnosis: str = ""
    provider_used: str = ""
    fix_applied: bool = False
    limitations: List[str] = Field(default_factory=list)


class DebuggingAgent(AgentBase):
    """
    DebuggingAgent - real text parsing of errors/stack traces.

    Extracts genuine exception names and file:line references from the provided
    text and (optionally) adds a labelled model diagnosis. It never claims to
    have fixed anything.
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
        try:
            error_msg = (input_data.get("error_message") or "").strip()
            stack_trace = (input_data.get("stack_trace") or "").strip()
            affected_files = list(input_data.get("affected_files", []) or [])
            repro = (input_data.get("reproduction_steps") or "").strip()

            self.logger.info(f"Debugging analysis: error_len={len(error_msg)}")

            text = "\n".join(t for t in (error_msg, stack_trace, repro) if t)
            tools_used: List[str] = []
            limitations: List[str] = [
                "This agent parses the supplied text and resolves provided files; "
                "it does NOT apply fixes and reports no fabricated confidence score.",
            ]

            # Real regex extraction from the provided text.
            exception_types: List[str] = sorted(set(_EXC_PATTERN.findall(text)))
            file_references: List[Dict[str, str]] = []
            seen = set()
            for pat in _FILELINE_PATTERNS:
                for m in pat.finditer(text):
                    key = (m.group(1), m.group(2))
                    if key not in seen:
                        seen.add(key)
                        file_references.append({"file": m.group(1), "line": m.group(2)})

            # Affected components: real, from provided files + parsed references.
            components = list(affected_files)
            for ref in file_references:
                if ref["file"] not in components:
                    components.append(ref["file"])

            existing, missing = resolve_files(affected_files, context)

            error_identified = bool(text)
            if not text:
                limitations.append(
                    "No error/log/stack-trace text supplied; nothing to diagnose."
                )

            # Optional model diagnosis (labelled, unverified).
            model_diagnosis = ""
            provider_used = ""
            tokens: Dict[str, int] = {}
            if text and provider_configured():
                llm = await llm_complete(
                    self.config.model,
                    "Diagnose the likely root cause of this error and suggest a "
                    "fix. Do NOT claim you applied any fix.\n\n"
                    f"Error/log:\n{text[:4000]}",
                    system="You are a debugging assistant. You have NOT edited or "
                           "run any code; only suggest a diagnosis.",
                    temperature=self.config.temperature,
                )
                if llm is not None:
                    model_diagnosis = llm["text"]
                    provider_used = llm["provider_used"]
                    tokens = llm["tokens"]
                    tools_used.append("model_router")
                    limitations.append(
                        "model_diagnosis is model-generated and UNVERIFIED; no fix "
                        "was applied."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; "
                        "returned parsed analysis only."
                    )
            elif text and not provider_configured():
                limitations.append(no_provider_limitation())

            output_text = (
                f"Debugging analysis: exceptions={len(exception_types)} "
                f"file_refs={len(file_references)} "
                f"resolved_files={len(existing)} "
                f"provider={provider_used or 'none'} (no fix applied)."
            )

            return self.create_result(
                success=True,
                result_data={
                    "error_identified": error_identified,
                    "exception_types": exception_types,
                    "file_references": file_references,
                    "affected_components": components,
                    "resolved_files": existing,
                    "missing_files": missing,
                    "model_diagnosis": model_diagnosis,
                    "provider_used": provider_used,
                    "fix_applied": False,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=sorted(set(tools_used)),
                tokens_used=tokens or {},
            )

        except Exception as e:
            self.logger.error(f"debugging_agent task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
