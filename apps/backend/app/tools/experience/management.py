"""
JARV Backend - Experience Management Tools

Tools for managing experience data: export, import, analysis, visualization, pruning, consolidation.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import logging
import json
import csv
import io
from difflib import SequenceMatcher
from uuid import UUID, uuid4
from sqlalchemy import select

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.tools.memory.storage import _memory_scope
from app.models.self_evolution import ExperienceRecord

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
            db, agent_id = await _memory_scope(context)
            records = (await db.execute(select(ExperienceRecord).where(
                ExperienceRecord.agent_id == agent_id,
                ExperienceRecord.is_active.is_(True),
            ))).scalars().all()
            if experience_type:
                records = [record for record in records if record.experience_type == experience_type]
            if outcome:
                records = [record for record in records if record.outcome == outcome]
            if min_confidence is not None:
                records = [record for record in records if record.confidence_score >= min_confidence]
            experiences = [{
                "id": str(record.id), "experience_type": record.experience_type,
                "title": record.title, "description": record.description,
                "situation": record.situation, "action_taken": record.action_taken,
                "result": record.result, "outcome": record.outcome,
                "lesson_learned": record.lesson_learned,
                "applicable_contexts": record.applicable_contexts,
                "confidence_score": record.confidence_score,
                "times_applied": record.times_applied, "success_rate": record.success_rate,
                "is_validated": record.is_validated,
                "created_at": record.created_at.isoformat(),
            } for record in records]

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
            if merge_strategy not in ("skip", "overwrite", "create_new"):
                return self.create_result(success=False, error_message="Invalid merge strategy")
            db, agent_id = await _memory_scope(context)
            for item in experiences_data:
                try:
                    if not isinstance(item, dict):
                        raise ValueError("Entry must be an object")
                    required = ("title", "situation", "action_taken", "result", "lesson_learned")
                    missing = [field for field in required if not item.get(field)]
                    if missing and validate_imports:
                        raise ValueError(f"Missing required fields: {', '.join(missing)}")
                    record_id = UUID(str(item["id"])) if item.get("id") else None
                    existing = None
                    if record_id is not None and merge_strategy != "create_new":
                        existing = (await db.execute(select(ExperienceRecord).where(
                            ExperienceRecord.id == record_id,
                            ExperienceRecord.agent_id == agent_id,
                        ))).scalar_one_or_none()
                    if existing is not None and merge_strategy == "skip":
                        skipped_count += 1
                        continue
                    if existing is not None and merge_strategy == "overwrite":
                        existing.title = item["title"]
                        existing.description = item.get("description", item["lesson_learned"])
                        existing.situation = item["situation"]
                        existing.action_taken = item["action_taken"]
                        existing.result = item["result"]
                        existing.lesson_learned = item["lesson_learned"]
                        existing.is_validated = False
                        existing.meta_data = {"provenance": "imported_unvalidated"}
                        overwritten_count += 1
                        continue
                    db.add(ExperienceRecord(
                        id=uuid4(), agent_id=agent_id, session_id=context.session_id,
                        task_id=context.task_id,
                        experience_type=str(item.get("experience_type", "imported"))[:50],
                        title=item.get("title", "Imported experience"),
                        description=item.get("description", item.get("lesson_learned", "Imported")),
                        situation=item.get("situation", "Imported context"),
                        action_taken=item.get("action_taken", "Imported action"),
                        result=item.get("result", "Imported result"),
                        outcome=str(item.get("outcome", "unknown"))[:50],
                        lesson_learned=item.get("lesson_learned", "Imported lesson"),
                        applicable_contexts=item.get("applicable_contexts", []),
                        confidence_score=max(0.0, min(1.0, float(item.get("confidence_score", 0.5)))),
                        times_applied=0, success_rate=None,
                        is_validated=False, is_active=True,
                        meta_data={"provenance": "imported_unvalidated"},
                    ))
                    imported_count += 1
                except Exception as exc:
                    errors.append(f"Experience {item.get('id', 'unknown') if isinstance(item, dict) else 'unknown'}: {exc}")
            await db.flush()

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
            db, agent_id = await _memory_scope(context)
            records = (await db.execute(select(ExperienceRecord).where(
                ExperienceRecord.agent_id == agent_id,
                ExperienceRecord.is_active.is_(True),
            ))).scalars().all()
            analysis = {
                "total_experiences": len(records),
                "by_type": {},
                "by_outcome": {},
                "average_confidence": 0.0,
                "average_success_rate": 0.0,
                "most_successful_patterns": [],
                "most_applied_patterns": [],
                "recommendations": [],
            }

            confidences = []
            success_rates = []
            for record in records:
                analysis["by_type"][record.experience_type] = analysis["by_type"].get(record.experience_type, 0) + 1
                analysis["by_outcome"][record.outcome] = analysis["by_outcome"].get(record.outcome, 0) + 1
                confidences.append(record.confidence_score)
                if record.success_rate is not None:
                    success_rates.append(record.success_rate)
            analysis["average_confidence"] = sum(confidences) / len(confidences) if confidences else 0.0
            analysis["average_success_rate"] = sum(success_rates) / len(success_rates) if success_rates else 0.0
            analysis["most_successful_patterns"] = [
                {"id": str(record.id), "title": record.title, "success_rate": record.success_rate,
                 "validated": record.is_validated}
                for record in sorted(
                    [item for item in records if item.success_rate is not None and item.is_validated],
                    key=lambda item: item.success_rate, reverse=True)[:10]
            ]
            analysis["most_applied_patterns"] = [
                {"id": str(record.id), "title": record.title, "times_applied": record.times_applied}
                for record in sorted(records, key=lambda item: item.times_applied, reverse=True)[:10]
            ]
            analysis["recommendations"] = (
                [] if analysis["most_successful_patterns"] else
                ["No verified experience outcomes are available for recommendations."]
            )

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
            db, agent_id = await _memory_scope(context)
            stmt = select(ExperienceRecord).where(
                ExperienceRecord.agent_id == agent_id,
                ExperienceRecord.is_active.is_(True),
            )
            if filters.get("experience_type"):
                stmt = stmt.where(ExperienceRecord.experience_type == filters["experience_type"])
            if filters.get("outcome"):
                stmt = stmt.where(ExperienceRecord.outcome == filters["outcome"])
            records = (await db.execute(stmt)).scalars().all()
            if viz_type == "timeline":
                by_day = {}
                for record in records:
                    day = record.created_at.date().isoformat()
                    by_day[day] = by_day.get(day, 0) + 1
                visualization_data = {"by_day": dict(sorted(by_day.items()))}
            elif viz_type == "success_rate":
                groups = {}
                for record in records:
                    if not record.is_validated or record.success_rate is None:
                        continue
                    row = groups.setdefault(record.experience_type, {"weighted_sum": 0.0, "count": 0})
                    weight = max(1, record.times_applied)
                    row["weighted_sum"] += record.success_rate * weight
                    row["count"] += weight
                visualization_data = {
                    "by_type": {key: {"success_rate": value["weighted_sum"] / value["count"],
                                      "verified_applications": value["count"]}
                                for key, value in groups.items()}
                }
            elif viz_type == "distribution":
                by_outcome, by_type = {}, {}
                for record in records:
                    by_outcome[record.outcome] = by_outcome.get(record.outcome, 0) + 1
                    by_type[record.experience_type] = by_type.get(record.experience_type, 0) + 1
                visualization_data = {"by_outcome": by_outcome, "by_type": by_type}
            elif viz_type == "network":
                context_counts = {}
                for record in records:
                    for item in record.applicable_contexts or []:
                        context_counts[item] = context_counts.get(item, 0) + 1
                visualization_data = {"context_frequency": context_counts}
            else:
                return self.create_result(success=False, error_message="Unsupported visualization type")
            data_points = sum(len(value) for value in visualization_data.values())

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
            db, agent_id = await _memory_scope(context)
            if (max_age_days is None and min_confidence is None and max_failure_rate is None
                    and not inactive_only):
                return self.create_result(success=False, error_message="At least one pruning criterion is required")
            stmt = select(ExperienceRecord).where(ExperienceRecord.agent_id == agent_id)
            if inactive_only:
                stmt = stmt.where(ExperienceRecord.is_active.is_(False))
            records = (await db.execute(stmt)).scalars().all()
            cutoff = datetime.utcnow() - timedelta(days=max_age_days) if max_age_days else None
            candidates = []
            for record in records:
                matches = []
                if cutoff:
                    matches.append(record.created_at.replace(tzinfo=None) < cutoff)
                if min_confidence is not None:
                    matches.append(record.confidence_score < min_confidence)
                if max_failure_rate is not None and record.success_rate is not None:
                    matches.append((1.0 - record.success_rate) > max_failure_rate)
                if inactive_only:
                    matches.append(not record.is_active)
                if matches and any(matches):
                    candidates.append(record)
            would_prune_count = len(candidates)
            actually_pruned_count = 0
            pruned_ids = [str(record.id) for record in candidates]
            if not dry_run:
                if not self._has_approval(context):
                    return self.create_result(success=False, requires_approval=True,
                                              error_message="Pruning requires an explicit approved execution context")
                for record in candidates:
                    await db.delete(record)
                actually_pruned_count = len(candidates)
                await db.flush()

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
            db, agent_id = await _memory_scope(context)
            records = (await db.execute(select(ExperienceRecord).where(
                ExperienceRecord.agent_id == agent_id,
                ExperienceRecord.is_active.is_(True),
            ))).scalars().all()
            groups = []
            assigned = set()
            for index, first in enumerate(records):
                if first.id in assigned:
                    continue
                group = [first]
                for second in records[index + 1:]:
                    if second.id in assigned:
                        continue
                    same_evidence = (
                        first.experience_type == second.experience_type
                        and first.outcome == second.outcome
                        and first.is_validated == second.is_validated
                    )
                    similarity = SequenceMatcher(
                        None, first.lesson_learned.lower(), second.lesson_learned.lower()).ratio()
                    if same_evidence and similarity >= similarity_threshold:
                        group.append(second)
                        assigned.add(second.id)
                if len(group) > 1:
                    assigned.add(first.id)
                    groups.append(group)
            merged_groups = [[str(record.id) for record in group] for group in groups]
            consolidated_count = sum(len(group) - 1 for group in groups)
            if not dry_run and consolidated_count:
                if not self._has_approval(context):
                    return self.create_result(success=False, requires_approval=True,
                                              error_message="Consolidation requires an explicit approved execution context")
                for group in groups:
                    primary = group[0]
                    for duplicate in group[1:]:
                        primary.applicable_contexts = list(dict.fromkeys(
                            (primary.applicable_contexts or []) + (duplicate.applicable_contexts or [])))
                        primary.times_applied += duplicate.times_applied
                        if primary.success_rate is not None and duplicate.success_rate is not None:
                            left_count = max(1, primary.times_applied - duplicate.times_applied)
                            total = left_count + max(1, duplicate.times_applied)
                            primary.success_rate = (
                                primary.success_rate * left_count
                                + duplicate.success_rate * max(1, duplicate.times_applied)
                            ) / total
                        duplicate.is_active = False
                        duplicate.meta_data = {**(duplicate.meta_data or {}),
                                               "consolidated_into": str(primary.id)}
                await db.flush()

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
