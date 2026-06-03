"""
JARV Backend - Richard Guidance

Provides proactive boundary guidance from Richard operator.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID
import logging

from app.core.richard.operator import RichardOperator, RichardInput, RichardDecision, DecisionType

logger = logging.getLogger(__name__)


class RichardGuidance:
    """
    Provides proactive Richard guidance for boundary decisions.

    Offers guidance and recommendations based on Richard's principles
    and past decisions.
    """

    def __init__(self):
        """Initialize Richard guidance"""
        self.logger = logging.getLogger("richard.guidance")
        self.operator = RichardOperator()

    async def request_guidance(
        self,
        user_id: UUID,
        situation: str,
        proposed_action: str,
        workspace_id: Optional[UUID] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> RichardInput:
        """
        Request guidance from Richard on a situation.

        Args:
            user_id: User requesting guidance
            situation: Situation description
            proposed_action: Proposed action
            workspace_id: Optional workspace
            context: Additional context

        Returns:
            RichardInput record
        """
        return await self.operator.submit_input(
            user_id=user_id,
            input_type="guidance",
            situation_description=situation,
            requested_action=proposed_action,
            workspace_id=workspace_id,
            context=context or {},
            urgency="normal",
            submitted_by="guidance_system",
        )

    async def get_similar_decisions(
        self,
        situation: str,
        limit: int = 10,
    ) -> List[tuple[RichardInput, RichardDecision]]:
        """
        Find similar past Richard decisions for guidance.

        In production: Use semantic search on RichardBoundaryInput table.

        Args:
            situation: Current situation description
            limit: Maximum results

        Returns:
            List of similar (input, decision) pairs
        """
        try:
            # In production: Semantic search on past decisions
            # from app.models.boundary import RichardBoundaryInput as DBInput
            # from app.core.database import get_db
            # async with get_db() as db:
            #     # Use pgvector similarity search
            #     situation_embedding = await get_embedding(situation)
            #     results = await db.execute(
            #         select(DBInput)
            #         .where(DBInput.decided_at != None)
            #         .order_by(
            #             DBInput.situation_embedding.cosine_distance(situation_embedding)
            #         )
            #         .limit(limit)
            #     )
            #
            #     similar = []
            #     for row in results:
            #         richard_input = RichardInput.from_orm(row)
            #         decision = RichardDecision(**row.decision)
            #         similar.append((richard_input, decision))
            #
            #     return similar

            self.logger.debug(
                f"Retrieved similar Richard decisions for situation",
                extra={"situation_length": len(situation), "limit": limit}
            )

            return []

        except Exception as e:
            self.logger.error(
                f"Failed to get similar decisions: {e}",
                exc_info=True
            )
            return []

    async def get_guidance_summary(
        self,
        situation: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Get guidance summary based on similar past decisions.

        Args:
            situation: Current situation
            context: Optional context

        Returns:
            Guidance summary dictionary
        """
        similar_decisions = await self.get_similar_decisions(situation, limit=5)

        if not similar_decisions:
            return {
                "has_guidance": False,
                "message": "No similar past decisions found. Consider submitting for Richard review.",
            }

        # Analyze patterns in similar decisions
        approve_count = sum(1 for _, d in similar_decisions if d.decision_type == DecisionType.APPROVE)
        deny_count = sum(1 for _, d in similar_decisions if d.decision_type == DecisionType.DENY)
        modify_count = sum(1 for _, d in similar_decisions if d.decision_type == DecisionType.MODIFY)

        total = len(similar_decisions)

        # Extract common conditions and modifications
        all_conditions = []
        all_modifications = {}
        for _, decision in similar_decisions:
            all_conditions.extend(decision.conditions)
            all_modifications.update(decision.modifications)

        guidance = {
            "has_guidance": True,
            "similar_cases": total,
            "approval_rate": approve_count / total if total > 0 else 0,
            "denial_rate": deny_count / total if total > 0 else 0,
            "modification_rate": modify_count / total if total > 0 else 0,
            "common_conditions": list(set(all_conditions))[:10],  # Top 10 unique conditions
            "common_modifications": all_modifications,
            "recommendation": self._generate_recommendation(
                approve_count, deny_count, modify_count, total
            ),
        }

        return guidance

    def _generate_recommendation(
        self,
        approve_count: int,
        deny_count: int,
        modify_count: int,
        total: int,
    ) -> str:
        """Generate recommendation based on past decisions"""
        if total == 0:
            return "No historical guidance available."

        approve_rate = approve_count / total
        deny_rate = deny_count / total

        if approve_rate >= 0.8:
            return "Similar situations have been frequently approved. Proceed with standard safeguards."
        elif deny_rate >= 0.8:
            return "Similar situations have been frequently denied. Consider alternative approaches."
        elif modify_count >= total / 2:
            return "Similar situations typically require modifications. Review common conditions carefully."
        else:
            return "Mixed outcomes in similar situations. Recommend submitting for Richard review."


# Global guidance instance
_guidance = RichardGuidance()


async def request_richard_guidance(
    user_id: UUID,
    situation: str,
    proposed_action: str,
    **kwargs
) -> RichardInput:
    """
    Global function to request Richard guidance.

    Args:
        user_id: User ID
        situation: Situation description
        proposed_action: Proposed action
        **kwargs: Additional parameters

    Returns:
        RichardInput
    """
    return await _guidance.request_guidance(
        user_id=user_id,
        situation=situation,
        proposed_action=proposed_action,
        **kwargs
    )
