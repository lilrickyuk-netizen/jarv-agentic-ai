"""
JARV Backend - Memory Storage Tools

Real memory operations with database integration.

Memory is stored through ``app.core.jarv_memory.memory_service``: rows are
workspace-isolated, embedded on write, and searched by semantic similarity plus
keyword overlap. Embeddings use the built-in local embedder by default (no key
needed); set EMBEDDING_PROVIDER=openai with OPENAI_API_KEY for OpenAI vectors.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone
import logging
import os
from uuid import UUID, uuid4
from sqlalchemy import or_, select

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.models.agent import Agent
from app.models.memory import Memory
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


def is_embedding_enabled() -> bool:
    """Embeddings are always produced (local embedder when no provider key is set)."""
    return True


async def _memory_scope(context: ToolContext):
    if context.db_session is None:
        raise ValueError("Memory database session is unavailable")
    if context.user_id is None or context.workspace_id is None:
        raise PermissionError("Authenticated user and workspace context are required")
    db = context.db_session
    owner = (await db.execute(select(Workspace.id).where(
        Workspace.id == context.workspace_id,
        Workspace.owner_id == context.user_id,
        Workspace.is_active.is_(True),
    ))).scalar_one_or_none()
    if owner is None:
        raise PermissionError("Workspace is outside the authenticated user's scope")
    agent_id = context.agent_id
    if agent_id is None:
        raise PermissionError("Agent identity is required for memory access")
    agent = (await db.execute(select(Agent.id).where(
        Agent.id == agent_id,
        Agent.workspace_id == context.workspace_id,
        Agent.is_active.is_(True),
    ))).scalar_one_or_none()
    if agent is None:
        raise PermissionError("Agent identity is not active in the workspace")
    return db, agent_id


# ===== MEMORY STORE TOOL =====

class MemoryStoreInput(BaseModel):
    """Input schema for memory store tool"""
    content: str = Field(..., min_length=1, max_length=50000, description="Memory content to store")
    memory_type: str = Field(..., description="Memory type: fact, task, learning, conversation, decision, etc.")
    summary: Optional[str] = Field(None, max_length=1000, description="Brief summary of content")
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Importance score (0.0 to 1.0)")
    is_permanent: bool = Field(default=False, description="Whether memory should never expire")
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650, description="Days until expiration (if not permanent)")
    tags: Optional[List[str]] = Field(None, description="Tags for organization")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context metadata")


class MemoryStoreOutput(BaseModel):
    """Output schema for memory store tool"""
    memory_id: str
    content_preview: str = Field(..., description="First 100 characters of content")
    memory_type: str
    importance_score: float
    has_embedding: bool = Field(..., description="Whether vector embedding was created")
    expires_at: Optional[str]


class MemoryStoreTool(ToolBase):
    """Tool for storing information in agent memory"""

    @property
    def name(self) -> str:
        return "memory_store"

    @property
    def description(self) -> str:
        return "Store information in agent memory with optional vector embeddings for semantic search."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MemoryStoreInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MemoryStoreOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return False  # Storing memories is safe

    @property
    def category(self) -> str:
        return "memory"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Store memory in database"""
        content = input_data["content"]
        memory_type = input_data["memory_type"]
        summary = input_data.get("summary")
        importance_score = input_data.get("importance_score", 0.5)
        is_permanent = input_data.get("is_permanent", False)
        expires_in_days = input_data.get("expires_in_days")
        tags = input_data.get("tags") or []
        additional_context = input_data.get("context") or {}

        try:
            db, agent_id = await _memory_scope(context)

            # Calculate expiration
            expires_at = None
            if not is_permanent and expires_in_days:
                expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

            # Prepare metadata with tags
            meta_data = {
                "tags": tags,
                "created_by_tool": "memory_store",
            }

            from app.core.jarv_memory import memory_service

            record = await memory_service.add(
                db, content=content, memory_type=memory_type,
                workspace_id=context.workspace_id, task_id=context.task_id,
                importance=importance_score, summary=summary, meta=meta_data,
                permanent=is_permanent, agent_id=agent_id, expires_at=expires_at,
                session_id=context.session_id,
            )
            record.context = {**additional_context, "workspace_id": str(context.workspace_id)}
            record.updated_at = datetime.now(timezone.utc)
            await db.flush()
            has_embedding = record.embedding is not None
            memory_id = str(record.id)

            logger.info(f"Stored memory: {memory_id}, type={memory_type}, importance={importance_score}")

            content_preview = content[:100] + "..." if len(content) > 100 else content

            return self.create_result(
                success=True,
                result_data={
                    "memory_id": memory_id,
                    "content_preview": content_preview,
                    "memory_type": memory_type,
                    "importance_score": importance_score,
                    "has_embedding": has_embedding,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
                output_text=f"Stored memory '{memory_type}' with ID {memory_id}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to store memory: {str(e)}",
            )


# ===== MEMORY RETRIEVE TOOL =====

class MemoryRetrieveInput(BaseModel):
    """Input schema for memory retrieve tool"""
    memory_id: str = Field(..., description="Memory ID to retrieve")


class MemoryRetrieveOutput(BaseModel):
    """Output schema for memory retrieve tool"""
    memory_id: str
    content: str
    summary: Optional[str]
    memory_type: str
    importance_score: float
    access_count: int
    created_at: str
    last_accessed_at: Optional[str]
    tags: List[str]
    is_permanent: bool
    expires_at: Optional[str]


class MemoryRetrieveTool(ToolBase):
    """Tool for retrieving specific memory by ID"""

    @property
    def name(self) -> str:
        return "memory_retrieve"

    @property
    def description(self) -> str:
        return "Retrieve specific memory by ID from agent memory."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MemoryRetrieveInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MemoryRetrieveOutput

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
        """Retrieve memory from database"""
        memory_id = input_data["memory_id"]

        try:
            db, agent_id = await _memory_scope(context)
            record = (await db.execute(select(Memory).where(
                Memory.id == UUID(memory_id),
                Memory.agent_id == agent_id,
                Memory.context["workspace_id"].as_string() == str(context.workspace_id),
            ))).scalar_one_or_none()
            if record is None:
                return self.create_result(success=False, error_message="Memory not found in this agent/workspace scope")
            record.access_count += 1
            record.last_accessed_at = datetime.utcnow()
            await db.flush()
            tags = (record.meta_data or {}).get("tags", [])
            return self.create_result(
                success=True,
                result_data={
                    "memory_id": str(record.id), "content": record.content,
                    "summary": record.summary, "memory_type": record.memory_type,
                    "importance_score": record.importance_score,
                    "access_count": record.access_count,
                    "created_at": record.created_at.isoformat(),
                    "last_accessed_at": record.last_accessed_at.isoformat(),
                    "tags": tags, "is_permanent": record.is_permanent,
                    "expires_at": record.expires_at.isoformat() if record.expires_at else None,
                },
                output_text=f"Retrieved memory {record.id}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to retrieve memory: {str(e)}",
            )


# ===== MEMORY SEARCH TOOL =====

class MemorySearchInput(BaseModel):
    """Input schema for memory search tool"""
    query: str = Field(..., min_length=1, description="Search query")
    memory_type: Optional[str] = Field(None, description="Filter by memory type")
    min_importance: Optional[float] = Field(None, ge=0.0, le=1.0, description="Minimum importance score")
    tags: Optional[List[str]] = Field(None, description="Filter by tags (OR logic)")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum results")
    use_semantic_search: bool = Field(default=True, description="Use vector similarity if available")


class MemorySearchResult(BaseModel):
    """Search result entry"""
    memory_id: str
    content: str
    summary: Optional[str]
    memory_type: str
    importance_score: float
    similarity_score: Optional[float] = Field(None, description="Cosine similarity (0-1) if semantic search used")
    created_at: str
    tags: List[str]


class MemorySearchOutput(BaseModel):
    """Output schema for memory search tool"""
    results: List[MemorySearchResult]
    count: int
    search_method: str = Field(..., description="semantic or full_text")


class MemorySearchTool(ToolBase):
    """Tool for searching agent memory"""

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return "Search agent memory using semantic similarity or full-text search."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MemorySearchInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MemorySearchOutput

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
        """Search memory database"""
        query = input_data["query"]
        memory_type = input_data.get("memory_type")
        min_importance = input_data.get("min_importance")
        tags = input_data.get("tags")
        limit = input_data.get("limit", 10)
        use_semantic = input_data.get("use_semantic_search", True)

        try:
            db, agent_id = await _memory_scope(context)
            from app.core.jarv_memory import memory_service

            # All agents in the workspace share its memory; other workspaces are never visible.
            hits = await memory_service.search_scored(
                db, query, limit=50, workspace_id=context.workspace_id,
                include_global=False, min_score=0.0 if not use_semantic else 0.12, touch=False,
            )
            if not use_semantic:
                hits = [hit for hit in hits if hit.keyword > 0]
            if memory_type:
                hits = [hit for hit in hits if hit.memory.memory_type == memory_type]
            if min_importance is not None:
                hits = [hit for hit in hits if hit.memory.importance_score >= min_importance]
            if tags:
                required = set(tags)
                hits = [hit for hit in hits
                        if required.issubset(set((hit.memory.meta_data or {}).get("tags", [])))]
            hits = hits[:limit]
            now = datetime.utcnow()
            results = []
            for hit in hits:
                record = hit.memory
                record.access_count += 1
                record.last_accessed_at = now
                record.updated_at = now
                results.append({
                    "memory_id": str(record.id), "content": record.content,
                    "summary": record.summary, "memory_type": record.memory_type,
                    "importance_score": record.importance_score,
                    "similarity_score": round(hit.semantic, 4),
                    "created_at": record.created_at.isoformat() if record.created_at else None,
                    "tags": (record.meta_data or {}).get("tags", []),
                })
            if hits:
                await db.flush()
            search_method = "semantic+keyword" if use_semantic else "keyword"

            return self.create_result(
                success=True,
                result_data={
                    "results": results,
                    "count": len(results),
                    "search_method": search_method,
                },
                output_text=f"Found {len(results)} memories using {search_method} search",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to search memories: {str(e)}",
            )


# ===== MEMORY UPDATE TOOL =====

class MemoryUpdateInput(BaseModel):
    """Input schema for memory update tool"""
    memory_id: str = Field(..., description="Memory ID to update")
    content: Optional[str] = Field(None, min_length=1, max_length=50000, description="New content")
    summary: Optional[str] = Field(None, max_length=1000, description="New summary")
    memory_type: Optional[str] = Field(None, description="New memory type")
    importance_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="New importance score")
    add_tags: Optional[List[str]] = Field(None, description="Tags to add")
    remove_tags: Optional[List[str]] = Field(None, description="Tags to remove")


