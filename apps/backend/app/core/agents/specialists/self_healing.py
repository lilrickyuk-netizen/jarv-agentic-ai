"""
JARV Backend - SelfHealingAgent

Analyses reported issues and drafts a remediation PLAN.

This agent NEVER fixes or restores a live system. Real healing (restarting
services, applying fixes, deploying changes) requires the monitoring subsystem
plus the approved command/deploy pipeline, none of which are wired into
standalone agent execution. When incident text or files are supplied this agent
does REAL local analysis (static dangerous-code scan of provided files via the
shared helpers) and, when an LLM provider is configured, proposes a remediation
PLAN. Actual healing is reported as blocked. There are no fabricated resolution
times, no false "applied fix" claims, and no false rollback claims.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class SelfHealingAgentInput(BaseModel):
    """SelfHealingAgent input"""
    issue_detected: str = Field(..., description="Issue description")
    affected_system: str = Field(...)
    severity: str = Field(default="medium")
    auto_fix_enabled: bool = Field(default=True)


class SelfHealingAgentOutput(BaseModel):
    """SelfHealingAgent output (honest; analysis + plan only, no live healing)."""
    affected_system: str = ""
    severity: str = ""
    blocked: bool = True
    files_analyzed: List[str] = Field(default_factory=list)
    findings: List[Dict[str, str]] = Field(default_factory=list)
    remediation_plan: List[str] = Field(default_factory=list)
    provider_used: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


class SelfHealingAgent(AgentBase):
    """
    SelfHealingAgent - Automatically detects and fixes system issues
    """

    @property
    def name(self) -> str:
        return "self_healing"

    @property
    def role(self) -> str:
        return "Automatically detects and fixes system issues"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return SelfHealingAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return SelfHealingAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def default_tools(self) -> list[str]:
        return ['command_run', 'file_write', 'git_commit', 'analyze_metrics']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            issue = (input_data.get("issue_detected") or "").strip()
            system = (input_data.get("affected_system") or "").strip()
            severity = input_data.get("severity", "medium")
            details = input_data.get("details", {}) if isinstance(input_data.get("details"), dict) else {}

            self.logger.info(f"Self-healing analysis: {severity} issue in {system or '(unspecified)'}")

            # Actual healing is always blocked here: it needs the monitoring
            # subsystem + the approved command/deploy pipeline.
            limitations: List[str] = [
                "Actual healing is BLOCKED: restarting services, applying fixes, "
                "or deploying changes requires the monitoring subsystem plus the "
                "approved command/deploy pipeline, which are NOT wired into "
                "standalone agent execution. No live system was modified.",
            ]

            # ---- Real local analysis of any provided files ------------------
            candidate_paths: List[str] = []
            for key in ("files", "target_files", "paths"):
                v = details.get(key) if details else None
                if isinstance(v, list):
                    candidate_paths.extend(str(x) for x in v if x)
            existing, missing = helpers.resolve_files(candidate_paths, context)
            for m in missing:
                limitations.append(f"Provided file not found, skipped: {m}")

            files_analyzed: List[str] = []
            findings: List[Dict[str, str]] = []
            for path in existing:
                text = helpers.read_file_safe(path)
                if text is None:
                    limitations.append(f"File could not be read: {path}")
                    continue
                files_analyzed.append(path)
                for d in helpers.scan_dangerous(text):
                    findings.append({"file": path, **d})
            if existing:
                limitations.append(
                    "Static scan is a non-exhaustive signal only; absence of "
                    "findings does not guarantee the file is safe."
                )

            # ---- Remediation plan (model-backed when configured) ------------
            remediation_plan: List[str] = []
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            if helpers.provider_configured() and (issue or findings):
                find_text = "; ".join(
                    f"{f.get('file')}:{f.get('pattern')}" for f in findings
                ) or "(no static findings)"
                prompt = (
                    f"Incident on system '{system or 'unknown'}' "
                    f"(severity={severity}): {issue or '(no description)'}.\n"
                    f"Static analysis findings: {find_text}.\n\n"
                    "Propose a safe remediation PLAN. You cannot execute "
                    "anything; this is advisory. Respond as one step per line, "
                    "each prefixed with '- '."
                )
                llm = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system="You draft incident remediation plans. You have no "
                           "ability to fix live systems and must never claim you "
                           "did. Suggest only safe, reversible, approved steps.",
                    temperature=self.config.temperature,
                    max_tokens=800,
                )
                if llm is not None:
                    provider_used = llm["provider_used"]
                    tokens = llm["tokens"]
                    for line in llm["text"].splitlines():
                        s = line.strip().lstrip("-*0123456789. ").strip()
                        if s:
                            remediation_plan.append(s)
                    limitations.append(
                        "Remediation plan is model-generated and unverified; "
                        "route each step through the approved pipeline."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the plan call failed; "
                        "returned analysis only."
                    )
            elif not helpers.provider_configured():
                limitations.append(helpers.no_provider_limitation())

            if not remediation_plan:
                remediation_plan = [
                    "Triage the incident via the monitoring subsystem to confirm "
                    "scope and root cause.",
                    "Route any corrective command or deploy through the approved "
                    "command/deploy pipeline with the required authority/approval.",
                ]

            output_text = (
                f"Self-healing[{severity}] on '{system or 'unknown'}': "
                f"actual healing BLOCKED; analyzed {len(files_analyzed)} file(s), "
                f"{len(findings)} static finding(s); "
                f"{len(remediation_plan)} plan step(s); provider="
                f"{provider_used or 'none'}."
            )

            # Producing a truthful analysis + plan (and an honest blocked status
            # for live healing) is a successful run.
            return self.create_result(
                success=True,
                result_data={
                    "affected_system": system,
                    "severity": severity,
                    "blocked": True,
                    "files_analyzed": files_analyzed,
                    "findings": findings,
                    "remediation_plan": remediation_plan,
                    "provider_used": provider_used,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(
                    (["static_scan"] if files_analyzed else [])
                    + (["model_router"] if provider_used else [])
                ),
                tokens_used=tokens or {},
                requires_approval=True,
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"self_healing task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
