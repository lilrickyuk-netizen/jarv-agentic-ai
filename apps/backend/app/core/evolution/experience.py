"""
JARV Backend - Experience Management

Captures, summarizes, and extracts lessons from agent experiences.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ExperienceType(str, Enum):
    """Type of experience"""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ExperienceCreate(BaseModel):
    """Schema for creating experience record"""
    workspace_id: UUID
    agent_id: UUID
    agent_name: str
    task_description: str
    experience_type: ExperienceType
    tools_used: List[str] = Field(default_factory=list)
    actions_taken: List[str] = Field(default_factory=list)
    outcome: str
    duration_seconds: float
    tokens_used: Dict[str, int] = Field(default_factory=dict)
    cost_estimate: float = 0.0
    context: Dict[str, Any] = Field(default_factory=dict)
    error_details: Optional[str] = None


class LessonExtract(BaseModel):
    """Extracted lesson from experience"""
    lesson_text: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    applicable_to: List[str] = Field(default_factory=list)  # agents, tools, patterns
    improvement_areas: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExperienceResult(BaseModel):
    """Experience record result"""
    id: UUID
    workspace_id: UUID
    agent_id: UUID
    agent_name: str
    task_description: str
    experience_type: ExperienceType
    tools_used: List[str]
    actions_taken: List[str]
    outcome: str
    duration_seconds: float
    tokens_used: Dict[str, int]
    cost_estimate: float
    context: Dict[str, Any]
    error_details: Optional[str]
    summary: Optional[str]
    lessons: List[LessonExtract]
    created_at: datetime
    updated_at: datetime


class ExperienceManager:
    """
    Manages experience capture and learning.

    Captures agent experiences, summarizes them, and extracts lessons.
    """

    def __init__(self):
        """Initialize experience manager"""
        self.logger = logging.getLogger("evolution.experience")

    async def capture_experience(
        self,
        experience: ExperienceCreate,
    ) -> UUID:
        """
        Capture an agent experience.

        In production: Insert into ExperienceRecord table.

        Args:
            experience: Experience data

        Returns:
            Experience ID
        """
        try:
            # In production: Insert into database
            # from app.models.evolution import ExperienceRecord as DBExperience
            # from app.core.database import get_db
            # async with get_db() as db:
            #     db_experience = DBExperience(
            #         workspace_id=experience.workspace_id,
            #         agent_id=experience.agent_id,
            #         agent_name=experience.agent_name,
            #         task_description=experience.task_description,
            #         experience_type=experience.experience_type,
            #         tools_used=experience.tools_used,
            #         actions_taken=experience.actions_taken,
            #         outcome=experience.outcome,
            #         duration_seconds=experience.duration_seconds,
            #         tokens_used=experience.tokens_used,
            #         cost_estimate=experience.cost_estimate,
            #         context=experience.context,
            #         error_details=experience.error_details,
            #     )
            #     db.add(db_experience)
            #     await db.commit()
            #     experience_id = db_experience.id

            experience_id = uuid4()

            self.logger.info(
                f"Captured experience: {experience.experience_type}",
                extra={
                    "experience_id": str(experience_id),
                    "agent_name": experience.agent_name,
                    "workspace_id": str(experience.workspace_id),
                }
            )

            return experience_id

        except Exception as e:
            self.logger.error(
                f"Failed to capture experience: {e}",
                extra={"agent_name": experience.agent_name},
                exc_info=True
            )
            raise

    async def summarize_experience(
        self,
        experience_id: UUID,
    ) -> str:
        """
        Summarize an experience using LLM.

        In production: Load experience, send to LLM for summarization.

        Args:
            experience_id: Experience ID

        Returns:
            Summary text
        """
        try:
            # In production:
            # 1. Load experience from database
            # 2. Create prompt with experience details
            # 3. Send to LLM (Claude/GPT) for summarization
            # 4. Update experience record with summary
            # 5. Return summary

            summary = "Experience summary placeholder"

            self.logger.info(
                f"Summarized experience",
                extra={"experience_id": str(experience_id)}
            )

            return summary

        except Exception as e:
            self.logger.error(
                f"Failed to summarize experience: {e}",
                extra={"experience_id": str(experience_id)},
                exc_info=True
            )
            raise

    async def extract_lesson(
        self,
        experience_id: UUID,
    ) -> List[LessonExtract]:
        """
        Extract lessons from experience using LLM.

        In production: Analyze experience and extract actionable lessons.

        Args:
            experience_id: Experience ID

        Returns:
            List of extracted lessons
        """
        try:
            # In production:
            # 1. Load experience and summary from database
            # 2. Create prompt for lesson extraction
            # 3. Send to LLM (Claude/GPT) with structured output
            # 4. Parse lessons with confidence scores
            # 5. Identify applicable areas (agents, tools, patterns)
            # 6. Store lessons in database
            # 7. Return lessons

            lessons = [
                LessonExtract(
                    lesson_text="Placeholder lesson",
                    confidence_score=0.8,
                    applicable_to=["agent", "tool"],
                    improvement_areas=["efficiency", "accuracy"],
                )
            ]

            self.logger.info(
                f"Extracted {len(lessons)} lessons from experience",
                extra={"experience_id": str(experience_id)}
            )

            return lessons

        except Exception as e:
            self.logger.error(
                f"Failed to extract lessons: {e}",
                extra={"experience_id": str(experience_id)},
                exc_info=True
            )
            raise

    async def get_experience(
        self,
        experience_id: UUID,
    ) -> Optional[ExperienceResult]:
        """Get experience by ID"""
        # In production: Query database
        return None

    async def list_experiences(
        self,
        workspace_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        experience_type: Optional[ExperienceType] = None,
        limit: int = 100,
    ) -> List[ExperienceResult]:
        """List experiences with filters"""
        # In production: Query database with filters
        return []

    async def get_experience_stats(
        self,
        workspace_id: UUID,
    ) -> Dict[str, Any]:
        """Get experience statistics"""
        return {
            "total_experiences": 0,
            "by_type": {},
            "total_lessons": 0,
            "avg_confidence": 0.0,
            "top_improvement_areas": [],
        }


# Global experience manager
_experience_manager = ExperienceManager()


async def capture_experience(experience: ExperienceCreate) -> UUID:
    """Global function to capture experience"""
    return await _experience_manager.capture_experience(experience)


async def summarize_experience(experience_id: UUID) -> str:
    """Global function to summarize experience"""
    return await _experience_manager.summarize_experience(experience_id)


async def extract_lesson(experience_id: UUID) -> List[LessonExtract]:
    """Global function to extract lessons"""
    return await _experience_manager.extract_lesson(experience_id)
