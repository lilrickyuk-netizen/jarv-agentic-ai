"""
JARV Backend - Experience Logging Tools

Tools for logging agent experiences (successes, failures, ratings).

SETUP INSTRUCTIONS:
- Experience data stored in PostgreSQL database (ExperienceRecord table)
- Uses Situation-Action-Result pattern for learning
- Tracks success rate, confidence score, applicability
- No external dependencies - fully local

Experience helps agents learn from past actions and improve over time.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import logging
from uuid import UUID, uuid4
from sqlalchemy import select

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.tools.memory.storage import _memory_scope
from app.models.self_evolution import ExperienceRecord
from app.core.safety.evolution_guard import classify_change
from app.core.security import redact_text

logger = logging.getLogger(__name__)


def _guarded(lesson: str, situation: str, action: str, result: str):
    """Redact secrets and apply the self-evolution safety guard: a lesson that would weaken
    safety, authority, logging or verification is stored rejected and inactive."""
    lesson, situation, action, result = (redact_text(lesson), redact_text(situation),
                                         redact_text(action), redact_text(result))
    unsafe, matched = classify_change(lesson)
    extra = {"lesson_status": "rejected", "is_active": False} if unsafe else {"lesson_status": "candidate",
                                                                              "is_active": True}
    return lesson, situation, action, result, extra, (f"safety guard: '{matched}'" if unsafe else None)


# ===== EXPERIENCE LOG SUCCESS TOOL =====

class ExperienceLogSuccessInput(BaseModel):
    """Input schema for logging successful experience"""
    title: str = Field(..., min_length=1, max_length=500, description="Brief title of experience")
    situation: str = Field(..., min_length=1, description="What was the situation/context")
    action_taken: str = Field(..., min_length=1, description="What action was taken")
    result: str = Field(..., min_length=1, description="What was the outcome")
    lesson_learned: str = Field(..., min_length=1, description="Key lesson from this experience")
    applicable_contexts: List[str] = Field(..., min_items=1, description="Contexts where this applies")
    confidence_score: float = Field(default=0.7, ge=0.0, le=1.0, description="Confidence in this lesson (0-1)")
    experience_type: str = Field(default="success_pattern", description="Type: success_pattern, best_practice, optimization, etc.")


class ExperienceLogSuccessOutput(BaseModel):
    """Output schema for logging successful experience"""
    experience_id: str
    title: str
    outcome: str = "success"
    confidence_score: float
    applicable_contexts: List[str]


class ExperienceLogSuccessTool(ToolBase):
    """Tool for logging successful action patterns"""

    @property
    def name(self) -> str:
        return "experience_log_success"

    @property
    def description(self) -> str:
        return "Log successful action pattern so agent can learn and reuse this approach."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExperienceLogSuccessInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperienceLogSuccessOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return False  # Logging experience is safe

    @property
    def category(self) -> str:
        return "experience"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Log successful experience to database"""
        title = input_data["title"]
        situation = input_data["situation"]
        action_taken = input_data["action_taken"]
        result = input_data["result"]
        lesson_learned = input_data["lesson_learned"]
        applicable_contexts = input_data["applicable_contexts"]
        confidence_score = input_data.get("confidence_score", 0.7)
        experience_type = input_data.get("experience_type", "success_pattern")

        try:
            db, agent_id = await _memory_scope(context)
            lesson_learned, situation, action_taken, result, guard, rejected = _guarded(
                lesson_learned, situation, action_taken, result)
            record = ExperienceRecord(
                id=uuid4(), agent_id=agent_id, session_id=context.session_id,
                task_id=context.task_id, experience_type=experience_type,
                title=title, description=f"Caller-reported success: {lesson_learned}",
                situation=situation, action_taken=action_taken, result=result,
                outcome="success", lesson_learned=lesson_learned,
                applicable_contexts=applicable_contexts,
                confidence_score=confidence_score, times_applied=0,
                success_rate=None, is_validated=False, workspace_id=context.workspace_id, **guard,
                meta_data={"workspace_id": str(context.workspace_id), "provenance": "caller_reported",
                           **({"rejected_reason": rejected} if rejected else {})},
            )
            db.add(record)
            await db.flush()
            experience_id = str(record.id)

            logger.info(f"Logged successful experience: {experience_id}, type={experience_type}, confidence={confidence_score}")

            return self.create_result(
                success=True,
                result_data={
                    "experience_id": experience_id,
                    "title": title,
                    "outcome": "success",
                    "confidence_score": confidence_score,
                    "applicable_contexts": applicable_contexts,
                },
                output_text=f"Logged successful experience: {title}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to log experience: {str(e)}",
            )


# ===== EXPERIENCE LOG FAILURE TOOL =====

class ExperienceLogFailureInput(BaseModel):
    """Input schema for logging failed experience"""
    title: str = Field(..., min_length=1, max_length=500, description="Brief title of experience")
    situation: str = Field(..., min_length=1, description="What was the situation/context")
    action_taken: str = Field(..., min_length=1, description="What action was taken")
    result: str = Field(..., min_length=1, description="What went wrong")
    lesson_learned: str = Field(..., min_length=1, description="What to avoid or do differently")
    applicable_contexts: List[str] = Field(..., min_items=1, description="Contexts where this applies")
    confidence_score: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence in this lesson (0-1)")
    experience_type: str = Field(default="failure_pattern", description="Type: failure_pattern, anti_pattern, mistake, etc.")


