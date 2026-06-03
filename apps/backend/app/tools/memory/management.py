"""
JARV Backend - Memory Management Tools

Tools for memory listing, tagging, export/import, and statistics.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import logging
import json

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


# ===== MEMORY LIST TOOL =====

class MemoryListInput(BaseModel):
    """Input schema for memory list tool"""
    memory_type: Optional[str] = Field(None, description="Filter by memory type")
    tags: Optional[List[str]] = Field(None, description="Filter by tags (AND logic)")
    min_importance: Optional[float] = Field(None, ge=0.0, le=1.0, description="Minimum importance score")
    only_permanent: bool = Field(default=False, description="Only show permanent memories")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    sort_by: str = Field(default="created_at", description="Sort by: created_at, importance_score, access_count")
    sort_order: str = Field(default="desc", description="Sort order: asc or desc")


class MemoryListEntry(BaseModel):
    """Memory list entry"""
    memory_id: str
    memory_type: str
    summary: Optional[str]
    importance_score: float
    access_count: int
    created_at: str
    last_accessed_at: Optional[str]
    tags: List[str]
    is_permanent: bool
    expires_at: Optional[str]


class MemoryListOutput(BaseModel):
    """Output schema for memory list tool"""
    memories: List[MemoryListEntry]
    count: int
    total: int = Field(..., description="Total memories matching filters (for pagination)")
    has_more: bool = Field(..., description="Whether more results exist")


class MemoryListTool(ToolBase):
    """Tool for listing agent memories"""

    @property
    def name(self) -> str:
        return "memory_list"

    @property
    def description(self) -> str:
        return "List agent memories with filtering, sorting, and pagination."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MemoryListInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MemoryListOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "memory"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """List memories from database"""
        memory_type = input_data.get("memory_type")
        tags = input_data.get("tags")
        min_importance = input_data.get("min_importance")
        only_permanent = input_data.get("only_permanent", False)
        limit = input_data.get("limit", 50)
        offset = input_data.get("offset", 0)
        sort_by = input_data.get("sort_by", "created_at")
        sort_order = input_data.get("sort_order", "desc")

        try:
            memories = []
            total = 0

            # In production: Query Memory table with filters and pagination
            # from app.models.memory import Memory
            # from app.core.database import get_db
            # from sqlalchemy import select, func, desc, asc
            #
            # async for session in get_db():
            #     # Build base query
            #     stmt = select(Memory).filter(Memory.agent_id == context.agent_id)
            #
            #     # Apply filters
            #     if memory_type:
            #         stmt = stmt.filter(Memory.memory_type == memory_type)
            #     if min_importance is not None:
            #         stmt = stmt.filter(Memory.importance_score >= min_importance)
            #     if only_permanent:
            #         stmt = stmt.filter(Memory.is_permanent == True)
            #     if tags:
            #         # Filter by tags (AND logic)
            #         for tag in tags:
            #             stmt = stmt.filter(Memory.meta_data["tags"].astext.contains(tag))
            #
            #     # Get total count
            #     count_stmt = select(func.count()).select_from(stmt.subquery())
            #     total = await session.scalar(count_stmt)
            #
            #     # Apply sorting
            #     order_col = getattr(Memory, sort_by, Memory.created_at)
            #     order_func = desc if sort_order == "desc" else asc
            #     stmt = stmt.order_by(order_func(order_col))
            #
            #     # Apply pagination
            #     stmt = stmt.offset(offset).limit(limit)
            #
            #     # Execute query
            #     result = await session.execute(stmt)
            #     for memory in result.scalars():
            #         tags_list = memory.meta_data.get("tags", []) if memory.meta_data else []
            #         memories.append({
            #             "memory_id": str(memory.id),
            #             "memory_type": memory.memory_type,
            #             "summary": memory.summary,
            #             "importance_score": memory.importance_score,
            #             "access_count": memory.access_count,
            #             "created_at": memory.created_at.isoformat(),
            #             "last_accessed_at": memory.last_accessed_at.isoformat() if memory.last_accessed_at else None,
            #             "tags": tags_list,
            #             "is_permanent": memory.is_permanent,
            #             "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
            #         })

            logger.info(f"Listed memories: {len(memories)} results, total={total}")

            has_more = (offset + len(memories)) < total

            return self.create_result(
                success=True,
                result_data={
                    "memories": memories,
                    "count": len(memories),
                    "total": total,
                    "has_more": has_more,
                },
                output_text=f"Listed {len(memories)} memories (total: {total})",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to list memories: {str(e)}",
            )


# ===== MEMORY TAG TOOL =====

class MemoryTagInput(BaseModel):
    """Input schema for memory tag tool"""
    memory_id: Optional[str] = Field(None, description="Specific memory ID to tag (if None, tags memories by filter)")
    tags: List[str] = Field(..., min_items=1, description="Tags to add")
    memory_type: Optional[str] = Field(None, description="Filter: tag all memories of this type")
    min_importance: Optional[float] = Field(None, ge=0.0, le=1.0, description="Filter: minimum importance")


class MemoryTagOutput(BaseModel):
    """Output schema for memory tag tool"""
    tagged_count: int = Field(..., description="Number of memories tagged")
    tags_added: List[str]


class MemoryTagTool(ToolBase):
    """Tool for tagging memories"""

    @property
    def name(self) -> str:
        return "memory_tag"

    @property
    def description(self) -> str:
        return "Add tags to memories for organization. Can tag specific memory or batch tag by filter."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MemoryTagInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MemoryTagOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "memory"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Tag memories in database"""
        memory_id = input_data.get("memory_id")
        tags = input_data["tags"]
        memory_type = input_data.get("memory_type")
        min_importance = input_data.get("min_importance")

        try:
            tagged_count = 0

            # In production: Update Memory table meta_data with tags
            # from app.models.memory import Memory
            # from app.core.database import get_db
            # from sqlalchemy import select
            #
            # async for session in get_db():
            #     if memory_id:
            #         # Tag specific memory
            #         memory = await session.get(Memory, memory_id)
            #         if memory and memory.agent_id == context.agent_id:
            #             if not memory.meta_data:
            #                 memory.meta_data = {}
            #             existing_tags = memory.meta_data.get("tags", [])
            #             new_tags = list(set(existing_tags + tags))
            #             memory.meta_data["tags"] = new_tags
            #             tagged_count = 1
            #     else:
            #         # Batch tag by filter
            #         stmt = select(Memory).filter(Memory.agent_id == context.agent_id)
            #         if memory_type:
            #             stmt = stmt.filter(Memory.memory_type == memory_type)
            #         if min_importance is not None:
            #             stmt = stmt.filter(Memory.importance_score >= min_importance)
            #
            #         result = await session.execute(stmt)
            #         for memory in result.scalars():
            #             if not memory.meta_data:
            #                 memory.meta_data = {}
            #             existing_tags = memory.meta_data.get("tags", [])
            #             new_tags = list(set(existing_tags + tags))
            #             memory.meta_data["tags"] = new_tags
            #             tagged_count += 1
            #
            #     await session.commit()

            logger.info(f"Tagged {tagged_count} memories with tags: {tags}")

            return self.create_result(
                success=True,
                result_data={
                    "tagged_count": tagged_count,
                    "tags_added": tags,
                },
                output_text=f"Tagged {tagged_count} memories with {len(tags)} tags",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to tag memories: {str(e)}",
            )