class MemoryUpdateOutput(BaseModel):
    """Output schema for memory update tool"""
    memory_id: str
    updated_fields: List[str]
    regenerated_embedding: bool = Field(..., description="Whether embedding was regenerated")


class MemoryUpdateTool(ToolBase):
    """Tool for updating memory entry"""

    @property
    def name(self) -> str:
        return "memory_update"

    @property
    def description(self) -> str:
        return "Update existing memory entry in agent memory."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MemoryUpdateInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MemoryUpdateOutput

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
        """Update memory in database"""
        memory_id = input_data["memory_id"]

        try:
            updated_fields = []
            regenerated_embedding = False
            db, agent_id = await _memory_scope(context)
            record = (await db.execute(select(Memory).where(
                Memory.id == UUID(memory_id), Memory.agent_id == agent_id,
                Memory.context["workspace_id"].as_string() == str(context.workspace_id),
            ))).scalar_one_or_none()
            if record is None:
                return self.create_result(success=False, error_message="Memory not found in this agent/workspace scope")
            if input_data.get("content") is not None:
                record.content = input_data["content"]
                updated_fields.append("content")
            if input_data.get("summary") is not None:
                record.summary = input_data["summary"]
                updated_fields.append("summary")
            if input_data.get("memory_type") is not None:
                record.memory_type = input_data["memory_type"]
                updated_fields.append("memory_type")
            if input_data.get("importance_score") is not None:
                record.importance_score = input_data["importance_score"]
                updated_fields.append("importance_score")
            if input_data.get("add_tags") or input_data.get("remove_tags"):
                metadata = dict(record.meta_data or {})
                tags = list(metadata.get("tags", []))
                tags = list(dict.fromkeys(tags + (input_data.get("add_tags") or [])))
                remove = set(input_data.get("remove_tags") or [])
                metadata["tags"] = [tag for tag in tags if tag not in remove]
                record.meta_data = metadata
                updated_fields.append("tags")
            await db.flush()

            logger.info(f"Updated memory: {memory_id}, fields={updated_fields}")

            return self.create_result(
                success=True,
                result_data={
                    "memory_id": memory_id,
                    "updated_fields": updated_fields,
                    "regenerated_embedding": regenerated_embedding,
                },
                output_text=f"Updated memory {memory_id} ({len(updated_fields)} fields)",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to update memory: {str(e)}",
            )