class ExperienceLogFailureOutput(BaseModel):
    """Output schema for logging failed experience"""
    experience_id: str
    title: str
    outcome: str = "failure"
    confidence_score: float
    applicable_contexts: List[str]


class ExperienceLogFailureTool(ToolBase):
    """Tool for logging failed action patterns"""

    @property
    def name(self) -> str:
        return "experience_log_failure"

    @property
    def description(self) -> str:
        return "Log failed action pattern so agent can learn what to avoid."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExperienceLogFailureInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperienceLogFailureOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "experience"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Log failed experience to database"""
        title = input_data["title"]
        situation = input_data["situation"]
        action_taken = input_data["action_taken"]
        result = input_data["result"]
        lesson_learned = input_data["lesson_learned"]
        applicable_contexts = input_data["applicable_contexts"]
        confidence_score = input_data.get("confidence_score", 0.8)
        experience_type = input_data.get("experience_type", "failure_pattern")

        try:
            db, agent_id = await _memory_scope(context)
            lesson_learned, situation, action_taken, result, guard, rejected = _guarded(
                lesson_learned, situation, action_taken, result)
            record = ExperienceRecord(
                id=uuid4(), agent_id=agent_id, session_id=context.session_id,
                task_id=context.task_id, experience_type=experience_type,
                title=title, description=f"Caller-reported failure: {lesson_learned}",
                situation=situation, action_taken=action_taken, result=result,
                outcome="failure", lesson_learned=lesson_learned,
                applicable_contexts=applicable_contexts,
                confidence_score=confidence_score, times_applied=0,
                success_rate=None, is_validated=False, workspace_id=context.workspace_id, **guard,
                meta_data={"workspace_id": str(context.workspace_id), "provenance": "caller_reported",
                           **({"rejected_reason": rejected} if rejected else {})},
            )
            db.add(record)
            await db.flush()
            experience_id = str(record.id)

            logger.info(f"Logged failed experience: {experience_id}, type={experience_type}, confidence={confidence_score}")

            return self.create_result(
                success=True,
                result_data={
                    "experience_id": experience_id,
                    "title": title,
                    "outcome": "failure",
                    "confidence_score": confidence_score,
                    "applicable_contexts": applicable_contexts,
                },
                output_text=f"Logged failed experience: {title}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to log experience: {str(e)}",
            )


# ===== EXPERIENCE RATE ACTION TOOL =====

class ExperienceRateActionInput(BaseModel):
    """Input schema for rating action quality"""
    experience_id: str = Field(..., description="Experience ID to rate")
    rating: float = Field(..., ge=0.0, le=1.0, description="Quality rating (0-1)")
    was_successful: bool = Field(..., description="Whether action was successful this time")
    notes: Optional[str] = Field(None, description="Optional notes about this application")


class ExperienceRateActionOutput(BaseModel):
    """Output schema for rating action"""
    experience_id: str
    updated_success_rate: float
    times_applied: int
    confidence_score: float


class ExperienceRateActionTool(ToolBase):
    """Tool for rating action quality after application"""

    @property
    def name(self) -> str:
        return "experience_rate_action"

    @property
    def description(self) -> str:
        return "Rate action quality after applying learned pattern to update success rate."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExperienceRateActionInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperienceRateActionOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "experience"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Rate experience application in database"""
        experience_id = input_data["experience_id"]
        rating = input_data["rating"]
        was_successful = input_data["was_successful"]
        notes = input_data.get("notes")

        try:
            db, agent_id = await _memory_scope(context)
            record = (await db.execute(select(ExperienceRecord).where(
                ExperienceRecord.id == UUID(experience_id),
                ExperienceRecord.agent_id == agent_id,
                ExperienceRecord.meta_data["workspace_id"].as_string() == str(context.workspace_id),
            ))).scalar_one_or_none()
            if record is None:
                return self.create_result(success=False, error_message="Experience not found in this agent/workspace scope")
            previous_count = record.times_applied
            record.times_applied += 1
            previous_successes = (record.success_rate or 0.0) * previous_count
            record.success_rate = (previous_successes + int(was_successful)) / record.times_applied
            metadata = dict(record.meta_data or {})
            ratings = list(metadata.get("ratings", []))
            ratings.append({
                "rating": rating, "was_successful": was_successful,
                "notes": notes, "timestamp": datetime.utcnow().isoformat(),
                "provenance": "caller_reported",
            })
            metadata["ratings"] = ratings
            record.meta_data = metadata
            await db.flush()
            logger.info(f"Rated experience: {experience_id}, rating={rating}, successful={was_successful}")
            return self.create_result(
                success=True,
                result_data={
                    "experience_id": experience_id,
                    "updated_success_rate": record.success_rate,
                    "times_applied": record.times_applied,
                    "confidence_score": record.confidence_score,
                    "validated": record.is_validated,
                },
                output_text=f"Rated experience application",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to rate action: {str(e)}",
            )
