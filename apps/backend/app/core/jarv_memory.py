"""
JARV Backend - Persistent Agent Memory Service

Persistent memory backed by PostgreSQL (pgvector extension available for vector
search; keyword search is always available so memory works without an embedding
provider). Memory records persist across sessions and link to task + workspace.

Supports: add, search, update, delete, and link-to-task/workspace. Agent outputs,
task results, decisions, approvals, and workspace scans are stored here so the
orchestrator and agents can recall prior context before planning.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.memory import Memory
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


class MemoryService:
    """Persistent agent memory over the `memories` table."""

    async def _agent_id(self, db: AsyncSession) -> UUID:
        """Resolve an agent to own memory rows (reuse existing, else create one)."""
        existing = (await db.execute(select(Agent.id).limit(1))).scalar_one_or_none()
        if existing:
            return existing
        ws_id = (await db.execute(select(Workspace.id).limit(1))).scalar_one_or_none()
        agent = Agent(
            id=uuid4(),
            name="memory",
            agent_type="memory",
            workspace_id=ws_id,
            model_provider="claude",
            model_name="claude-sonnet-4-6",
            authority_level=1,
            allowed_tools=["memory_add", "memory_search"],
            blocked_tools=[],
            current_state="idle",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(agent)
        await db.flush()
        return agent.id

    async def add(
        self,
        db: AsyncSession,
        content: str,
        memory_type: str = "fact",
        workspace_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        importance: float = 0.6,
        summary: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
        permanent: bool = True,
    ) -> Memory:
        """Persist a memory record linked to task/workspace."""
        agent_id = await self._agent_id(db)
        record = Memory(
            id=uuid4(),
            agent_id=agent_id,
            memory_type=memory_type,
            content=content,
            summary=summary or (content[:200] if content else None),
            importance_score=importance,
            task_id=task_id,
            context={"workspace_id": str(workspace_id) if workspace_id else None},
            meta_data=meta or {},
            is_permanent=permanent,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(record)
        await db.flush()
        return record

    async def search(
        self,
        db: AsyncSession,
        query: str,
        limit: int = 5,
        workspace_id: Optional[UUID] = None,
    ) -> List[Memory]:
        """
        Keyword search over memory content/summary (always available, no embedding
        provider required). Results ordered by importance then recency.
        """
        q = (query or "").strip()
        stmt = select(Memory)
        if q:
            terms = [t for t in q.replace(",", " ").split() if len(t) > 2][:6]
            if terms:
                conds = []
                for t in terms:
                    like = f"%{t}%"
                    conds.append(Memory.content.ilike(like))
                    conds.append(Memory.summary.ilike(like))
                stmt = stmt.where(or_(*conds))
        stmt = stmt.order_by(Memory.importance_score.desc(), Memory.created_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

        # Bump access bookkeeping (real persistence side-effect).
        now = datetime.now(timezone.utc)
        for r in rows:
            r.access_count = (r.access_count or 0) + 1
            r.last_accessed_at = now
        if rows:
            await db.flush()
        return list(rows)

    async def count(self, db: AsyncSession) -> int:
        return int((await db.execute(select(func.count(Memory.id)))).scalar() or 0)

    async def pgvector_available(self, db: AsyncSession) -> bool:
        """True if the pgvector extension is installed (vector search backend)."""
        from sqlalchemy import text
        try:
            res = await db.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
            return res.first() is not None
        except Exception:  # noqa: BLE001
            return False


memory_service = MemoryService()
