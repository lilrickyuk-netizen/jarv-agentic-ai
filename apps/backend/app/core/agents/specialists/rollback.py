"""
JARV Backend - RollbackAgent

Prepares rollbacks from real state (Repair 12d): service status, workspace
history, and the verified database backups that can be restored, through an
approval-gated restore into a new database. It never reports a rollback that
did not happen. See ``ops_mode``; the fallback below is used without a
database session or workspace.
"""
from typing import Dict, Any, List, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class RollbackAgentInput(BaseModel):
    """RollbackAgent input"""
    deployment_id: str = Field(..., description="Deployment to rollback")
    reason: str = Field(...)
    target_version: str = Field(default="previous")


class RollbackAgentOutput(BaseModel):
    """RollbackAgent output (honest; always blocked in standalone execution)."""
    deployment_id: str = ""
    reason: str = ""
    target_version: str = ""
    blocked: bool = True
    rollback_performed: bool = False
    requirements: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class RollbackAgent(AgentBase):
    """
    RollbackAgent - Safely rolls back deployments and changes
    """

    @property
    def name(self) -> str:
        return "rollback"

    @property
    def role(self) -> str:
        return "Safely rolls back deployments and changes"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return RollbackAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return RollbackAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def default_tools(self) -> list[str]:
        from app.core.agents.specialists.ops_mode import tools_for

        return tools_for("rollback")

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        from app.core.agents.specialists import ops_mode

        live = await ops_mode.run(self, input_data, context)
        if live is not None:
            return live
        try:
            deployment_id = (input_data.get("deployment_id") or "").strip()
            reason = (input_data.get("reason") or "").strip()
            target_version = (input_data.get("target_version") or "previous").strip()

            self.logger.info(
                f"Rollback requested for deployment '{deployment_id}' "
                f"(reason: {reason or 'none'}) - BLOCKED in standalone execution"
            )

            requirements: List[str] = [
                "A live deployment subsystem that knows the current deployed "
                "version and can promote/restore releases.",
                "A release/version history so the rollback target "
                f"('{target_version}') can be resolved to a real artifact.",
                "Explicit Level 7 deployment authority and (per hard-boundary "
                "rules) human approval before any production rollback.",
                "Verification of system health after restore, via the monitoring "
                "subsystem.",
            ]

            limitations: List[str] = [
                "BLOCKED: no real deployment, version, or release state is "
                "available to a standalone agent. No rollback was performed and "
                "no version was restored.",
                "This agent cannot resolve, restore, or verify any version on its "
                "own; the request must be routed to the deployment subsystem.",
            ]

            output_text = (
                f"Rollback BLOCKED for deployment '{deployment_id or '(none)'}' "
                f"(target='{target_version}'): no deployment/release state "
                f"available; no rollback performed. "
                f"{len(requirements)} requirement(s) listed."
            )

            # success=True reflects that the agent produced a truthful,
            # structured limitation - not that any rollback happened.
            return self.create_result(
                success=True,
                result_data={
                    "deployment_id": deployment_id,
                    "reason": reason,
                    "target_version": target_version,
                    "blocked": True,
                    "rollback_performed": False,
                    "requirements": requirements,
                    "limitations": limitations,
                },
                output_text=output_text,
                requires_approval=True,
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"rollback task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
