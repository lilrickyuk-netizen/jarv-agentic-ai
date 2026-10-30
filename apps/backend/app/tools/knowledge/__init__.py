"""
JARV Backend - consult_specialist_knowledge (Repair 13)

Lets an agent look up its field's knowledge library mid-task (or another
field's, by name): source-attributed, versioned topics ranked by relevance.
Every agent's toolbox offers it, scoped to that agent by default. Read-only.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.core.agents.base import AuthorityLevel
from app.tools._scoped import ScopedTool


class _Consult(BaseModel):
    query: str = Field(..., min_length=2, max_length=500, description="What you need to know")
    field: Optional[str] = Field(None, description="Agent field to search, e.g. security or finance; defaults to yours")
    limit: int = Field(4, ge=1, le=8)


class ConsultSpecialistKnowledgeTool(ScopedTool):
    _name = "consult_specialist_knowledge"
    _description = ("Look up expert guidance in your field's knowledge library (or another field's): practices, "
                    "rules and definitions from authoritative sources, with the source to cite.")
    _input = _Consult
    _category = "knowledge"
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        from app.core.agents.registry import get_registry
        from app.core.knowledge.service import knowledge_service

        field = data.get("field") or (context.metadata or {}).get("agent")
        if not field:
            raise ValueError("Name the field to search (an agent name such as security or finance)")
        if not get_registry().is_implemented(field):
            raise LookupError(f"No knowledge field named '{field}'")
        found = await knowledge_service.retrieve(db, agent_name=field, query=data["query"], limit=data["limit"])
        topics = [{"title": r["title"], "guidance": r["content"], "source": r["source_title"],
                   "publisher": r["source_publisher"], "url": r["source_url"], "version": r["version"],
                   "relevance": round(r["relevance_score"], 3)} for r in found if r["relevance_score"] > 0]
        if not topics:
            return {"field": field, "topics": []}, f"No {field} guidance matches '{data['query']}'"
        return {"field": field, "topics": topics}, (
            f"{len(topics)} {field} topic(s): " + "; ".join(t["title"] for t in topics))


KNOWLEDGE_TOOLS = [ConsultSpecialistKnowledgeTool]