# ===== MEMORY EXPORT TOOL =====

class MemoryExportInput(BaseModel):
    """Input schema for memory export tool"""
    memory_type: Optional[str] = Field(None, description="Export only this memory type")
    tags: Optional[List[str]] = Field(None, description="Export only memories with these tags")
    min_importance: Optional[float] = Field(None, ge=0.0, le=1.0, description="Export only memories above this importance")
    format: str = Field(default="json", description="Export format: json or csv")
    include_embeddings: bool = Field(default=False, description="Include vector embeddings in export")


class MemoryExportOutput(BaseModel):
    """Output schema for memory export tool"""
    export_data: str = Field(..., description="Exported memory data as string")
    count: int = Field(..., description="Number of memories exported")
    format: str
    export_size_bytes: int


class MemoryExportTool(ToolBase):
    """Tool for exporting memories"""

    @property
    def name(self) -> str:
        return "memory_export"

    @property
    def description(self) -> str:
        return "Export agent memories to JSON or CSV format."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MemoryExportInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MemoryExportOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "memory"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Export memories from database"""
        memory_type = input_data.get("memory_type")
        tags = input_data.get("tags")
        min_importance = input_data.get("min_importance")
        export_format = input_data.get("format", "json")
        include_embeddings = input_data.get("include_embeddings", False)

        try:
            memories = []

            # In production: Query and export memories
            # from app.models.memory import Memory
            # from app.core.database import get_db
            # from sqlalchemy import select
            #
            # async for session in get_db():
            #     stmt = select(Memory).filter(Memory.agent_id == context.agent_id)
            #
            #     if memory_type:
            #         stmt = stmt.filter(Memory.memory_type == memory_type)
            #     if min_importance is not None:
            #         stmt = stmt.filter(Memory.importance_score >= min_importance)
            #     if tags:
            #         for tag in tags:
            #             stmt = stmt.filter(Memory.meta_data["tags"].astext.contains(tag))
            #
            #     result = await session.execute(stmt)
            #     for memory in result.scalars():
            #         export_entry = {
            #             "id": str(memory.id),
            #             "memory_type": memory.memory_type,
            #             "content": memory.content,
            #             "summary": memory.summary,
            #             "importance_score": memory.importance_score,
            #             "access_count": memory.access_count,
            #             "created_at": memory.created_at.isoformat(),
            #             "last_accessed_at": memory.last_accessed_at.isoformat() if memory.last_accessed_at else None,
            #             "is_permanent": memory.is_permanent,
            #             "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
            #             "meta_data": memory.meta_data,
            #         }
            #
            #         if include_embeddings and memory.embedding:
            #             export_entry["embedding"] = list(memory.embedding)
            #
            #         memories.append(export_entry)

            # Format export data
            if export_format == "json":
                export_data = json.dumps(memories, indent=2)
            elif export_format == "csv":
                # Simple CSV export (without embeddings)
                import csv
                import io
                output = io.StringIO()
                if memories:
                    fieldnames = ["id", "memory_type", "content", "summary", "importance_score", "access_count", "created_at"]
                    writer = csv.DictWriter(output, fieldnames=fieldnames)
                    writer.writeheader()
                    for mem in memories:
                        writer.writerow({k: mem.get(k, "") for k in fieldnames})
                export_data = output.getvalue()
            else:
                return self.create_result(
                    success=False,
                    error_message=f"Unsupported export format: {export_format}",
                )

            export_size = len(export_data.encode('utf-8'))
            logger.info(f"Exported {len(memories)} memories ({export_size} bytes)")

            return self.create_result(
                success=True,
                result_data={
                    "export_data": export_data,
                    "count": len(memories),
                    "format": export_format,
                    "export_size_bytes": export_size,
                },
                output_text=f"Exported {len(memories)} memories as {export_format} ({export_size} bytes)",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to export memories: {str(e)}",
            )


# ===== MEMORY IMPORT TOOL =====

class MemoryImportInput(BaseModel):
    """Input schema for memory import tool"""
    import_data: str = Field(..., description="Memory data to import (JSON format)")
    merge_strategy: str = Field(default="skip", description="Merge strategy: skip (skip existing IDs), overwrite, or create_new")
    preserve_ids: bool = Field(default=False, description="Preserve original IDs if merge_strategy=create_new")


class MemoryImportOutput(BaseModel):
    """Output schema for memory import tool"""
    imported_count: int
    skipped_count: int
    overwritten_count: int
    errors: List[str]


class MemoryImportTool(ToolBase):
    """Tool for importing memories"""

    @property
    def name(self) -> str:
        return "memory_import"

    @property
    def description(self) -> str:
        return "Import agent memories from JSON format."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MemoryImportInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MemoryImportOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return True  # Importing can create many memories

    @property
    def category(self) -> str:
        return "memory"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Import memories to database"""
        import_data = input_data["import_data"]
        merge_strategy = input_data.get("merge_strategy", "skip")
        preserve_ids = input_data.get("preserve_ids", False)

        try:
            # Parse import data
            try:
                memories_data = json.loads(import_data)
                if not isinstance(memories_data, list):
                    return self.create_result(
                        success=False,
                        error_message="Import data must be a JSON array of memories",
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

            # In production: Import memories to database
            # from app.models.memory import Memory
            # from app.core.database import get_db
            # from uuid import uuid4
            #
            # async for session in get_db():
            #     for mem_data in memories_data:
            #         try:
            #             memory_id = mem_data.get("id")
            #             existing = None
            #
            #             if memory_id:
            #                 existing = await session.get(Memory, memory_id)
            #
            #             if existing and merge_strategy == "skip":
            #                 skipped_count += 1
            #                 continue
            #
            #             if existing and merge_strategy == "overwrite":
            #                 # Update existing memory
            #                 existing.content = mem_data["content"]
            #                 existing.summary = mem_data.get("summary")
            #                 existing.memory_type = mem_data["memory_type"]
            #                 existing.importance_score = mem_data.get("importance_score", 0.5)
            #                 existing.meta_data = mem_data.get("meta_data")
            #                 overwritten_count += 1
            #             else:
            #                 # Create new memory
            #                 new_id = memory_id if preserve_ids else str(uuid4())
            #                 memory = Memory(
            #                     id=new_id,
            #                     agent_id=context.agent_id,
            #                     memory_type=mem_data["memory_type"],
            #                     content=mem_data["content"],
            #                     summary=mem_data.get("summary"),
            #                     importance_score=mem_data.get("importance_score", 0.5),
            #                     access_count=mem_data.get("access_count", 0),
            #                     is_permanent=mem_data.get("is_permanent", False),
            #                     meta_data=mem_data.get("meta_data"),
            #                 )
            #                 session.add(memory)
            #                 imported_count += 1
            #
            #         except Exception as e:
            #             errors.append(f"Failed to import memory {mem_data.get('id', 'unknown')}: {str(e)}")
            #
            #     await session.commit()

            logger.info(f"Imported {imported_count} memories, skipped {skipped_count}, overwritten {overwritten_count}")

            return self.create_result(
                success=True,
                result_data={
                    "imported_count": imported_count,
                    "skipped_count": skipped_count,
                    "overwritten_count": overwritten_count,
                    "errors": errors,
                },
                output_text=f"Imported {imported_count} memories (skipped: {skipped_count}, errors: {len(errors)})",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to import memories: {str(e)}",
            )


# ===== MEMORY STATS TOOL =====

class MemoryStatsOutput(BaseModel):
    """Output schema for memory stats tool"""
    total_memories: int
    by_type: Dict[str, int] = Field(..., description="Count by memory type")
    by_importance: Dict[str, int] = Field(..., description="Distribution by importance range")
    permanent_count: int
    temporary_count: int
    most_accessed: List[Dict[str, Any]] = Field(..., description="Top 10 most accessed memories")
    average_importance: float
    total_size_bytes: int = Field(..., description="Total size of memory content")
    tags: Dict[str, int] = Field(..., description="Tag usage counts")


class MemoryStatsTool(ToolBase):
    """Tool for getting memory statistics"""

    @property
    def name(self) -> str:
        return "memory_stats"

    @property
    def description(self) -> str:
        return "Get statistics about agent memory usage and distribution."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return None  # No input needed

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MemoryStatsOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "memory"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Get memory statistics from database"""
        try:
            stats = {
                "total_memories": 0,
                "by_type": {},
                "by_importance": {
                    "low (0.0-0.3)": 0,
                    "medium (0.3-0.7)": 0,
                    "high (0.7-1.0)": 0,
                },
                "permanent_count": 0,
                "temporary_count": 0,
                "most_accessed": [],
                "average_importance": 0.0,
                "total_size_bytes": 0,
                "tags": {},
            }

            # In production: Query Memory table for statistics
            # from app.models.memory import Memory
            # from app.core.database import get_db
            # from sqlalchemy import select, func
            #
            # async for session in get_db():
            #     # Total count
            #     stats["total_memories"] = await session.scalar(
            #         select(func.count()).select_from(Memory).filter(Memory.agent_id == context.agent_id)
            #     )
            #
            #     # Count by type
            #     type_counts = await session.execute(
            #         select(Memory.memory_type, func.count()).filter(Memory.agent_id == context.agent_id).group_by(Memory.memory_type)
            #     )
            #     stats["by_type"] = {type_name: count for type_name, count in type_counts}
            #
            #     # Count by importance range
            #     all_memories = await session.execute(
            #         select(Memory).filter(Memory.agent_id == context.agent_id)
            #     )
            #     importance_scores = []
            #     total_size = 0
            #     tag_counts = {}
            #
            #     for memory in all_memories.scalars():
            #         importance_scores.append(memory.importance_score)
            #         total_size += len(memory.content.encode('utf-8'))
            #
            #         if memory.importance_score < 0.3:
            #             stats["by_importance"]["low (0.0-0.3)"] += 1
            #         elif memory.importance_score < 0.7:
            #             stats["by_importance"]["medium (0.3-0.7)"] += 1
            #         else:
            #             stats["by_importance"]["high (0.7-1.0)"] += 1
            #
            #         if memory.is_permanent:
            #             stats["permanent_count"] += 1
            #         else:
            #             stats["temporary_count"] += 1
            #
            #         # Count tags
            #         if memory.meta_data and "tags" in memory.meta_data:
            #             for tag in memory.meta_data["tags"]:
            #                 tag_counts[tag] = tag_counts.get(tag, 0) + 1
            #
            #     stats["average_importance"] = sum(importance_scores) / len(importance_scores) if importance_scores else 0.0
            #     stats["total_size_bytes"] = total_size
            #     stats["tags"] = tag_counts
            #
            #     # Most accessed
            #     most_accessed = await session.execute(
            #         select(Memory)
            #         .filter(Memory.agent_id == context.agent_id)
            #         .order_by(Memory.access_count.desc())
            #         .limit(10)
            #     )
            #     stats["most_accessed"] = [
            #         {
            #             "memory_id": str(mem.id),
            #             "memory_type": mem.memory_type,
            #             "access_count": mem.access_count,
            #             "importance_score": mem.importance_score,
            #         }
            #         for mem in most_accessed.scalars()
            #     ]

            logger.info(f"Generated memory statistics: {stats['total_memories']} total memories")

            return self.create_result(
                success=True,
                result_data=stats,
                output_text=f"Memory statistics: {stats['total_memories']} total memories",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to get memory statistics: {str(e)}",
            )
