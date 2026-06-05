"""
JARV Backend - SecurityAgent

Performs a REAL, honest static regex scan for secrets and dangerous code
patterns in the provided files and/or text.

This agent does NOT fabricate vulnerability counts. It runs the shared
`scan_secrets` and `scan_dangerous` regex scanners over the real content it can
read, and `vulnerabilities_found` is exactly the number of real matches. It
clearly states that this is a lightweight static regex scan, NOT a full SAST /
dependency CVE analysis.
"""
from typing import Dict, Any, List, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists._helpers import (
    resolve_files,
    read_file_safe,
    scan_secrets,
    scan_dangerous,
    task_text,
)

logger = logging.getLogger(__name__)


class SecurityAgentInput(BaseModel):
    """SecurityAgent input"""
    scan_type: str = Field(..., description="vulnerability, dependency, code, config")
    targets: list[str] = Field(default_factory=list)
    severity_threshold: str = Field(default="medium")


class SecurityAgentOutput(BaseModel):
    """SecurityAgent output (honest regex scan; every field has a default)."""
    scan_completed: bool = False
    scan_type: str = ""
    files_scanned: int = 0
    files_missing: int = 0
    vulnerabilities_found: int = 0
    findings: List[Dict[str, str]] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class SecurityAgent(AgentBase):
    """
    SecurityAgent - real static regex scan for secrets and dangerous patterns.

    `vulnerabilities_found` always equals the number of real regex matches. No
    counts are invented. This is not a substitute for full SAST.
    """

    @property
    def name(self) -> str:
        return "security"

    @property
    def role(self) -> str:
        return "Audits security, detects vulnerabilities, enforces policies"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return SecurityAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return SecurityAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def default_tools(self) -> list[str]:
        return ['analyze_security', 'file_read', 'analyze_code']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            scan_type = (input_data.get("scan_type") or "vulnerability").strip()
            targets = list(input_data.get("targets", []) or [])
            # The runner injects the task instruction into scan_type; treat any
            # non-path instruction text as scannable text too.
            inline_text = task_text(input_data, "scan_type")

            self.logger.info(f"Security scan: type={scan_type} targets={len(targets)}")

            tools_used: List[str] = []
            limitations: List[str] = [
                "This is a lightweight STATIC regex scan for secret-like strings "
                "and dangerous calls only; it is NOT a full SAST, dependency CVE, "
                "or configuration audit. Absence of findings does not prove the "
                "code is secure.",
            ]

            existing, missing = resolve_files(targets, context)
            findings: List[Dict[str, str]] = []

            for path in existing:
                content = read_file_safe(path)
                if content is None:
                    limitations.append(f"File unreadable, skipped: {path}")
                    continue
                tools_used.append("scan_secrets")
                tools_used.append("scan_dangerous")
                for f in scan_secrets(content):
                    findings.append({**f, "location": path})
                for f in scan_dangerous(content):
                    findings.append({**f, "location": path})

            # Scan inline instruction/text content if it was supplied (and isn't
            # just an empty/placeholder path).
            if inline_text and inline_text not in targets:
                tools_used.append("scan_secrets")
                tools_used.append("scan_dangerous")
                for f in scan_secrets(inline_text):
                    findings.append({**f, "location": "input_text"})
                for f in scan_dangerous(inline_text):
                    findings.append({**f, "location": "input_text"})

            # vulnerabilities_found MUST equal the real number of findings.
            vulnerabilities_found = len(findings)

            recommendations: List[str] = []
            if any(f.get("type") == "secret" for f in findings):
                recommendations.append(
                    "Remove hardcoded secrets and move them to environment "
                    "variables / a secrets manager; rotate any exposed credential."
                )
            if any(f.get("type") == "dangerous_call" for f in findings):
                recommendations.append(
                    "Review flagged dangerous calls (eval/exec/os.system/shell=True/"
                    "unsafe deserialization) and replace with safe alternatives."
                )
            recommendations.append(
                "Run a full SAST tool and dependency CVE scan for complete "
                "coverage; this static regex pass is not exhaustive."
            )

            if not existing and not inline_text:
                limitations.append(
                    "No readable targets or text supplied; nothing was scanned."
                )
            for m in missing:
                limitations.append(f"Target not found, not scanned: {m}")

            output_text = (
                f"Security[{scan_type}]: files_scanned={len(existing)} "
                f"findings={vulnerabilities_found} (static regex scan only)."
            )

            return self.create_result(
                success=True,
                result_data={
                    "scan_completed": True,
                    "scan_type": scan_type,
                    "files_scanned": len(existing),
                    "files_missing": len(missing),
                    "vulnerabilities_found": vulnerabilities_found,
                    "findings": findings,
                    "recommendations": recommendations,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=sorted(set(tools_used)),
            )

        except Exception as e:
            self.logger.error(f"security task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
