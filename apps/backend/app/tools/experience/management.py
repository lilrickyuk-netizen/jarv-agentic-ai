"""
JARV Backend - Experience Management Tools

Tools for managing experience data: export, import, analysis, visualization, pruning, consolidation.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import logging
import json

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


# ===== EXPERIENCE EXPORT TOOL =====

class ExperienceExportInput(BaseModel):
    """Input schema for exporting experiences"""
    experience_type: Optional[str] = Field(None, description="Export only this type")
    outcome: Optional[str] = Field(None, description="Filter by outcome: success, failure, mixed")
    min_confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Minimum confidence")
    format: str = Field(default="json", description="Export format: json or csv")


class ExperienceExportOutput(BaseModel):
    """Output schema for exporting experiences"""
    export_data: str
    count: int
    format: str
    export_size_bytes: int


class ExperienceExportTool(ToolBase):
    """Tool for exporting learned experiences"""

    @property
    def name(self) -> str:
        return "experience_export"

    @property
    def description(self) -> str:
        return "Export learned experiences to JSON or CSV format."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExperienceExportInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperienceExportOutput

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
        """Export experiences from database"""
        experience_type = input_data.get("experience_type")
        outcome = input_data.get("outcome")
        min_confidence = input_data.get("min_confidence")
        export_format = input_data.get("format", "json")

        try:
            experiences = []

            # In production: Query and export experiences
            # from app.models.self_evolution import ExperienceRecord
            # from app.core.database import get_db
            # from sqlalchemy import select
            #
            # async for session in get_db():
            #     stmt = select(ExperienceRecord).filter(ExperienceRecord.agent_id == context.agent_id)
            #
            #     if experience_type:
            #         stmt = stmt.filter(ExperienceRecord.experience_type == experience_type)
            #     if outcome:
            #         stmt = stmt.filter(ExperienceRecord.outcome == outcome)
            #     if min_confidence is not None:
            #         stmt = stmt.filter(ExperienceRecord.confidence_score >= min_confidence)
            #
            #     result = await session.execute(stmt)
            #     for exp in result.scalars():
            #         experiences.append({
            #             "id": str(exp.id),
            #             "experience_type": exp.experience_type,
            #             "title": exp.title,
            #             "description": exp.description,
            #             "situation": exp.situation,
            #             "action_taken": exp.action_taken,
            #             "result": exp.result,
            #             "outcome": exp.outcome,
            #             "lesson_learned": exp.lesson_learned,
            #             "applicable_contexts": exp.applicable_contexts,
            #             "confidence_score": exp.confidence_score,
            #             "times_applied": exp.times_applied,
            #             "success_rate": exp.success_rate,
            #             "is_validated": exp.is_validated,
            #             "created_at": exp.created_at.isoformat(),
            #         })

            # Format export data
            if export_format == "json":
                export_data = json.dumps(experiences, indent=2)
            elif export_format == "csv":
                import csv
                import io
                output = io.StringIO()
                if experiences:
                    fieldnames = ["id", "experience_type", "title", "situation", "action_taken", "result", "outcome", "lesson_learned", "confidence_score"]
                    writer = csv.DictWriter(output, fieldnames=fieldnames)
                    writer.writeheader()
                    for exp in experiences:
                        writer.writerow({k: exp.get(k, "") for k in fieldnames})
                export_data = output.getvalue()
            else:
                return self.create_result(
                    success=False,
                    error_message=f"Unsupported export format: {export_format}",
                )

            export_size = len(export_data.encode('utf-8'))
            logger.info(f"Exported {len(experiences)} experiences ({export_size} bytes)")

            return self.create_result(
                success=True,
                result_data={
                    "export_data": export_data,
                    "count": len(experiences),
                    "format": export_format,
                    "export_size_bytes": export_size,
                },
                output_text=f"Exported {len(experiences)} experiences as {export_format}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to export experiences: {str(e)}",
            )


# ===== EXPERIENCE IMPORT TOOL =====

class ExperienceImportInput(BaseModel):
    """Input schema for importing experiences"""
    import_data: str = Field(..., description="Experience data to import (JSON format)")
    merge_strategy: str = Field(default="skip", description="Merge strategy: skip, overwrite, or create_new")
    validate_imports: bool = Field(default=True, description="Whether to validate imported experiences")


class ExperienceImportOutput(BaseModel):
    """Output schema for importing experiences"""
    imported_count: int
    skipped_count: int
    overwritten_count: int
    errors: List[str]


class ExperienceImportTool(ToolBase):
    """Tool for importing experiences"""

    @property
    def name(self) -> str:
        return "experience_import"

    @property
    def description(self) -> str:
        return "Import experiences from JSON format."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExperienceImportInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperienceImportOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return True  # Importing can create many experiences

    @property
    def category(self) -> str:
        return "experience"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Import experiences to database"""
        import_data = input_data["import_data"]
        merge_strategy = input_data.get("merge_strategy", "skip")
        validate_imports = input_data.get("validate_imports", True)

        try:
            # Parse import data
            try:
                experiences_data = json.loads(import_data)
                if not isinstance(experiences_data, list):
                    return self.create_result(
                        success=False,
                        error_message="Import data must be a JSON array of experiences",
                    )
            except json.JSONDecodeError as e:
                return self.create_result(
                    success=False,
                    error_message=f"Invalid JSON: {str(e)}",
                )

            imported_count = 0
            skipped_count = 0
            overwritten_count = 0
            errors = []

            # In production: Import experiences to database
            # Similar to memory import logic

            logger.info(f"Imported {imported_count} experiences, skipped {skipped_count}, overwritten {overwritten_count}")

            return self.create_result(
                success=True,
                result_data={
                    "imported_count": imported_count,
                    "skipped_count": skipped_count,
                    "overwritten_count": overwritten_count,
                    "errors": errors,
                },
                output_text=f"Imported {imported_count} experiences (skipped: {skipped_count}, errors: {len(errors)})",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to import experiences: {str(e)}",
            )


