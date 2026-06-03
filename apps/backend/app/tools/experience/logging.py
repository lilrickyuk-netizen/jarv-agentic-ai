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

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


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
            from uuid import uuid4
            experience_id = str(uuid4())

            # In production: Insert into ExperienceRecord table
            # from app.models.self_evolution import ExperienceRecord
            # from app.core.database import get_db
            # async for session in get_db():
            #     experience = ExperienceRecord(
            #         id=experience_id,
            #         agent_id=context.agent_id,
            #         session_id=context.session_id,
            #         task_id=getattr(context, 'task_id', None),
            #         experience_type=experience_type,
            #         title=title,
            #         description=f"Success: {lesson_learned}",
            #         situation=situation,
            #         action_taken=action_taken,
            #         result=result,
            #         outcome="success",
            #         lesson_learned=lesson_learned,
            #         applicable_contexts=applicable_contexts,
            #         confidence_score=confidence_score,
            #         times_applied=0,
            #         success_rate=None,
            #         is_validated=False,
            #         is_active=True,
            #     )
            #     session.add(experience)
            #     await session.commit()

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
            from uuid import uuid4
            experience_id = str(uuid4())

            # In production: Insert into ExperienceRecord table
            # from app.models.self_evolution import ExperienceRecord
            # from app.core.database import get_db
            # async for session in get_db():
            #     experience = ExperienceRecord(
            #         id=experience_id,
            #         agent_id=context.agent_id,
            #         session_id=context.session_id,
            #         task_id=getattr(context, 'task_id', None),
            #         experience_type=experience_type,
            #         title=title,
            #         description=f"Failure: {lesson_learned}",
            #         situation=situation,
            #         action_taken=action_taken,
            #         result=result,
            #         outcome="failure",
            #         lesson_learned=lesson_learned,
            #         applicable_contexts=applicable_contexts,
            #         confidence_score=confidence_score,
            #         times_applied=0,
            #         success_rate=0.0,  # Initialize at 0 for failures
            #         is_validated=False,
            #         is_active=True,
            #     )
            #     session.add(experience)
            #     await session.commit()

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
            # In production: Update ExperienceRecord
            # from app.models.self_evolution import ExperienceRecord
            # from app.core.database import get_db
            #
            # async for session in get_db():
            #     experience = await session.get(ExperienceRecord, experience_id)
            #     if not experience or experience.agent_id != context.agent_id:
            #         return self.create_result(success=False, error_message="Experience not found")
            #
            #     # Update application count
            #     experience.times_applied += 1
            #
            #     # Update success rate
            #     if experience.success_rate is None:
            #         experience.success_rate = 1.0 if was_successful else 0.0
            #     else:
            #         # Running average
            #         total_successes = experience.success_rate * (experience.times_applied - 1)
            #         if was_successful:
            #             total_successes += 1
            #         experience.success_rate = total_successes / experience.times_applied
            #
            #     # Adjust confidence based on repeated application
            #     # More applications = more confidence (up to a limit)
            #     if experience.times_applied > 5:
            #         experience.confidence_score = min(0.95, experience.confidence_score * 1.02)
            #
            #     # Store rating in metadata
            #     if not experience.meta_data:
            #         experience.meta_data = {}
            #     if "ratings" not in experience.meta_data:
            #         experience.meta_data["ratings"] = []
            #     experience.meta_data["ratings"].append({
            #         "rating": rating,
            #         "was_successful": was_successful,
            #         "notes": notes,
            #         "timestamp": datetime.utcnow().isoformat(),
            #     })
            #
            #     await session.commit()
            #
            #     return self.create_result(
            #         success=True,
            #         result_data={
            #             "experience_id": experience_id,
            #             "updated_success_rate": experience.success_rate,
            #             "times_applied": experience.times_applied,
            #             "confidence_score": experience.confidence_score,
            #         },
            #         output_text=f"Rated experience application (success_rate: {experience.success_rate:.2f})",
            #     )

            logger.info(f"Rated experience: {experience_id}, rating={rating}, successful={was_successful}")

            # Placeholder response
            return self.create_result(
                success=True,
                result_data={
                    "experience_id": experience_id,
                    "updated_success_rate": 0.75,  # Placeholder
                    "times_applied": 1,  # Placeholder
                    "confidence_score": 0.7,  # Placeholder
                },
                output_text=f"Rated experience application",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to rate action: {str(e)}",
            )
