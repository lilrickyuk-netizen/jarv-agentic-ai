"""
JARV Backend - Persistent Agent Memory Service

The single memory store used by the command center, the tool runtime, agent
execution, and the memory API.

Guarantees:
- Workspace isolation. A search scoped to a workspace returns that workspace's
  memories plus genuinely global ones (no workspace), never another
  workspace's. Rows are owned by an agent from the same workspace.
- Semantic + keyword ranking. Every memory is embedded on write
  (``app.core.memory.embeddings``). PostgreSQL ranks with pgvector cosine
  distance; other databases rank in Python. Keyword overlap and importance
  are blended in, so search still works for rows whose vectors come from a
  different embedding model.
- The 23 design categories (``app.core.memory.taxonomy``), confidence,
  provenance (source_ref), versioning, and parent-agent / sub-agent / approval
  / checkpoint / boundary-input references.
- No duplicate noise. Writing the same content into the same workspace and
  category reinforces the existing record instead of creating a new one.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory.embeddings import get_embedding_service
from app.core.memory.taxonomy import categorise, validate_category
from app.core.security import redact_text
from app.models.agent import Agent
from app.models.memory import Memory

logger = logging.getLogger(__name__)

VECTOR_DIMENSIONS = 1536
_CANDIDATE_CAP = 400          # rows scored in Python on non-PostgreSQL databases
_SEMANTIC_WEIGHT = 0.65
_KEYWORD_WEIGHT = 0.25
_IMPORTANCE_WEIGHT = 0.10
_TERM_RE = re.compile(r"[a-z0-9]{3,}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_uuid(value: Any) -> Optional[UUID]:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _normalise_vector(vector: Sequence[float]) -> Optional[List[float]]:
    values = [float(v) for v in vector]
    if len(values) != VECTOR_DIMENSIONS:
        return None
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0.0:
        return None
    return [v / norm for v in values]


def _dialect(db: AsyncSession) -> str:
    try:
        return db.get_bind().dialect.name
    except Exception:  # noqa: BLE001 - unbound session: rank in Python
        return ""


def _timestamp(value: Optional[datetime]) -> float:
    if value is None:
        return 0.0
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()


def _query_terms(text: str) -> List[str]:
    seen: List[str] = []
    for term in _TERM_RE.findall((text or "").lower()):
        if term not in seen:
            seen.append(term)
    return seen[:12]


def _keyword_score(terms: Sequence[str], record: Memory) -> float:
    if not terms:
        return 0.0
    haystack = f"{record.content or ''} {record.summary or ''}".lower()
    return sum(1 for term in terms if term in haystack) / len(terms)


@dataclass
class ScoredMemory:
    """A search hit with the evidence behind its rank."""
    memory: Memory
    score: float
    semantic: float
    keyword: float
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        m = self.memory
        return {
            "id": str(m.id),
            "type": m.memory_type,
            "category": m.memory_category,
            "content": m.content,
            "summary": m.summary,
            "importance": m.importance_score,
            "confidence": m.confidence_score,
            "source_ref": m.source_ref,
            "task_id": str(m.task_id) if m.task_id else None,
            "workspace_id": str(m.workspace_id) if m.workspace_id else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "score": round(self.score, 4),
            "semantic": round(self.semantic, 4),
            "keyword": round(self.keyword, 4),
        }


class MemoryService:
    """Persistent, workspace-isolated agent memory over the ``memories`` table."""

    # ----- ownership -------------------------------------------------------

    async def _agent_id(self, db: AsyncSession, workspace_id: Optional[UUID] = None) -> UUID:
        """Agent that owns rows written for ``workspace_id``.

        Reuses an active agent from that workspace (preferring the memory
        agent) and creates the workspace's memory agent if it has none. It
        never borrows an agent from a different workspace.
        """
        workspace_id = _as_uuid(workspace_id)
        if workspace_id is None:
            workspace_id = await self._fallback_workspace(db)
        existing = (await db.execute(
            select(Agent.id)
            .where(Agent.workspace_id == workspace_id, Agent.is_active.is_(True))
            .order_by((Agent.agent_type == "memory").desc(), Agent.created_at.asc())
            .limit(1)
        )).scalar_one_or_none()
        if existing:
            return existing
        agent = Agent(
            id=uuid4(),
            name="memory",
            agent_type="memory",
            workspace_id=workspace_id,
            model_provider="claude",
            model_name="claude-sonnet-4-6",
            authority_level=1,
            allowed_tools=["memory_add", "memory_search"],
            blocked_tools=[],
            current_state="idle",
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(agent)
        await db.flush()
        return agent.id

    async def _fallback_workspace(self, db: AsyncSession) -> UUID:
        """Agents require a workspace. Global memories are owned by the oldest
        workspace's memory agent; the memory row itself stays global
        (workspace_id NULL) so it is not attributed to that workspace."""
        from app.models.workspace import Workspace

        workspace = (await db.execute(
            select(Workspace.id).order_by(Workspace.created_at.asc()).limit(1)
        )).scalar_one_or_none()
        if workspace is None:
            raise ValueError("A workspace must exist before memory can be stored")
        return workspace

    # ----- write -----------------------------------------------------------

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
        *,
        category: Optional[str] = None,
        confidence: float = 0.5,
        source_ref: Optional[str] = None,
        agent_id: Optional[UUID] = None,
        parent_agent_id: Optional[UUID] = None,
        sub_agent_id: Optional[UUID] = None,
        approval_id: Optional[UUID] = None,
        checkpoint_id: Optional[UUID] = None,
        boundary_input_id: Optional[UUID] = None,
        expires_at: Optional[datetime] = None,
        session_id: Optional[UUID] = None,
    ) -> Memory:
        """Persist a memory, or reinforce the identical one already stored."""
        # Secrets never enter memory, whichever caller wrote them.
        text = redact_text((content or "").strip())
        if not text:
            raise ValueError("Memory content cannot be empty")
        summary = redact_text(summary) if summary else None
        workspace_id = _as_uuid(workspace_id)
        memory_category = (validate_category(category) if category
                           else categorise(memory_type, has_workspace=workspace_id is not None))

        duplicate = (await db.execute(
            select(Memory).where(
                Memory.content == text,
                Memory.memory_category == memory_category,
                Memory.workspace_id == workspace_id if workspace_id else Memory.workspace_id.is_(None),
            ).limit(1)
        )).scalar_one_or_none()
        if duplicate is not None:
            duplicate.importance_score = min(1.0, max(duplicate.importance_score, importance) + 0.05)
            duplicate.confidence_score = min(1.0, max(duplicate.confidence_score or 0.0, confidence))
            duplicate.access_count = (duplicate.access_count or 0) + 1
            duplicate.last_accessed_at = _now()
            duplicate.updated_at = _now()
            if task_id and not duplicate.task_id:
                duplicate.task_id = task_id
            reinforced = dict(duplicate.meta_data or {})
            reinforced["reinforced"] = int(reinforced.get("reinforced", 0)) + 1
            duplicate.meta_data = reinforced
            await db.flush()
            return duplicate

        embedding, embedding_model = await self._embed(text)
        owner = _as_uuid(agent_id) or await self._agent_id(db, workspace_id)
        record = Memory(
            id=uuid4(),
            agent_id=owner,
            memory_type=memory_type or "fact",
            memory_category=memory_category,
            content=text,
            summary=summary or text[:200],
            embedding=embedding,
            embedding_model=embedding_model if embedding is not None else None,
            importance_score=max(0.0, min(1.0, importance)),
            confidence_score=max(0.0, min(1.0, confidence)),
            source_ref=(source_ref or None) and source_ref[:255],
            version=1,
            workspace_id=workspace_id,
            task_id=_as_uuid(task_id),
            session_id=_as_uuid(session_id),
            parent_agent_id=_as_uuid(parent_agent_id),
            sub_agent_id=_as_uuid(sub_agent_id),
            approval_id=_as_uuid(approval_id),
            checkpoint_id=_as_uuid(checkpoint_id),
            boundary_input_id=_as_uuid(boundary_input_id),
            # Kept for readers written before the workspace_id column existed.
            context={"workspace_id": str(workspace_id) if workspace_id else None},
            meta_data=meta or {},
            is_permanent=permanent,
            expires_at=expires_at,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(record)
        await db.flush()
        return record

    async def _embed(self, text: str):
        service = get_embedding_service()
        try:
            vector, model_id = await service.embed(text)
        except Exception as exc:  # noqa: BLE001 - row is still stored and keyword-searchable
            logger.warning(f"memory embedding failed: {exc}")
            return None, None
        normalised = _normalise_vector(vector)
        return (normalised, model_id) if normalised is not None else (None, None)

    async def update(
        self,
        db: AsyncSession,
        memory_id: UUID,
        workspace_id: Optional[UUID],
        *,
        content: Optional[str] = None,
        summary: Optional[str] = None,
        importance: Optional[float] = None,
        confidence: Optional[float] = None,
        category: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
        permanent: Optional[bool] = None,
    ) -> Optional[Memory]:
        """Edit a memory in the caller's scope. Content edits re-embed and bump the version."""
        record = await self.get(db, memory_id, workspace_id)
        if record is None:
            return None
        if content is not None and content.strip() and content.strip() != record.content:
            history = list((record.meta_data or {}).get("history", []))[-9:]
            history.append({"version": record.version, "content": record.content,
                            "changed_at": _now().isoformat()})
            record.content = redact_text(content.strip())
            record.summary = summary or record.content[:200]
            record.embedding, record.embedding_model = await self._embed(record.content)
            record.version = (record.version or 1) + 1
            record.meta_data = {**(record.meta_data or {}), "history": history}
        elif summary is not None:
            record.summary = summary
        if importance is not None:
            record.importance_score = max(0.0, min(1.0, importance))
        if confidence is not None:
            record.confidence_score = max(0.0, min(1.0, confidence))
        if category is not None:
            record.memory_category = validate_category(category)
        if meta:
            record.meta_data = {**(record.meta_data or {}), **meta}
        if permanent is not None:
            record.is_permanent = permanent
        record.updated_at = _now()
        await db.flush()
        return record

    async def delete(self, db: AsyncSession, memory_id: UUID, workspace_id: Optional[UUID]) -> bool:
        record = await self.get(db, memory_id, workspace_id)
        if record is None:
            return False
        await db.delete(record)
        await db.flush()
        return True

    async def link_to_task(
        self, db: AsyncSession, memory_id: UUID, workspace_id: Optional[UUID], task_id: UUID,
    ) -> Optional[Memory]:
        """Attach a memory to a task in the same workspace."""
        from app.models.task import Task

        record = await self.get(db, memory_id, workspace_id)
        if record is None:
            return None
        task = (await db.execute(select(Task).where(Task.id == _as_uuid(task_id)))).scalar_one_or_none()
        if task is None:
            raise LookupError("Task not found")
        task_workspace = getattr(task, "workspace_id", None)
        if record.workspace_id and task_workspace and task_workspace != record.workspace_id:
            raise PermissionError("Task belongs to a different workspace")
        record.task_id = task.id
        record.updated_at = _now()
        await db.flush()
        return record

    async def link_to_workspace(
        self, db: AsyncSession, memory_id: UUID, workspace_id: UUID,
    ) -> Optional[Memory]:
        """Adopt a global memory into a workspace. A memory that already belongs
        to a workspace is never moved to another one."""
        workspace_id = _as_uuid(workspace_id)
        record = (await db.execute(select(Memory).where(Memory.id == _as_uuid(memory_id)))).scalar_one_or_none()
        if record is None:
            return None
        if record.workspace_id is not None and record.workspace_id != workspace_id:
            raise PermissionError("Memory already belongs to a different workspace")
        record.workspace_id = workspace_id
        record.agent_id = await self._agent_id(db, workspace_id)
        if record.memory_category == "global":
            record.memory_category = "workspace"
        record.context = {**(record.context or {}), "workspace_id": str(workspace_id)}
        record.updated_at = _now()
        await db.flush()
        return record

    # ----- read ------------------------------------------------------------

    def _scope(self, workspace_id: Optional[UUID], include_global: bool):
        """Rows visible from ``workspace_id``.

        A row without a workspace (written outside any workspace, or a legacy row
        the migration could not attribute) is visible only from the workspace its
        owning agent belongs to, so it can never leak to another owner.
        """
        workspace_id = _as_uuid(workspace_id)
        if workspace_id is None:
            return Memory.workspace_id.is_(None)
        if include_global:
            owned_agents = select(Agent.id).where(Agent.workspace_id == workspace_id)
            return or_(Memory.workspace_id == workspace_id,
                       and_(Memory.workspace_id.is_(None), Memory.agent_id.in_(owned_agents)))
        return Memory.workspace_id == workspace_id

    def _live(self):
        return or_(Memory.expires_at.is_(None), Memory.expires_at > _now())

    async def get(self, db: AsyncSession, memory_id: UUID, workspace_id: Optional[UUID]) -> Optional[Memory]:
        """Fetch one memory only if it is in the caller's workspace (or global)."""
        return (await db.execute(
            select(Memory).where(
                Memory.id == _as_uuid(memory_id),
                self._scope(workspace_id, include_global=True),
            )
        )).scalar_one_or_none()

    async def search(
        self,
        db: AsyncSession,
        query: str,
        limit: int = 5,
        workspace_id: Optional[UUID] = None,
        **filters: Any,
    ) -> List[Memory]:
        """Ranked memories (kept as a list of rows for existing callers)."""
        return [hit.memory for hit in await self.search_scored(
            db, query, limit=limit, workspace_id=workspace_id, **filters)]

    async def search_scored(
        self,
        db: AsyncSession,
        query: str,
        *,
        limit: int = 5,
        workspace_id: Optional[UUID] = None,
        categories: Optional[Iterable[str]] = None,
        task_id: Optional[UUID] = None,
        include_global: bool = True,
        min_score: float = 0.12,
        touch: bool = True,
    ) -> List[ScoredMemory]:
        """Rank memories by semantic similarity, keyword overlap, and importance."""
        limit = max(1, min(int(limit), 50))
        conditions = [self._scope(workspace_id, include_global), self._live()]
        if categories:
            conditions.append(Memory.memory_category.in_([validate_category(c) for c in categories]))
        if task_id:
            conditions.append(Memory.task_id == _as_uuid(task_id))
        base = and_(*conditions)

        text = (query or "").strip()
        if not text:
            rows = (await db.execute(
                select(Memory).where(base)
                .order_by(Memory.importance_score.desc(), Memory.created_at.desc())
                .limit(limit)
            )).scalars().all()
            hits = [ScoredMemory(r, r.importance_score, 0.0, 0.0, ["importance"]) for r in rows]
            return await self._finish(db, hits, touch)

        terms = _query_terms(text)
        query_vector, model_id = await self._embed(text)
        candidates: Dict[UUID, Memory] = {}
        semantic: Dict[UUID, float] = {}

        if query_vector is not None and _dialect(db) == "postgresql":
            distance = Memory.embedding.cosine_distance(query_vector).label("distance")
            for record, dist in (await db.execute(
                select(Memory, distance)
                .where(base, Memory.embedding_model == model_id, Memory.embedding.is_not(None))
                .order_by(distance).limit(limit * 6)
            )).all():
                candidates[record.id] = record
                semantic[record.id] = max(0.0, 1.0 - float(dist))
        else:
            for record in (await db.execute(
                select(Memory).where(base)
                .order_by(Memory.created_at.desc()).limit(_CANDIDATE_CAP)
            )).scalars().all():
                candidates[record.id] = record

        if terms:
            keyword_filter = or_(*[
                condition for term in terms
                for condition in (Memory.content.ilike(f"%{term}%"), Memory.summary.ilike(f"%{term}%"))
            ])
            for record in (await db.execute(
                select(Memory).where(base, keyword_filter)
                .order_by(Memory.importance_score.desc(), Memory.created_at.desc())
                .limit(limit * 6)
            )).scalars().all():
                candidates.setdefault(record.id, record)

        query_nonzero = ([(i, v) for i, v in enumerate(query_vector) if v] if query_vector else [])
        hits: List[ScoredMemory] = []
        for record_id, record in candidates.items():
            sim = semantic.get(record_id)
            if (sim is None and query_nonzero and record.embedding is not None
                    and record.embedding_model == model_id):
                # Stored vectors are unit length, as is the query: dot product == cosine.
                vector = record.embedding
                sim = max(0.0, sum(value * float(vector[i]) for i, value in query_nonzero))
            sim = sim or 0.0
            kw = _keyword_score(terms, record)
            score = (_SEMANTIC_WEIGHT * sim + _KEYWORD_WEIGHT * kw
                     + _IMPORTANCE_WEIGHT * (record.importance_score or 0.0))
            if sim < 0.08 and kw == 0.0:
                continue
            if score < min_score:
                continue
            reasons = [r for r, ok in (("semantic", sim >= 0.08), ("keyword", kw > 0)) if ok]
            hits.append(ScoredMemory(record, score, sim, kw, reasons))

        hits.sort(key=lambda h: (h.score, _timestamp(h.memory.created_at)), reverse=True)
        return await self._finish(db, hits[:limit], touch)

    async def _finish(self, db: AsyncSession, hits: List[ScoredMemory], touch: bool) -> List[ScoredMemory]:
        if touch and hits:
            now = _now()
            for hit in hits:
                hit.memory.access_count = (hit.memory.access_count or 0) + 1
                hit.memory.last_accessed_at = now
                # Set explicitly: a server-side onupdate would expire the attribute,
                # and reading an expired attribute on an AsyncSession fails.
                hit.memory.updated_at = now
            await db.flush()
        return hits

    async def backfill_embeddings(self, db: AsyncSession, *, batch: int = 200) -> int:
        """Embed rows written before vectors were stored, or with a different model.

        Returns how many rows were (re)embedded. Safe to run repeatedly.
        """
        model_id = get_embedding_service().model_id
        rows = (await db.execute(
            select(Memory).where(or_(Memory.embedding.is_(None), Memory.embedding_model != model_id,
                                     Memory.embedding_model.is_(None)))
            .limit(batch)
        )).scalars().all()
        updated = 0
        for record in rows:
            vector, used_model = await self._embed(record.content)
            if vector is not None:
                record.embedding, record.embedding_model = vector, used_model
                record.updated_at = _now()
                record.memory_category = record.memory_category or categorise(
                    record.memory_type, has_workspace=record.workspace_id is not None)
                updated += 1
        if updated:
            await db.flush()
        return updated

    async def count(self, db: AsyncSession, workspace_id: Optional[UUID] = None) -> int:
        stmt = select(func.count(Memory.id))
        if workspace_id is not None:
            stmt = stmt.where(Memory.workspace_id == _as_uuid(workspace_id))
        return int((await db.execute(stmt)).scalar() or 0)

    async def pgvector_available(self, db: AsyncSession) -> bool:
        """True if the pgvector extension is installed (vector search backend)."""
        from sqlalchemy import text
        try:
            res = await db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            return res.first() is not None
        except Exception:  # noqa: BLE001
            return False


memory_service = MemoryService()