# ===== EXPERIENCE ANALYZE TOOL =====

class ExperienceAnalyzeOutput(BaseModel):
    """Output schema for analyzing experiences"""
    total_experiences: int
    by_type: Dict[str, int]
    by_outcome: Dict[str, int]
    average_confidence: float
    average_success_rate: float
    most_successful_patterns: List[Dict[str, Any]]
    most_applied_patterns: List[Dict[str, Any]]
    recommendations: List[str]


class ExperienceAnalyzeTool(ToolBase):
    """Tool for analyzing experience patterns"""

    @property
    def name(self) -> str:
        return "experience_analyze"

    @property
    def description(self) -> str:
        return "Analyze experience patterns and generate insights."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return None  # No input needed

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperienceAnalyzeOutput

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
        """Analyze experience patterns from database"""
        try:
            analysis = {
                "total_experiences": 0,
                "by_type": {},
                "by_outcome": {},
                "average_confidence": 0.0,
                "average_success_rate": 0.0,
                "most_successful_patterns": [],
                "most_applied_patterns": [],
                "recommendations": [],
            }

            # In production: Analyze ExperienceRecord table
            # Similar to memory stats logic

            logger.info(f"Analyzed {analysis['total_experiences']} experiences")

            return self.create_result(
                success=True,
                result_data=analysis,
                output_text=f"Experience analysis complete: {analysis['total_experiences']} experiences",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to analyze experiences: {str(e)}",
            )


# ===== EXPERIENCE VISUALIZE TOOL =====

class ExperienceVisualizeInput(BaseModel):
    """Input schema for visualizing experiences"""
    visualization_type: str = Field(..., description="Type: timeline, success_rate, distribution, network")
    filters: Optional[Dict[str, Any]] = Field(None, description="Optional filters")


class ExperienceVisualizeOutput(BaseModel):
    """Output schema for visualizing experiences"""
    visualization_data: Dict[str, Any] = Field(..., description="Data for visualization")
    visualization_type: str
    data_points: int


class ExperienceVisualizeTool(ToolBase):
    """Tool for visualizing experience data"""

    @property
    def name(self) -> str:
        return "experience_visualize"

    @property
    def description(self) -> str:
        return "Generate visualization data for experience patterns."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExperienceVisualizeInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperienceVisualizeOutput

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
        """Generate visualization data from experiences"""
        viz_type = input_data["visualization_type"]
        filters = input_data.get("filters") or {}

        try:
            visualization_data = {}
            data_points = 0

            # In production: Query experiences and generate visualization data
            # Timeline: experiences over time
            # Success Rate: success rate by type or context
            # Distribution: count by type, outcome, confidence ranges
            # Network: relationships between patterns

            logger.info(f"Generated {viz_type} visualization with {data_points} data points")

            return self.create_result(
                success=True,
                result_data={
                    "visualization_data": visualization_data,
                    "visualization_type": viz_type,
                    "data_points": data_points,
                },
                output_text=f"Generated {viz_type} visualization ({data_points} data points)",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to generate visualization: {str(e)}",
            )


