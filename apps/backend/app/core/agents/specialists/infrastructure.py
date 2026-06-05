"""
JARV Backend - InfrastructureAgent

Performs a REAL LOCAL infrastructure-file scan and reports honestly.

This agent does NOT provision, scale, migrate, or touch live cloud resources in
standalone execution, and it never fabricates cost, capacity, performance, or
downtime numbers. It inspects the local workspace for infrastructure files that
genuinely exist (Dockerfile, docker-compose, .env.example, nginx configs) and
reports exactly what it found. Inspecting live servers, cost, SSL, and DNS
requires real cloud/integration access that is not wired here.
"""
from typing import Dict, Any, List, Type
import os
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists._helpers import resolve_files

logger = logging.getLogger(__name__)


class InfrastructureAgentInput(BaseModel):
    """InfrastructureAgent input"""
    operation: str = Field(..., description="provision, scale, optimize, migrate")
    resources: list[str] = Field(default_factory=list)
    target_capacity: Dict[str, int] = Field(default_factory=dict)


class InfrastructureAgentOutput(BaseModel):
    """InfrastructureAgent output (honest; real local scan, no fabricated numbers)."""
    operation_completed: bool = False
    operation: str = ""
    scanned_path: str = ""
    infra_files_found: List[Dict[str, str]] = Field(default_factory=list)
    infra_files_missing: List[str] = Field(default_factory=list)
    resources_requested: List[str] = Field(default_factory=list)
    live_integration_connected: bool = False
    limitations: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class InfrastructureAgent(AgentBase):
    """
    InfrastructureAgent - Manages cloud infrastructure, scaling, and optimization
    """

    @property
    def name(self) -> str:
        return "infrastructure"

    @property
    def role(self) -> str:
        return "Manages cloud infrastructure, scaling, and optimization"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return InfrastructureAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return InfrastructureAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def default_tools(self) -> list[str]:
        return ['command_run', 'http_post', 'analyze_metrics']

    # Candidate infra files (relative); nginx configs handled separately.
    _INFRA_CANDIDATES = [
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".env.example",
        "infra/nginx.conf",
        "infra/nginx/nginx.conf",
        "nginx.conf",
        "nginx/nginx.conf",
    ]

    def _scan_base(self, context: AgentContext) -> str:
        """Pick a real base directory to scan (workspace metadata, else cwd)."""
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
        """Real local infra-file scan; honest limitation for live operations."""
        try:
            operation = input_data.get("operation", "scale")
            resources = [str(r).strip() for r in (input_data.get("resources") or []) if str(r).strip()]

            base = self._scan_base(context)
            self.logger.info(f"Infrastructure local scan ({operation}) under {base}")

            # REAL existence check using the helper resolver + os.path.
            existing, missing = resolve_files(self._INFRA_CANDIDATES, context)

            found: List[Dict[str, str]] = []
            seen = set()
            for p in existing:
                ap = os.path.abspath(p)
                if ap in seen:
                    continue
                seen.add(ap)
                found.append({
                    "name": os.path.basename(ap),
                    "path": ap,
                    "kind": "nginx_config" if "nginx" in ap.lower()
                            else ("env_example" if ap.lower().endswith(".env.example")
                                  else "docker"),
                })

            limitations: List[str] = [
                "This is a LOCAL file scan only: it reports which infrastructure "
                "files exist on disk. No provisioning, scaling, migration, or "
                "optimization was performed.",
                "Inspecting live servers, real cost/resource usage, SSL "
                "certificates, and DNS requires cloud/provider integrations that "
                "are not wired into this standalone agent.",
            ]
            if resources:
                limitations.append(
                    f"{len(resources)} resource name(s) were supplied but no live "
                    "resource was touched (no integration connected)."
                )

            recommendations = [
                "Connect cloud/provider integrations to perform real "
                f"'{operation}' operations and to read live cost/SSL/DNS state.",
            ]
            if not found:
                recommendations.append(
                    f"No infrastructure files detected under {base}; add a "
                    "Dockerfile/compose/nginx config or scan the correct path."
                )

            result_data = {
                "operation_completed": False,
                "operation": operation,
                "scanned_path": base,
                "infra_files_found": found,
                "infra_files_missing": missing,
                "resources_requested": resources,
                "live_integration_connected": False,
                "limitations": limitations,
                "recommendations": recommendations,
            }

            output_text = (
                f"Infrastructure scan ({operation}): {len(found)} infra file(s) "
                f"found under {base}, {len(missing)} candidate(s) absent. "
                "No live infrastructure operation was performed."
            )

            # Producing a truthful local scan + limitation is a successful run.
            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=output_text,
                tools_used=(["file_read"] if found else []),
            )

        except Exception as e:
            self.logger.error(f"infrastructure task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
