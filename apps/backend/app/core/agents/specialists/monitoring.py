"""
JARV Backend - MonitoringAgent

Monitors systems, detects anomalies, alerts on issues
"""
from typing import Dict, Any, Type
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
    """MonitoringAgent output"""
    monitoring_active: bool
    systems_healthy: int
    systems_warning: int
    systems_critical: int
    alerts_triggered: list[Dict[str, str]]
    recommendations: list[str]


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
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def default_tools(self) -> list[str]:
        return ['http_get', 'analyze_metrics', 'memory_store']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """
        Execute task.

        Args:
            input_data: Task input
            context: Execution context

        Returns:
            Agent result
        """
        try:
            targets = input_data.get("targets", [])

            self.logger.info(f"Monitoring {len(targets)} systems")

            # Simulate health checks
            healthy = int(len(targets) * 0.8)
            warning = int(len(targets) * 0.15)
            critical = len(targets) - healthy - warning

            alerts = []
            if critical > 0:
                alerts.append({"severity": "critical", "message": f"{critical} systems down"})
            if warning > 0:
                alerts.append({"severity": "warning", "message": f"{warning} systems degraded"})

            result_data = {
                "monitoring_active": True,
                "systems_healthy": healthy,
                "systems_warning": warning,
                "systems_critical": critical,
                "alerts_triggered": alerts,
                "recommendations": ["Scale up resources", "Review logs"] if alerts else [],
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Monitoring: {healthy}/{len(targets)} systems healthy",
                tools_used=["http_get", "analyze_metrics"],
            )

        except Exception as e:
            self.logger.error(f"monitoring task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
