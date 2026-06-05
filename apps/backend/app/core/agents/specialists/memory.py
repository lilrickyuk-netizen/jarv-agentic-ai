"""
JARV Backend - MemoryAgent

Reports on the memory ACTUALLY available in the execution context, honestly.

Memory persistence and vector search require a DB session (and pgvector) that
is NOT available to a standalone agent run. This agent therefore never claims to
store, persist, or vector-search memory, and never invents memory IDs or
relevance scores. It reports the real number of items present in the execution
context (memory_context / previous_results / workspace_rules) and, when a query
string is given, performs a REAL substring filter over the in-context memory
items and returns the true matches.
"""
from typing import Dict, Any, List, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists._helpers import context_summary

logger = logging.getLogger(__name__)


class MemoryAgentInput(BaseModel):
    """MemoryAgent input"""
    operation: str = Field(..., description="store, retrieve, search, update")
    memory_type: str = Field(..., description="fact, experience, preference, context")
    content: Dict[str, Any] = Field(default_factory=dict)
    query: str = Field(default="")


class MemoryAgentOutput(BaseModel):
    """MemoryAgent output (honest; real context counts, no fake IDs/scores)."""
    operation_completed: bool = False
    operation: str = ""
    persisted: bool = False
    db_session_available: bool = False
    context_memory_items: int = 0
    previous_results: int = 0
    workspace_rules: int = 0
    query: str = ""
    matches: List[Dict[str, Any]] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class MemoryAgent(AgentBase):
    """
    MemoryAgent - Manages memories, learns from experiences, retrieves context
    """

    @property
    def name(self) -> str:
        return "memory"

    @property
    def role(self) -> str:
        return "Manages memories, learns from experiences, retrieves context"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MemoryAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MemoryAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def default_tools(self) -> list[str]:
        return ['memory_store', 'memory_retrieve', 'memory_search', 'memory_update']

    @staticmethod
    def _item_text(item: Any) -> str:
        """Best-effort text of an in-context memory item (no fabrication)."""
        if isinstance(item, dict):
            for k in ("content", "text", "value", "summary"):
                v = item.get(k)
                if isinstance(v, str) and v:
                    return v
            return str(item)
        return str(item)

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """Report real in-context memory; real substring search when queried."""
        try:
            operation = input_data.get("operation", "retrieve")
            memory_type = input_data.get("memory_type", "fact")
            query = (input_data.get("query") or "").strip()

            self.logger.info(f"Memory operation: {operation} ({memory_type})")

            # REAL counts of what is actually available in this execution.
            summary = context_summary(context)
            mem_items = getattr(context, "memory_context", None) or []

            # REAL substring filter over in-context memory items when a query is
            # supplied. No vector search, no relevance scores invented.
            matches: List[Dict[str, Any]] = []
            if query:
                ql = query.lower()
                for idx, item in enumerate(mem_items):
                    text = self._item_text(item)
                    if ql in text.lower():
                        matches.append({
                            "index": idx,
                            "content": text[:500],
                            "match_method": "substring",
                        })

            persist_ops = {"store", "update"}
            limitations: List[str] = [
                "No DB session is available to this standalone agent: memory "
                "cannot be persisted, and vector/semantic search is not "
                "available. Only the in-context memory items can be inspected.",
            ]
            if operation in persist_ops:
                limitations.append(
                    f"Operation '{operation}' was NOT persisted; persisting "
                    "memory requires the memory subsystem with a DB session."
                )
            if operation == "search" and not query:
                limitations.append(
                    "Search requested without a query string; no substring "
                    "filter was applied."
                )
            if query and not mem_items:
                limitations.append(
                    "A query was provided but the execution context contained no "
                    "memory items to search."
                )

            recommendations = [
                "Route memory store/search through the memory subsystem (DB + "
                "pgvector) for real persistence and semantic search.",
            ]

            result_data = {
                "operation_completed": False,
                "operation": operation,
                "persisted": False,
                "db_session_available": False,
                "context_memory_items": summary["memory_context_items"],
                "previous_results": summary["previous_results"],
                "workspace_rules": summary["workspace_rules"],
                "query": query,
                "matches": matches,
                "limitations": limitations,
                "recommendations": recommendations,
            }

            if query:
                detail = f"{len(matches)} substring match(es) over {summary['memory_context_items']} in-context item(s)"
            else:
                detail = f"{summary['memory_context_items']} in-context memory item(s) available"
            output_text = (
                f"Memory[{operation}] (no DB session, not persisted): {detail}."
            )

            # A truthful report over real in-context data is a successful run.
            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=output_text,
                tools_used=[],
            )

        except Exception as e:
            self.logger.error(f"memory task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
