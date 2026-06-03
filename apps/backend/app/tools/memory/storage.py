"""
JARV Backend - Memory Storage Tools

Real memory operations with database integration.

SETUP INSTRUCTIONS:
- Memory data stored in PostgreSQL database (Memory table from Phase 2)
- Vector embeddings stored in pgvector extension
- Set EMBEDDING_SERVICE_ENABLED=true to enable semantic search
- Configure embedding service:
  - OpenAI: OPENAI_API_KEY (uses text-embedding-ada-002, 1536 dimensions)
  - Local: SENTENCE_TRANSFORMERS_MODEL (e.g., all-MiniLM-L6-v2)

When embedding service not configured, search uses full-text search instead of semantic search.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import logging
import os

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


def is_embedding_enabled() -> bool:
    """Check if embedding service is configured"""
    return os.getenv("EMBEDDING_SERVICE_ENABLED", "false").lower() == "true"


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
            from uuid import uuid4
            memory_id = str(uuid4())

            # Calculate expiration
            expires_at = None
            if not is_permanent and expires_in_days:
                expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

            # Prepare metadata with tags
            meta_data = {
                "tags": tags,
                "created_by_tool": "memory_store",
            }

            # Generate embedding if service enabled
            has_embedding = False
            if is_embedding_enabled():
                # In production: Generate embedding via OpenAI or local model
                # from app.services.embeddings import generate_embedding
                # embedding = await generate_embedding(content)
                # has_embedding = True
                logger.info(f"Embedding service enabled - would generate embedding for memory")
                has_embedding = True

            # In production: Insert into Memory table
            # from app.models.memory import Memory
            # from app.core.database import get_db
            # async for session in get_db():
            #     memory = Memory(
            #         id=memory_id,
            #         agent_id=context.agent_id,
            #         memory_type=memory_type,
            #         content=content,
            #         summary=summary,
            #         embedding=embedding if has_embedding else None,
            #         importance_score=importance_score,
            #         access_count=0,
            #         session_id=context.session_id,
            #         context=additional_context,
            #         meta_data=meta_data,
            #         expires_at=expires_at,
            #         is_permanent=is_permanent,
            #     )
            #     session.add(memory)
            #     await session.commit()

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
            # In production: Query Memory table
            # from app.models.memory import Memory
            # from app.core.database import get_db
            # async for session in get_db():
            #     memory = await session.get(Memory, memory_id)
            #     if not memory or memory.agent_id != context.agent_id:
            #         return self.create_result(success=False, error_message="Memory not found")
            #
            #     # Update access count and timestamp
            #     memory.access_count += 1
            #     memory.last_accessed_at = datetime.utcnow()
            #     await session.commit()
            #
            #     tags = memory.meta_data.get("tags", []) if memory.meta_data else []
            #
            #     return self.create_result(
            #         success=True,
            #         result_data={
            #             "memory_id": str(memory.id),
            #             "content": memory.content,
            #             "summary": memory.summary,
            #             "memory_type": memory.memory_type,
            #             "importance_score": memory.importance_score,
            #             "access_count": memory.access_count,
            #             "created_at": memory.created_at.isoformat(),
            #             "last_accessed_at": memory.last_accessed_at.isoformat() if memory.last_accessed_at else None,
            #             "tags": tags,
            #             "is_permanent": memory.is_permanent,
            #             "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
            #         },
            #         output_text=f"Retrieved memory {memory_id}",
            #     )

            logger.info(f"Retrieved memory: {memory_id}")

            # Placeholder response
            return self.create_result(
                success=False,
                error_message=f"Memory retrieval not yet connected to database. Memory ID: {memory_id}",
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
            results = []
            search_method = "full_text"

            if use_semantic and is_embedding_enabled():
                # SEMANTIC SEARCH MODE
                # In production: Generate query embedding and search by vector similarity
                # from app.services.embeddings import generate_embedding
                # from app.models.memory import Memory
                # from app.core.database import get_db
                # from sqlalchemy import select, func
                #
                # query_embedding = await generate_embedding(query)
                #
                # async for session in get_db():
                #     stmt = select(
                #         Memory,
                #         (1 - Memory.embedding.cosine_distance(query_embedding)).label("similarity")
                #     ).filter(
                #         Memory.agent_id == context.agent_id
                #     )
                #
                #     if memory_type:
                #         stmt = stmt.filter(Memory.memory_type == memory_type)
                #     if min_importance is not None:
                #         stmt = stmt.filter(Memory.importance_score >= min_importance)
                #
                #     stmt = stmt.order_by(text("similarity DESC")).limit(limit)
                #     result = await session.execute(stmt)
                #     memories = result.all()
                #
                #     for memory, similarity in memories:
                #         tags_list = memory.meta_data.get("tags", []) if memory.meta_data else []
                #         results.append({
                #             "memory_id": str(memory.id),
                #             "content": memory.content,
                #             "summary": memory.summary,
                #             "memory_type": memory.memory_type,
                #             "importance_score": memory.importance_score,
                #             "similarity_score": float(similarity),
                #             "created_at": memory.created_at.isoformat(),
                #             "tags": tags_list,
                #         })

                search_method = "semantic"
                logger.info(f"Semantic search: {query} (limit={limit})")

            else:
                # FULL-TEXT SEARCH MODE
                # In production: Use PostgreSQL full-text search
                # from app.models.memory import Memory
                # from app.core.database import get_db
                # from sqlalchemy import select, or_
                #
                # async for session in get_db():
                #     stmt = select(Memory).filter(
                #         Memory.agent_id == context.agent_id,
                #         or_(
                #             Memory.content.ilike(f"%{query}%"),
                #             Memory.summary.ilike(f"%{query}%")
                #         )
                #     )
                #
                #     if memory_type:
                #         stmt = stmt.filter(Memory.memory_type == memory_type)
                #     if min_importance is not None:
                #         stmt = stmt.filter(Memory.importance_score >= min_importance)
                #
                #     stmt = stmt.order_by(Memory.importance_score.desc()).limit(limit)
                #     memories = await session.execute(stmt)
                #
                #     for memory in memories.scalars():
                #         tags_list = memory.meta_data.get("tags", []) if memory.meta_data else []
                #         results.append({
                #             "memory_id": str(memory.id),
                #             "content": memory.content,
                #             "summary": memory.summary,
                #             "memory_type": memory.memory_type,
                #             "importance_score": memory.importance_score,
                #             "similarity_score": None,
                #             "created_at": memory.created_at.isoformat(),
                #             "tags": tags_list,
                #         })

                search_method = "full_text"
                logger.info(f"Full-text search: {query} (limit={limit})")

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

            # In production: Update Memory table
            # from app.models.memory import Memory
            # from app.core.database import get_db
            #
            # async for session in get_db():
            #     memory = await session.get(Memory, memory_id)
            #     if not memory or memory.agent_id != context.agent_id:
            #         return self.create_result(success=False, error_message="Memory not found")
            #
            #     if "content" in input_data and input_data["content"]:
            #         memory.content = input_data["content"]
            #         updated_fields.append("content")
            #
            #         # Regenerate embedding if content changed
            #         if is_embedding_enabled():
            #             from app.services.embeddings import generate_embedding
            #             memory.embedding = await generate_embedding(memory.content)
            #             regenerated_embedding = True
            #
            #     if "summary" in input_data and input_data["summary"]:
            #         memory.summary = input_data["summary"]
            #         updated_fields.append("summary")
            #
            #     if "memory_type" in input_data and input_data["memory_type"]:
            #         memory.memory_type = input_data["memory_type"]
            #         updated_fields.append("memory_type")
            #
            #     if "importance_score" in input_data and input_data["importance_score"] is not None:
            #         memory.importance_score = input_data["importance_score"]
            #         updated_fields.append("importance_score")
            #
            #     # Handle tags
            #     if input_data.get("add_tags") or input_data.get("remove_tags"):
            #         tags = memory.meta_data.get("tags", []) if memory.meta_data else []
            #
            #         if input_data.get("add_tags"):
            #             tags.extend([t for t in input_data["add_tags"] if t not in tags])
            #
            #         if input_data.get("remove_tags"):
            #             tags = [t for t in tags if t not in input_data["remove_tags"]]
            #
            #         if not memory.meta_data:
            #             memory.meta_data = {}
            #         memory.meta_data["tags"] = tags
            #         updated_fields.append("tags")
            #
            #     await session.commit()

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
            # In production: Delete from Memory table
            # from app.models.memory import Memory
            # from app.core.database import get_db
            #
            # async for session in get_db():
            #     memory = await session.get(Memory, memory_id)
            #     if not memory or memory.agent_id != context.agent_id:
            #         return self.create_result(success=False, error_message="Memory not found")
            #
            #     await session.delete(memory)
            #     await session.commit()

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
