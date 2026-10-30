"""
JARV Backend - Experience Query Tools

Tools for querying learned patterns and getting suggestions from experience.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
import logging
from uuid import UUID
from sqlalchemy import String, cast, or_, select
from app.tools.memory.storage import _memory_scope
from app.models.self_evolution import ExperienceRecord

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


# ===== EXPERIENCE QUERY PATTERN TOOL =====

class ExperienceQueryPatternInput(BaseModel):
    """Input schema for querying patterns"""
    context: str = Field(..., min_length=1, description="Current situation/context to find patterns for")
    experience_type: Optional[str] = Field(None, description="Filter by experience type")
    outcome: Optional[str] = Field(None, description="Filter by outcome: success, failure, mixed")
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Minimum confidence score")
    min_success_rate: Optional[float] = Field(None, ge=0.0, le=1.0, description="Minimum success rate")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum results")


class PatternResult(BaseModel):
    """Pattern query result"""
    experience_id: str
    title: str
    experience_type: str
    situation: str
    action_taken: str
    result: str
    outcome: str
    lesson_learned: str
    confidence_score: float
    times_applied: int
    success_rate: Optional[float]
    applicable_contexts: List[str]


class ExperienceQueryPatternOutput(BaseModel):
    """Output schema for querying patterns"""
    patterns: List[PatternResult]
    count: int


class ExperienceQueryPatternTool(ToolBase):
    """Tool for querying learned patterns"""

    @property
    def name(self) -> str:
        return "experience_query_pattern"

    @property
    def description(self) -> str:
        return "Query learned patterns relevant to current context."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExperienceQueryPatternInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperienceQueryPatternOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "experience"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Query experience patterns from database"""
        query_context = input_data["context"]
        experience_type = input_data.get("experience_type")
        outcome = input_data.get("outcome")
        min_confidence = input_data.get("min_confidence", 0.5)
        min_success_rate = input_data.get("min_success_rate")
        limit = input_data.get("limit", 10)

        try:
            db, agent_id = await _memory_scope(context)
            stmt = select(ExperienceRecord).where(
                ExperienceRecord.agent_id == agent_id,
                ExperienceRecord.is_active.is_(True),
                ExperienceRecord.confidence_score >= min_confidence,
            )
            if experience_type:
                stmt = stmt.where(ExperienceRecord.experience_type == experience_type)
            if outcome:
                stmt = stmt.where(ExperienceRecord.outcome == outcome)
            if min_success_rate is not None:
                stmt = stmt.where(ExperienceRecord.success_rate >= min_success_rate)
            terms = [term for term in query_context.lower().split() if len(term) > 2]
            if terms:
                stmt = stmt.where(or_(*[
                    condition for term in terms
                    for condition in (
                        ExperienceRecord.situation.ilike(f"%{term}%"),
                        ExperienceRecord.action_taken.ilike(f"%{term}%"),
                        ExperienceRecord.lesson_learned.ilike(f"%{term}%"),
                        ExperienceRecord.title.ilike(f"%{term}%"),
                    )
                ]))
            stmt = stmt.order_by(
                ExperienceRecord.confidence_score.desc(),
                ExperienceRecord.success_rate.desc().nullslast(),
            ).limit(limit)
            records = (await db.execute(stmt)).scalars().all()
            patterns = [{
                "experience_id": str(record.id), "title": record.title,
                "experience_type": record.experience_type, "situation": record.situation,
                "action_taken": record.action_taken, "result": record.result,
                "outcome": record.outcome, "lesson_learned": record.lesson_learned,
                "confidence_score": record.confidence_score, "times_applied": record.times_applied,
                "success_rate": record.success_rate,
                "applicable_contexts": record.applicable_contexts,
            } for record in records]

            logger.info(f"Queried patterns for context: {query_context[:50]}..., found {len(patterns)}")

            return self.create_result(
                success=True,
                result_data={
                    "patterns": patterns,
                    "count": len(patterns),
                },
                output_text=f"Found {len(patterns)} relevant patterns",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to query patterns: {str(e)}",
            )


# ===== EXPERIENCE GET SUGGESTIONS TOOL =====

class ExperienceGetSuggestionsInput(BaseModel):
    """Input schema for getting suggestions"""
    current_situation: str = Field(..., min_length=1, description="Current situation needing suggestions")
    goal: str = Field(..., min_length=1, description="What you're trying to achieve")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum suggestions")


class Suggestion(BaseModel):
    """Experience-based suggestion"""
    suggestion_id: str
    action: str = Field(..., description="Suggested action")
    reasoning: str = Field(..., description="Why this is suggested")
    confidence: float = Field(..., description="Confidence in suggestion (0-1)")
    based_on_experience_id: str
    experience_title: str
    success_rate: Optional[float]
    times_applied: int
    provenance: str = "verified_outcome"


class ExperienceGetSuggestionsOutput(BaseModel):
    """Output schema for getting suggestions"""
    suggestions: List[Suggestion]
    count: int


