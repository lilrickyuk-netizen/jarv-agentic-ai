"""
JARV Backend - DevOpsAgent

Detects CI/CD and deployment configuration LOCALLY and reports honestly.

This agent CANNOT build, deploy, roll back, or release in standalone execution:
real deployment requires the deployment subsystem and approval pipeline, which
are not wired into an isolated agent run. It therefore never claims a deploy or
build happened and never invents a deployment URL or health-check pass. It
inspects the local repo for CI/deploy files that genuinely exist (GitHub
Actions workflows, Dockerfile, docker-compose) and reports exactly what it
found, while marking any actual deploy/staging/release action as BLOCKED.
"""
from typing import Dict, Any, List, Type
import os
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists._helpers import resolve_files

logger = logging.getLogger(__name__)


class DevOpsAgentInput(BaseModel):
    """DevOpsAgent input"""
    operation: str = Field(..., description="Operation: deploy, rollback, scale, monitor")
    environment: str = Field(..., description="Target environment")
    config: Dict[str, Any] = Field(default_factory=dict)


class DevOpsAgentOutput(BaseModel):
    """DevOpsAgent output (honest; real local detection, no fabricated deploy)."""
    operation_completed: bool = False
    operation: str = ""
    environment: str = ""
    deploy_blocked: bool = False
    scanned_path: str = ""
    ci_files_found: List[Dict[str, str]] = Field(default_factory=list)
    ci_files_missing: List[str] = Field(default_factory=list)
    deployment_subsystem_connected: bool = False
    limitations: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class DevOpsAgent(AgentBase):
    """
    DevOpsAgent - Manages deployments, CI/CD, and infrastructure operations
    """

    @property
    def name(self) -> str:
        return "devops"

    @property
    def role(self) -> str:
        return "Manages deployments, CI/CD, and infrastructure operations"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return DevOpsAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return DevOpsAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def default_tools(self) -> list[str]:
        return ['command_run', 'file_read', 'file_write', 'git_push']

    # Static CI/deploy file candidates (workflows enumerated separately).
    _CI_CANDIDATES = [
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".github/workflows",
    ]
    # Operations that mutate real environments (must be blocked here).
    _DEPLOY_OPS = {"deploy", "rollback", "scale", "release", "provision", "migrate"}

    def _scan_base(self, context: AgentContext) -> str:
        meta = getattr(context, "metadata", None) or {}
        base = meta.get("workspace_path") or meta.get("folder_path")
        if base and os.path.isdir(base):
            return os.path.abspath(base)
        return os.path.abspath(os.getcwd())

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """Real local CI/deploy file detection; honest BLOCKED for real deploys."""
        try:
            operation = input_data.get("operation", "deploy")
            environment = input_data.get("environment", "staging")
            base = self._scan_base(context)

            self.logger.info(
                f"DevOps local detection for '{operation}' -> {environment} under {base}"
            )

            # REAL existence check for CI/deploy config.
            existing, missing = resolve_files(self._CI_CANDIDATES, context)
            found: List[Dict[str, str]] = []
            seen = set()
            for p in existing:
                ap = os.path.abspath(p)
                if ap in seen:
                    continue
                seen.add(ap)
                if os.path.isdir(ap):
                    # Enumerate real workflow files inside .github/workflows.
                    try:
                        for fn in sorted(os.listdir(ap)):
                            if fn.lower().endswith((".yml", ".yaml")):
                                found.append({
                                    "name": fn,
                                    "path": os.path.join(ap, fn),
                                    "kind": "github_workflow",
                                })
                    except OSError:
                        pass
                else:
                    found.append({
                        "name": os.path.basename(ap),
                        "path": ap,
                        "kind": "docker",
                    })

            deploy_blocked = operation in self._DEPLOY_OPS

            limitations: List[str] = [
                "This is LOCAL detection only: it reports which CI/CD and "
                "deployment files exist on disk. No build, deploy, rollback, or "
                "release was performed.",
            ]
            if deploy_blocked:
                limitations.append(
                    f"Operation '{operation}' is BLOCKED in standalone execution: "
                    "real deployment requires the deployment subsystem and the "
                    "authority/approval pipeline. Nothing was deployed or changed."
                )
            else:
                limitations.append(
                    f"Operation '{operation}' performed no live action; the "
                    "deployment subsystem is not connected to this agent."
                )

            recommendations = [
                "Route deploy/rollback/release through the deployment subsystem "
                "and approval pipeline to perform real, audited operations.",
            ]
            if not found:
                recommendations.append(
                    f"No CI/deploy files detected under {base}; add GitHub "
                    "workflows or a Dockerfile/compose file, or scan the correct path."
                )

            result_data = {
                "operation_completed": False,
                "operation": operation,
                "environment": environment,
                "deploy_blocked": deploy_blocked,
                "scanned_path": base,
                "ci_files_found": found,
                "ci_files_missing": missing,
                "deployment_subsystem_connected": False,
                "limitations": limitations,
                "recommendations": recommendations,
            }

            output_text = (
                f"DevOps detection ({operation} -> {environment}): {len(found)} "
                f"CI/deploy file(s) found under {base}. "
                + ("Real deploy BLOCKED (needs deployment subsystem + approval)."
                   if deploy_blocked else "No live action taken.")
            )

            # A truthful detection + blocked report is a successful agent run.
            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=output_text,
                tools_used=(["file_read"] if found else []),
                requires_approval=deploy_blocked,
            )

        except Exception as e:
            self.logger.error(f"devops task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
