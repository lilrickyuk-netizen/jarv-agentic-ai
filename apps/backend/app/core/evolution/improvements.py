"""
JARV Backend - Improvement Proposals

Proposes improvements to rules, runbooks, agents, tools, swarms, and operating plans.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ImprovementType(str, Enum):
    """Type of improvement"""
    RULE = "rule"
    RUNBOOK = "runbook"
    AGENT_INSTRUCTION = "agent_instruction"
    TOOL_SELECTION = "tool_selection"
    SWARM_STRATEGY = "swarm_strategy"
    OPERATING_PLAN = "operating_plan"


class RiskLevel(str, Enum):
    """Risk level of improvement"""
    SAFE = "safe"  # Auto-apply
    LOW = "low"  # Needs verification
    MEDIUM = "medium"  # Needs approval
    HIGH = "high"  # Needs manual review
    CRITICAL = "critical"  # Blocked


class ImprovementStatus(str, Enum):
    """Status of improvement proposal"""
    PROPOSED = "proposed"
    VERIFYING = "verifying"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


class ImprovementCreate(BaseModel):
    """Schema for creating improvement proposal"""
    workspace_id: UUID
    improvement_type: ImprovementType
    title: str
    description: str
    current_state: str
    proposed_state: str
    rationale: str
    expected_benefits: List[str] = Field(default_factory=list)
    potential_risks: List[str] = Field(default_factory=list)
    affected_components: List[str] = Field(default_factory=list)
    source_experience_ids: List[UUID] = Field(default_factory=list)
    source_lesson: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ImprovementResult(BaseModel):
    """Improvement proposal result"""
    id: UUID
    workspace_id: UUID
    improvement_type: ImprovementType
    title: str
    description: str
    current_state: str
    proposed_state: str
    rationale: str
    expected_benefits: List[str]
    potential_risks: List[str]
    affected_components: List[str]
    source_experience_ids: List[UUID]
    source_lesson: Optional[str]
    risk_level: RiskLevel
    status: ImprovementStatus
    verification_results: Dict[str, Any]
    approval_user_id: Optional[UUID]
    approval_timestamp: Optional[datetime]
    applied_at: Optional[datetime]
    rolled_back_at: Optional[datetime]
    version_id: Optional[UUID]
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ImprovementManager:
    """
    Manages improvement proposals.

    Proposes and tracks improvements to various system components.
    """

    def __init__(self):
        """Initialize improvement manager"""
        self.logger = logging.getLogger("evolution.improvements")

    async def propose_improvement(
        self,
        improvement: ImprovementCreate,
    ) -> UUID:
        """
        Propose an improvement.

        In production: Insert into ImprovementProposal table.

        Args:
            improvement: Improvement data

        Returns:
            Improvement ID
        """
        try:
            # Classify risk level
            risk_level = await self._classify_risk(improvement)

            # In production: Insert into database
            # from app.models.evolution import ImprovementProposal as DBImprovement
            # from app.core.database import get_db
            # async with get_db() as db:
            #     db_improvement = DBImprovement(
            #         workspace_id=improvement.workspace_id,
            #         improvement_type=improvement.improvement_type,
            #         title=improvement.title,
            #         description=improvement.description,
            #         current_state=improvement.current_state,
            #         proposed_state=improvement.proposed_state,
            #         rationale=improvement.rationale,
            #         expected_benefits=improvement.expected_benefits,
            #         potential_risks=improvement.potential_risks,
            #         affected_components=improvement.affected_components,
            #         source_experience_ids=[str(id) for id in improvement.source_experience_ids],
            #         source_lesson=improvement.source_lesson,
            #         risk_level=risk_level,
            #         status=ImprovementStatus.PROPOSED,
            #         metadata=improvement.metadata,
            #     )
            #     db.add(db_improvement)
            #     await db.commit()
            #     improvement_id = db_improvement.id

            improvement_id = uuid4()

            self.logger.info(
                f"Proposed {improvement.improvement_type} improvement: {improvement.title}",
                extra={
                    "improvement_id": str(improvement_id),
                    "workspace_id": str(improvement.workspace_id),
                    "risk_level": risk_level.value,
                }
            )

            return improvement_id

        except Exception as e:
            self.logger.error(
                f"Failed to propose improvement: {e}",
                extra={"title": improvement.title},
                exc_info=True
            )
            raise

    async def _classify_risk(
        self,
        improvement: ImprovementCreate,
    ) -> RiskLevel:
        """
        Classify risk level of improvement.

        In production: Use LLM to analyze risks.

        Args:
            improvement: Improvement data

        Returns:
            Risk level
        """
        try:
            # In production:
            # 1. Analyze potential risks list
            # 2. Check affected components criticality
            # 3. Use LLM to classify risk
            # 4. Apply safety rules
            # 5. Return risk level

            # Simple heuristic for now
            if len(improvement.potential_risks) == 0:
                return RiskLevel.SAFE
            elif len(improvement.potential_risks) == 1:
                return RiskLevel.LOW
            elif len(improvement.potential_risks) == 2:
                return RiskLevel.MEDIUM
            elif len(improvement.potential_risks) == 3:
                return RiskLevel.HIGH
            else:
                return RiskLevel.CRITICAL

        except Exception as e:
            self.logger.error(f"Failed to classify risk: {e}", exc_info=True)
            # Default to high risk on error
            return RiskLevel.HIGH

    async def propose_rule_improvement(
        self,
        workspace_id: UUID,
        rule_name: str,
        current_rule: str,
        proposed_rule: str,
        rationale: str,
        **kwargs
    ) -> UUID:
        """Propose workspace rule improvement"""
        improvement = ImprovementCreate(
            workspace_id=workspace_id,
            improvement_type=ImprovementType.RULE,
            title=f"Improve rule: {rule_name}",
            description=f"Update workspace rule based on experience",
            current_state=current_rule,
            proposed_state=proposed_rule,
            rationale=rationale,
            affected_components=[f"workspace_rule_{rule_name}"],
            **kwargs
        )
        return await self.propose_improvement(improvement)

    async def propose_runbook_improvement(
        self,
        workspace_id: UUID,
        runbook_name: str,
        current_runbook: str,
        proposed_runbook: str,
        rationale: str,
        **kwargs
    ) -> UUID:
        """Propose runbook improvement"""
        improvement = ImprovementCreate(
            workspace_id=workspace_id,
            improvement_type=ImprovementType.RUNBOOK,
            title=f"Improve runbook: {runbook_name}",
            description=f"Update runbook based on experience",
            current_state=current_runbook,
            proposed_state=proposed_runbook,
            rationale=rationale,
            affected_components=[f"runbook_{runbook_name}"],
            **kwargs
        )
        return await self.propose_improvement(improvement)

    async def propose_agent_improvement(
        self,
        workspace_id: UUID,
        agent_name: str,
        instruction_area: str,
        current_instruction: str,
        proposed_instruction: str,
        rationale: str,
        **kwargs
    ) -> UUID:
        """Propose agent instruction improvement"""
        improvement = ImprovementCreate(
            workspace_id=workspace_id,
            improvement_type=ImprovementType.AGENT_INSTRUCTION,
            title=f"Improve {agent_name} {instruction_area}",
            description=f"Update agent instructions based on experience",
            current_state=current_instruction,
            proposed_state=proposed_instruction,
            rationale=rationale,
            affected_components=[f"agent_{agent_name}"],
            **kwargs
        )
        return await self.propose_improvement(improvement)

    async def propose_tool_selection_improvement(
        self,
        workspace_id: UUID,
        scenario: str,
        current_tools: List[str],
        proposed_tools: List[str],
        rationale: str,
        **kwargs
    ) -> UUID:
        """Propose tool selection improvement"""
        improvement = ImprovementCreate(
            workspace_id=workspace_id,
            improvement_type=ImprovementType.TOOL_SELECTION,
            title=f"Improve tool selection for: {scenario}",
            description=f"Update tool selection strategy based on experience",
            current_state=f"Tools: {', '.join(current_tools)}",
            proposed_state=f"Tools: {', '.join(proposed_tools)}",
            rationale=rationale,
            affected_components=["tool_selection_strategy"],
            **kwargs
        )
        return await self.propose_improvement(improvement)

    async def propose_swarm_strategy_improvement(
        self,
        workspace_id: UUID,
        strategy_name: str,
        current_strategy: str,
        proposed_strategy: str,
        rationale: str,
        **kwargs
    ) -> UUID:
        """Propose swarm strategy improvement"""
        improvement = ImprovementCreate(
            workspace_id=workspace_id,
            improvement_type=ImprovementType.SWARM_STRATEGY,
            title=f"Improve swarm strategy: {strategy_name}",
            description=f"Update swarm management strategy based on experience",
            current_state=current_strategy,
            proposed_state=proposed_strategy,
            rationale=rationale,
            affected_components=[f"swarm_strategy_{strategy_name}"],
            **kwargs
        )
        return await self.propose_improvement(improvement)

    async def propose_operating_plan_improvement(
        self,
        workspace_id: UUID,
        plan_component: str,
        current_plan: str,
        proposed_plan: str,
        rationale: str,
        **kwargs
    ) -> UUID:
        """Propose operating plan improvement"""
        improvement = ImprovementCreate(
            workspace_id=workspace_id,
            improvement_type=ImprovementType.OPERATING_PLAN,
            title=f"Improve operating plan: {plan_component}",
            description=f"Update operating plan based on experience",
            current_state=current_plan,
            proposed_state=proposed_plan,
            rationale=rationale,
            affected_components=[f"operating_plan_{plan_component}"],
            **kwargs
        )
        return await self.propose_improvement(improvement)

    async def get_improvement(
        self,
        improvement_id: UUID,
    ) -> Optional[ImprovementResult]:
        """Get improvement by ID"""
        # In production: Query database
        return None

    async def list_improvements(
        self,
        workspace_id: Optional[UUID] = None,
        improvement_type: Optional[ImprovementType] = None,
        status: Optional[ImprovementStatus] = None,
        risk_level: Optional[RiskLevel] = None,
        limit: int = 100,
    ) -> List[ImprovementResult]:
        """List improvements with filters"""
        # In production: Query database with filters
        return []

    async def get_improvement_stats(
        self,
        workspace_id: UUID,
    ) -> Dict[str, Any]:
        """Get improvement statistics"""
        return {
            "total_proposed": 0,
            "by_type": {},
            "by_status": {},
            "by_risk_level": {},
            "approval_rate": 0.0,
            "application_rate": 0.0,
        }


# Global improvement manager
_improvement_manager = ImprovementManager()


async def propose_rule_improvement(workspace_id: UUID, **kwargs) -> UUID:
    """Global function to propose rule improvement"""
    return await _improvement_manager.propose_rule_improvement(workspace_id, **kwargs)


async def propose_runbook_improvement(workspace_id: UUID, **kwargs) -> UUID:
    """Global function to propose runbook improvement"""
    return await _improvement_manager.propose_runbook_improvement(workspace_id, **kwargs)


async def propose_agent_improvement(workspace_id: UUID, **kwargs) -> UUID:
    """Global function to propose agent improvement"""
    return await _improvement_manager.propose_agent_improvement(workspace_id, **kwargs)


async def propose_tool_improvement(workspace_id: UUID, **kwargs) -> UUID:
    """Global function to propose tool selection improvement"""
    return await _improvement_manager.propose_tool_selection_improvement(workspace_id, **kwargs)


async def propose_swarm_improvement(workspace_id: UUID, **kwargs) -> UUID:
    """Global function to propose swarm strategy improvement"""
    return await _improvement_manager.propose_swarm_strategy_improvement(workspace_id, **kwargs)


async def propose_plan_improvement(workspace_id: UUID, **kwargs) -> UUID:
    """Global function to propose operating plan improvement"""
    return await _improvement_manager.propose_operating_plan_improvement(workspace_id, **kwargs)