class ExperienceGetSuggestionsTool(ToolBase):
    """Tool for getting action suggestions based on experience"""

    @property
    def name(self) -> str:
        return "experience_get_suggestions"

    @property
    def description(self) -> str:
        return "Get action suggestions based on past successful experiences."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExperienceGetSuggestionsInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperienceGetSuggestionsOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "experience"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Get suggestions from experience database"""
        current_situation = input_data["current_situation"]
        goal = input_data["goal"]
        limit = input_data.get("limit", 5)

        try:
            db, agent_id = await _memory_scope(context)
            stmt = select(ExperienceRecord).where(
                ExperienceRecord.agent_id == agent_id,
                ExperienceRecord.is_active.is_(True),
                ExperienceRecord.is_validated.is_(True),
                ExperienceRecord.outcome == "success",
                ExperienceRecord.success_rate.is_not(None),
            )
            terms = [term for term in (current_situation + " " + goal).lower().split()
                     if len(term) > 2]
            if terms:
                stmt = stmt.where(or_(*[
                    condition for term in terms
                    for condition in (
                        ExperienceRecord.situation.ilike(f"%{term}%"),
                        ExperienceRecord.lesson_learned.ilike(f"%{term}%"),
                        # A JSON list: matched as text so it works on PostgreSQL's json type as well.
                        cast(ExperienceRecord.applicable_contexts, String).ilike(f'%"{term}"%'),
                    )
                ]))
            stmt = stmt.order_by(
                ExperienceRecord.success_rate.desc(),
                ExperienceRecord.confidence_score.desc(),
            ).limit(limit)
            records = (await db.execute(stmt)).scalars().all()
            suggestions = [{
                "suggestion_id": str(record.id),
                "action": record.action_taken,
                "reasoning": f"Verified outcome ({record.success_rate:.2f} success rate): {record.lesson_learned}",
                "confidence": record.confidence_score,
                "based_on_experience_id": str(record.id),
                "experience_title": record.title,
                "success_rate": record.success_rate,
                "times_applied": record.times_applied,
                "provenance": "verified_outcome",
            } for record in records]

            logger.info(f"Generated {len(suggestions)} suggestions for: {current_situation[:50]}...")

            return self.create_result(
                success=True,
                result_data={
                    "suggestions": suggestions,
                    "count": len(suggestions),
                },
                output_text=f"Generated {len(suggestions)} suggestions from experience",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to get suggestions: {str(e)}",
            )


# ===== EXPERIENCE COMPARE APPROACHES TOOL =====

class ExperienceCompareApproachesInput(BaseModel):
    """Input schema for comparing approaches"""
    approach_a_id: str = Field(..., description="First experience ID to compare")
    approach_b_id: str = Field(..., description="Second experience ID to compare")
    comparison_criteria: List[str] = Field(
        default=["success_rate", "confidence", "applicability"],
        description="Criteria to compare: success_rate, confidence, times_applied, applicability"
    )


class ApproachComparison(BaseModel):
    """Comparison result"""
    approach_a: Dict[str, Any]
    approach_b: Dict[str, Any]
    comparison: Dict[str, str] = Field(..., description="Side-by-side comparison")
    recommendation: str = Field(..., description="Which approach is recommended")
    reasoning: str = Field(..., description="Why this approach is recommended")


class ExperienceCompareApproachesOutput(BaseModel):
    """Output schema for comparing approaches"""
    comparison: ApproachComparison


class ExperienceCompareApproachesTool(ToolBase):
    """Tool for comparing different approaches based on experience"""

    @property
    def name(self) -> str:
        return "experience_compare_approaches"

    @property
    def description(self) -> str:
        return "Compare two different approaches based on experience data."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExperienceCompareApproachesInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperienceCompareApproachesOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "experience"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Compare approaches from experience database"""
        approach_a_id = input_data["approach_a_id"]
        approach_b_id = input_data["approach_b_id"]
        criteria = input_data.get("comparison_criteria", ["success_rate", "confidence", "applicability"])

        try:
            db, agent_id = await _memory_scope(context)
            ids = [UUID(approach_a_id), UUID(approach_b_id)]
            records = (await db.execute(select(ExperienceRecord).where(
                ExperienceRecord.id.in_(ids), ExperienceRecord.agent_id == agent_id,
            ))).scalars().all()
            by_id = {record.id: record for record in records}
            if len(by_id) != 2:
                return self.create_result(success=False, error_message="One or both experiences are not in this agent/workspace scope")
            a, b = by_id[ids[0]], by_id[ids[1]]
            comparison = {}
            if "success_rate" in criteria:
                comparison["success_rate"] = f"A: {a.success_rate!r} vs B: {b.success_rate!r}"
            if "confidence" in criteria:
                comparison["confidence"] = f"A: {a.confidence_score:.2f} vs B: {b.confidence_score:.2f}"
            if "times_applied" in criteria:
                comparison["times_applied"] = f"A: {a.times_applied} vs B: {b.times_applied}"
            if "applicability" in criteria:
                comparison["applicability"] = (
                    f"A: {len(a.applicable_contexts)} contexts vs B: {len(b.applicable_contexts)} contexts")
            if not (a.is_validated and b.is_validated and
                    a.success_rate is not None and b.success_rate is not None):
                recommendation = "insufficient_verified_evidence"
                reasoning = "At least one approach lacks a verified outcome and measured success rate."
            elif a.success_rate > b.success_rate:
                recommendation, reasoning = "approach_a", "Approach A has the higher verified success rate."
            elif b.success_rate > a.success_rate:
                recommendation, reasoning = "approach_b", "Approach B has the higher verified success rate."
            else:
                recommendation, reasoning = "tie", "Verified success rates are equal."
            comparison_result = {
                "approach_a": {"id": str(a.id), "title": a.title, "success_rate": a.success_rate,
                                "confidence": a.confidence_score, "times_applied": a.times_applied},
                "approach_b": {"id": str(b.id), "title": b.title, "success_rate": b.success_rate,
                                "confidence": b.confidence_score, "times_applied": b.times_applied},
                "comparison": comparison, "recommendation": recommendation, "reasoning": reasoning,
            }

            logger.info(f"Compared approaches: {approach_a_id} vs {approach_b_id}")
            return self.create_result(
                success=True,
                result_data={"comparison": comparison_result},
                output_text=f"Compared approaches: {recommendation}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to compare approaches: {str(e)}",
            )
