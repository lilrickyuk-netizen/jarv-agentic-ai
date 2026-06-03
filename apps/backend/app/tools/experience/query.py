"""
JARV Backend - Experience Query Tools

Tools for querying learned patterns and getting suggestions from experience.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
import logging

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
            patterns = []

            # In production: Query ExperienceRecord table
            # from app.models.self_evolution import ExperienceRecord
            # from app.core.database import get_db
            # from sqlalchemy import select, or_, func
            #
            # async for session in get_db():
            #     stmt = select(ExperienceRecord).filter(
            #         ExperienceRecord.agent_id == context.agent_id,
            #         ExperienceRecord.is_active == True,
            #         ExperienceRecord.confidence_score >= min_confidence,
            #     )
            #
            #     # Filter by type
            #     if experience_type:
            #         stmt = stmt.filter(ExperienceRecord.experience_type == experience_type)
            #
            #     # Filter by outcome
            #     if outcome:
            #         stmt = stmt.filter(ExperienceRecord.outcome == outcome)
            #
            #     # Filter by success rate
            #     if min_success_rate is not None:
            #         stmt = stmt.filter(ExperienceRecord.success_rate >= min_success_rate)
            #
            #     # Search for relevant context
            #     # Use full-text search or filter by applicable_contexts
            #     stmt = stmt.filter(
            #         or_(
            #             ExperienceRecord.situation.ilike(f"%{query_context}%"),
            #             ExperienceRecord.applicable_contexts.contains([query_context])
            #         )
            #     )
            #
            #     # Order by confidence and success rate
            #     stmt = stmt.order_by(
            #         ExperienceRecord.confidence_score.desc(),
            #         ExperienceRecord.success_rate.desc().nullslast()
            #     ).limit(limit)
            #
            #     result = await session.execute(stmt)
            #     for exp in result.scalars():
            #         patterns.append({
            #             "experience_id": str(exp.id),
            #             "title": exp.title,
            #             "experience_type": exp.experience_type,
            #             "situation": exp.situation,
            #             "action_taken": exp.action_taken,
            #             "result": exp.result,
            #             "outcome": exp.outcome,
            #             "lesson_learned": exp.lesson_learned,
            #             "confidence_score": exp.confidence_score,
            #             "times_applied": exp.times_applied,
            #             "success_rate": exp.success_rate,
            #             "applicable_contexts": exp.applicable_contexts,
            #         })

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
            suggestions = []

            # In production: Query successful experiences and generate suggestions
            # from app.models.self_evolution import ExperienceRecord
            # from app.core.database import get_db
            # from sqlalchemy import select, or_
            # from uuid import uuid4
            #
            # async for session in get_db():
            #     # Find successful experiences relevant to situation and goal
            #     stmt = select(ExperienceRecord).filter(
            #         ExperienceRecord.agent_id == context.agent_id,
            #         ExperienceRecord.is_active == True,
            #         ExperienceRecord.outcome == "success",
            #         or_(
            #             ExperienceRecord.situation.ilike(f"%{current_situation}%"),
            #             ExperienceRecord.lesson_learned.ilike(f"%{goal}%")
            #         )
            #     ).order_by(
            #         ExperienceRecord.success_rate.desc().nullslast(),
            #         ExperienceRecord.confidence_score.desc()
            #     ).limit(limit)
            #
            #     result = await session.execute(stmt)
            #     for exp in result.scalars():
            #         suggestions.append({
            #             "suggestion_id": str(uuid4()),
            #             "action": exp.action_taken,
            #             "reasoning": f"Based on experience: {exp.lesson_learned}",
            #             "confidence": exp.confidence_score,
            #             "based_on_experience_id": str(exp.id),
            #             "experience_title": exp.title,
            #             "success_rate": exp.success_rate,
            #             "times_applied": exp.times_applied,
            #         })

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
            # In production: Fetch both experiences and compare
            # from app.models.self_evolution import ExperienceRecord
            # from app.core.database import get_db
            #
            # async for session in get_db():
            #     exp_a = await session.get(ExperienceRecord, approach_a_id)
            #     exp_b = await session.get(ExperienceRecord, approach_b_id)
            #
            #     if not exp_a or not exp_b:
            #         return self.create_result(success=False, error_message="One or both experiences not found")
            #
            #     if exp_a.agent_id != context.agent_id or exp_b.agent_id != context.agent_id:
            #         return self.create_result(success=False, error_message="Access denied to experiences")
            #
            #     # Build comparison
            #     comparison_details = {}
            #     score_a = 0
            #     score_b = 0
            #
            #     if "success_rate" in criteria:
            #         sr_a = exp_a.success_rate or 0.5
            #         sr_b = exp_b.success_rate or 0.5
            #         comparison_details["success_rate"] = f"A: {sr_a:.2f} vs B: {sr_b:.2f}"
            #         if sr_a > sr_b:
            #             score_a += 1
            #         elif sr_b > sr_a:
            #             score_b += 1
            #
            #     if "confidence" in criteria:
            #         comparison_details["confidence"] = f"A: {exp_a.confidence_score:.2f} vs B: {exp_b.confidence_score:.2f}"
            #         if exp_a.confidence_score > exp_b.confidence_score:
            #             score_a += 1
            #         elif exp_b.confidence_score > exp_a.confidence_score:
            #             score_b += 1
            #
            #     if "times_applied" in criteria:
            #         comparison_details["times_applied"] = f"A: {exp_a.times_applied} vs B: {exp_b.times_applied}"
            #         if exp_a.times_applied > exp_b.times_applied:
            #             score_a += 0.5
            #         elif exp_b.times_applied > exp_a.times_applied:
            #             score_b += 0.5
            #
            #     if "applicability" in criteria:
            #         comparison_details["applicability"] = f"A: {len(exp_a.applicable_contexts)} contexts vs B: {len(exp_b.applicable_contexts)} contexts"
            #         if len(exp_a.applicable_contexts) > len(exp_b.applicable_contexts):
            #             score_a += 0.5
            #         elif len(exp_b.applicable_contexts) > len(exp_a.applicable_contexts):
            #             score_b += 0.5
            #
            #     # Determine recommendation
            #     if score_a > score_b:
            #         recommendation = "approach_a"
            #         reasoning = f"Approach A scores higher ({score_a:.1f} vs {score_b:.1f}) across selected criteria"
            #     elif score_b > score_a:
            #         recommendation = "approach_b"
            #         reasoning = f"Approach B scores higher ({score_b:.1f} vs {score_a:.1f}) across selected criteria"
            #     else:
            #         recommendation = "tie"
            #         reasoning = "Both approaches score equally; choose based on context"
            #
            #     comparison_result = {
            #         "approach_a": {
            #             "id": str(exp_a.id),
            #             "title": exp_a.title,
            #             "success_rate": exp_a.success_rate,
            #             "confidence": exp_a.confidence_score,
            #             "times_applied": exp_a.times_applied,
            #         },
            #         "approach_b": {
            #             "id": str(exp_b.id),
            #             "title": exp_b.title,
            #             "success_rate": exp_b.success_rate,
            #             "confidence": exp_b.confidence_score,
            #             "times_applied": exp_b.times_applied,
            #         },
            #         "comparison": comparison_details,
            #         "recommendation": recommendation,
            #         "reasoning": reasoning,
            #     }
            #
            #     return self.create_result(
            #         success=True,
            #         result_data={"comparison": comparison_result},
            #         output_text=f"Comparison complete: {recommendation}",
            #     )

            logger.info(f"Compared approaches: {approach_a_id} vs {approach_b_id}")

            # Placeholder response
            return self.create_result(
                success=False,
                error_message=f"Approach comparison not yet connected to database",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to compare approaches: {str(e)}",
            )