# ===== MEMORY DELETE TOOL =====

class MemoryDeleteInput(BaseModel):
    """Input schema for memory delete tool"""
    memory_id: str = Field(..., description="Memory ID to delete")


class MemoryDeleteOutput(BaseModel):
    """Output schema for memory delete tool"""
    memory_id: str
    deleted: bool


class MemoryDeleteTool(ToolBase):
    """Tool for deleting memory entry"""

    @property
    def name(self) -> str:
        return "memory_delete"

    @property
    def description(self) -> str:
        return "Delete memory entry from agent memory."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MemoryDeleteInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MemoryDeleteOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return True  # Deletion requires approval

    @property
    def category(self) -> str:
        return "memory"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Delete memory from database"""
        memory_id = input_data["memory_id"]

        try:
            db, agent_id = await _memory_scope(context)
            record = (await db.execute(select(Memory).where(
                Memory.id == UUID(memory_id), Memory.agent_id == agent_id,
                Memory.context["workspace_id"].as_string() == str(context.workspace_id),
            ))).scalar_one_or_none()
            if record is None:
                return self.create_result(success=False, error_message="Memory not found in this agent/workspace scope")
            await db.delete(record)
            await db.flush()
            logger.info(f"Deleted memory: {memory_id}")

            return self.create_result(
                success=True,
                result_data={
                    "memory_id": memory_id,
                    "deleted": True,
                },
                output_text=f"Deleted memory {memory_id}",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to delete memory: {str(e)}",
            )