# ===== EXPERIENCE PRUNE TOOL =====

class ExperiencePruneInput(BaseModel):
    """Input schema for pruning experiences"""
    max_age_days: Optional[int] = Field(None, ge=1, description="Remove experiences older than this")
    min_confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Remove below this confidence")
    max_failure_rate: Optional[float] = Field(None, ge=0.0, le=1.0, description="Remove above this failure rate")
    inactive_only: bool = Field(default=True, description="Only prune inactive experiences")
    dry_run: bool = Field(default=True, description="Preview what would be pruned without deleting")


class ExperiencePruneOutput(BaseModel):
    """Output schema for pruning experiences"""
    would_prune_count: int = Field(..., description="Number that would be pruned (dry run)")
    actually_pruned_count: int = Field(..., description="Number actually pruned")
    pruned_ids: List[str] = Field(..., description="IDs of pruned experiences")


class ExperiencePruneTool(ToolBase):
    """Tool for removing outdated experiences"""

    @property
    def name(self) -> str:
        return "experience_prune"

    @property
    def description(self) -> str:
        return "Remove outdated or low-quality experiences from the database."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExperiencePruneInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperiencePruneOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return True  # Pruning can delete many experiences

    @property
    def category(self) -> str:
        return "experience"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Prune experiences from database"""
        max_age_days = input_data.get("max_age_days")
        min_confidence = input_data.get("min_confidence")
        max_failure_rate = input_data.get("max_failure_rate")
        inactive_only = input_data.get("inactive_only", True)
        dry_run = input_data.get("dry_run", True)

        try:
            would_prune_count = 0
            actually_pruned_count = 0
            pruned_ids = []

            # In production: Query and delete experiences matching criteria
            # Similar to memory delete logic but with filters

            logger.info(f"Pruned {actually_pruned_count} experiences (dry_run={dry_run})")

            return self.create_result(
                success=True,
                result_data={
                    "would_prune_count": would_prune_count,
                    "actually_pruned_count": actually_pruned_count,
                    "pruned_ids": pruned_ids,
                },
                output_text=f"{'Would prune' if dry_run else 'Pruned'} {would_prune_count if dry_run else actually_pruned_count} experiences",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to prune experiences: {str(e)}",
            )


# ===== EXPERIENCE CONSOLIDATE TOOL =====

class ExperienceConsolidateInput(BaseModel):
    """Input schema for consolidating experiences"""
    similarity_threshold: float = Field(default=0.8, ge=0.5, le=1.0, description="Similarity threshold for merging")
    dry_run: bool = Field(default=True, description="Preview consolidation without making changes")


class ExperienceConsolidateOutput(BaseModel):
    """Output schema for consolidating experiences"""
    consolidated_count: int = Field(..., description="Number of experiences consolidated")
    merged_groups: List[Dict[str, Any]] = Field(..., description="Groups of merged experiences")


class ExperienceConsolidateTool(ToolBase):
    """Tool for consolidating similar experiences"""

    @property
    def name(self) -> str:
        return "experience_consolidate"

    @property
    def description(self) -> str:
        return "Consolidate similar experiences into unified patterns."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ExperienceConsolidateInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ExperienceConsolidateOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return True  # Consolidation modifies multiple experiences

    @property
    def category(self) -> str:
        return "experience"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Consolidate similar experiences in database"""
        similarity_threshold = input_data.get("similarity_threshold", 0.8)
        dry_run = input_data.get("dry_run", True)

        try:
            consolidated_count = 0
            merged_groups = []

            # In production: Find similar experiences and consolidate
            # Use text similarity (Levenshtein, cosine, etc.) to find duplicates
            # Merge them into single consolidated experience with combined stats

            logger.info(f"Consolidated {consolidated_count} experiences (dry_run={dry_run})")

            return self.create_result(
                success=True,
                result_data={
                    "consolidated_count": consolidated_count,
                    "merged_groups": merged_groups,
                },
                output_text=f"{'Would consolidate' if dry_run else 'Consolidated'} {consolidated_count} experiences",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to consolidate experiences: {str(e)}",
            )
