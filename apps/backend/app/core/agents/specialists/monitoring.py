"""
JARV Backend - MonitoringAgent

Measures JARV and the targets it is given with the operations tools
(Repair 12d): service and dependency health, containers, crashes, recent
errors, server resources, Prometheus metrics, and uptime of public URLs.
See ``ops_mode``. When no database session or workspace is available, the
fallback below reports targets as "unknown" and never invents health numbers.
"""
from typing import Dict, Any, List, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class MonitoringAgentInput(BaseModel):
    """MonitoringAgent input"""
    targets: list[str] = Field(..., description="Systems to monitor")
    metrics: list[str] = Field(default_factory=list)
    alert_threshold: Dict[str, float] = Field(default_factory=dict)


class MonitoringAgentOutput(BaseModel):
    """MonitoringAgent output (honest; no fabricated health/uptime numbers)."""
    monitoring_active: bool = False
    live_integration_connected: bool = False
    targets_provided: int = 0
    target_statuses: List[Dict[str, str]] = Field(default_factory=list)
    systems_healthy: int = 0
    systems_warning: int = 0
    systems_critical: int = 0
    systems_unknown: int = 0
    alerts_triggered: List[Dict[str, str]] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class MonitoringAgent(AgentBase):
    """
    MonitoringAgent - Monitors systems, detects anomalies, alerts on issues
    """

    @property
    def name(self) -> str:
        return "monitoring"

    @property
    def role(self) -> str:
        return "Monitors systems, detects anomalies, alerts on issues"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MonitoringAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MonitoringAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def default_tools(self) -> list[str]:
        from app.core.agents.specialists.ops_mode import tools_for

        return tools_for("monitoring")

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """Return an honest LIMITED monitoring assessment (no live integration)."""
        from app.core.agents.specialists import ops_mode

        live = await ops_mode.run(self, input_data, context)
        if live is not None:
            return live
        try:
            targets = [str(t).strip() for t in (input_data.get("targets") or []) if str(t).strip()]

            self.logger.info(f"Monitoring requested for {len(targets)} target(s)")

            # No live monitoring integration is wired into standalone agent
            # execution. Echo provided targets with status "unknown" — never
            # claim any are healthy/degraded/down, since nothing was probed.
            target_statuses: List[Dict[str, str]] = [
                {"target": t, "status": "unknown"} for t in targets
            ]

            limitations: List[str] = [
                "No live monitoring integration or probe targets are connected to "
                "this standalone agent; no health check, metric query, or uptime "
                "measurement was performed.",
                "Live monitoring requires the monitoring subsystem and its "
                "integrations (metrics/log backends, HTTP probes, alerting). "
                "Until those are wired, target status is reported as 'unknown'.",
            ]
            if not targets:
                limitations.append("No targets were provided; nothing to assess.")

            recommendations = [
                "Wire the monitoring subsystem and integrations to obtain real "
                "health, metric, and uptime data before relying on this agent.",
            ]
            if targets:
                recommendations.append(
                    f"Re-run via the monitoring subsystem to actually probe the "
                    f"{len(targets)} listed target(s)."
                )

            result_data = {
                "monitoring_active": False,
                "live_integration_connected": False,
                "targets_provided": len(targets),
                "target_statuses": target_statuses,
                "systems_healthy": 0,
                "systems_warning": 0,
                "systems_critical": 0,
                "systems_unknown": len(targets),
                "alerts_triggered": [],
                "recommendations": recommendations,
                "limitations": limitations,
            }

            output_text = (
                f"Monitoring (LIMITED): no live integration connected; "
                f"{len(targets)} target(s) reported with status 'unknown'. "
                "Real monitoring requires the monitoring subsystem."
            )

            # Producing a truthful limited assessment is a successful agent run.
            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=output_text,
                tools_used=[],
            )

        except Exception as e:
            self.logger.error(f"monitoring task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
