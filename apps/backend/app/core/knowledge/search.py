"""
JARV Backend - Search the agents' source documentation (Upgrade 1a)

Hybrid search over active passages: by meaning (pgvector cosine distance on the HNSW index, comparing only vectors
from the same embedding model) and by words (Postgres full-text search, websearch_to_tsquery + ts_rank_cd), fused
with Reciprocal Rank Fusion: score = sum of 1 / (60 + rank) over the two lists. RRF uses ranks, not raw scores, so
the two scales never need normalising. Sources whose text is not stored (link_only) are matched on their titles
and returned as links to read live.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from sqlalchemy import func, literal_column, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_library import LICENCE_LINK_ONLY, KnowledgeChunk, KnowledgeSource

logger = logging.getLogger(__name__)

RRF_K = 60
# The PostgreSQL generated full-text column (see knowledge_library.py).
TSV = literal_column("knowledge_chunks.tsv")
CANDIDATES = 20
EF_SEARCH = 100


def fuse(*rankings: Sequence[Any], k: int = RRF_K) -> List[tuple]:
    """Reciprocal Rank Fusion of ranked id lists: [(id, score)] best first."""
    scores: Dict[Any, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


async def _sources(db: AsyncSession, agents: Optional[Sequence[str]], workspace_id: Optional[UUID],
                   workspace_only: bool = False):
    if workspace_only:
        if workspace_id is None:
            return []
        query = select(KnowledgeSource).where(KnowledgeSource.workspace_id == workspace_id)
    else:
        query = select(KnowledgeSource).where(or_(KnowledgeSource.workspace_id.is_(None),
                                                  KnowledgeSource.workspace_id == workspace_id)
                                              if workspace_id is not None else KnowledgeSource.workspace_id.is_(None))
    rows = (await db.execute(query.where(KnowledgeSource.status != "retired"))).scalars().all()
    wanted = set(agents or [])
    return [s for s in rows if not wanted or wanted & set(s.agents or [])]


async def search_passages(db: AsyncSession, query: str, *, agents: Optional[Sequence[str]] = None,
                          workspace_id: Optional[UUID] = None, limit: int = 6,
                          workspace_only: bool = False) -> List[Dict[str, Any]]:
    """The best passages (and unstored sources, as links) for ``query``, each with what to cite.
    ``workspace_only`` searches only the workspace's own documents (its specification)."""
    from app.core.memory.embeddings import get_embedding_service

    query = (query or "").strip()[:2000]
    if not query or db.get_bind().dialect.name != "postgresql":
        return []
    sources = await _sources(db, agents, workspace_id, workspace_only)
    if not sources:
        return []
    by_id = {s.id: s for s in sources}
    stored = [s.id for s in sources if s.licence_class != LICENCE_LINK_ONLY]
    meaning: List[UUID] = []
    words: List[UUID] = []
    if stored:
        try:
            vector, model_id = await get_embedding_service().embed(query)
            # A savepoint, so a failure here (an old pgvector without the setting) cannot abort the caller's
            # transaction; the words half below still runs.
            async with db.begin_nested():
                await db.execute(text(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}"))
                meaning = list((await db.execute(
                    select(KnowledgeChunk.id).where(
                        KnowledgeChunk.source_id.in_(stored), KnowledgeChunk.is_active.is_(True),
                        KnowledgeChunk.embedding_model == model_id, KnowledgeChunk.embedding.is_not(None))
                    .order_by(KnowledgeChunk.embedding.cosine_distance(vector)).limit(CANDIDATES))).scalars().all())
        except Exception as exc:  # noqa: BLE001 - the words half still answers
            logger.warning(f"passage search by meaning failed: {exc}")
        tsquery = func.websearch_to_tsquery("english", query)
        words = list((await db.execute(
            select(KnowledgeChunk.id).where(
                KnowledgeChunk.source_id.in_(stored), KnowledgeChunk.is_active.is_(True),
                TSV.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(TSV, tsquery).desc()).limit(CANDIDATES))).scalars().all())
    ranked = fuse(meaning, words)[:limit]
    chunks = {c.id: c for c in (await db.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.id.in_([cid for cid, _ in ranked])))).scalars().all()}
    hits: List[Dict[str, Any]] = []
    for chunk_id, score in ranked:
        chunk = chunks.get(chunk_id)
        source = by_id.get(chunk.source_id) if chunk else None
        if chunk is None or source is None:
            continue
        hits.append({"kind": "passage", "id": str(chunk.id), "heading_path": chunk.heading_path,
                     "content": chunk.content,
                     "url": source.url, "title": source.title, "publisher": source.publisher,
                     "licence": source.licence, "version": chunk.version, "score": round(score, 5),
                     "by_meaning": chunk_id in meaning, "by_words": chunk_id in words})
    # Unstored sources: found by their titles, read live.
    terms = {w for w in query.lower().replace("-", " ").split() if len(w) > 3}
    for source in sources:
        if source.licence_class == LICENCE_LINK_ONLY and terms & set(
                f"{source.title} {source.publisher}".lower().replace("-", " ").split()):
            hits.append({"kind": "link", "title": source.title, "publisher": source.publisher, "url": source.url,
                         "note": "Text not stored (licence not confirmed); read it with fetch_url."})
    return hits[: limit + 2]


async def agent_passages(db: AsyncSession, agent: str, query: str, *, workspace_id: Optional[UUID] = None,
                         limit: int = 4) -> List[Dict[str, Any]]:
    """An agent's own source documentation for a task, in the shape of its specialist briefs
    ({id, title, source_url, content, version}), so every place that reads the briefs reads these too. Never
    raises: reference material is an addition, not a reason for a task to fail."""
    try:
        hits = await search_passages(db, query, agents=[agent], workspace_id=workspace_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"source documentation unavailable for {agent}: {exc}")
        return []
    return [{"id": hit["id"], "title": hit["heading_path"] or hit["title"], "source_url": hit["url"],
             "source_title": hit["title"], "source_publisher": hit["publisher"], "source_license": hit["licence"],
             "content": hit["content"], "version": hit["version"], "kind": "documentation"}
            for hit in hits if hit["kind"] == "passage"]


def render_passages(hits: List[Dict[str, Any]], *, chars: int = 900) -> str:
    """Hits as short cited lines for a prompt."""
    lines = []
    for hit in hits:
        if hit["kind"] == "passage":
            body = " ".join(hit["content"].split())[:chars]
            lines.append(f"- {hit['heading_path']} ({hit['publisher']}, {hit['url']}): {body}")
        else:
            lines.append(f"- {hit['title']} ({hit['publisher']}, {hit['url']}): {hit['note']}")
    return "\n".join(lines)


async def search_everything(db: AsyncSession, query: str, *, agent: Optional[str] = None,
                            workspace_id: Optional[UUID] = None, limit: int = 8) -> List[Dict[str, Any]]:
    """One ranking over every kind of knowledge (Upgrade 2): the agent's specialist briefs, source
    documentation and the workspace's specification passages, and the workspace's memories. Each list is ranked
    on its own and the lists are fused by rank (RRF), so no score scale needs comparing. Every hit carries its
    kind and what to cite."""
    lists: List[List[str]] = []
    items: Dict[str, Dict[str, Any]] = {}

    def add(kind: str, key: str, hit: Dict[str, Any]) -> str:
        items.setdefault(f"{kind}:{key}", {"kind": kind, **hit})
        return f"{kind}:{key}"

    if agent:
        try:
            from app.core.knowledge.service import knowledge_service

            briefs = await knowledge_service.retrieve(db, agent_name=agent, query=query, limit=limit)
            lists.append([add("brief", b["id"], {"title": b["title"], "content": b["content"],
                                                 "citation": f"{b['source_title']} ({b['source_url']})"})
                          for b in briefs if b.get("relevance_score", 0) > 0])
        except Exception as exc:  # noqa: BLE001 - a missing field still leaves the rest
            logger.info(f"briefs not searched for {agent}: {exc}")
    try:
        passages = await search_passages(db, query, agents=None if agent in (None, "orchestrator") else [agent],
                                         workspace_id=workspace_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"passages not searched: {exc}")
        passages = []
    lists.append([add("documentation" if not str(p["url"]).startswith("workspace://") else "specification",
                      p.get("id") or p["url"],
                      {"title": p.get("heading_path") or p["title"], "content": p.get("content") or p.get("note"),
                       "citation": f"{p['publisher']} ({p['url']})"}) for p in passages])
    if workspace_id is not None:
        try:
            from app.core.jarv_memory import memory_service

            memories = await memory_service.search(db, query, limit=limit, workspace_id=workspace_id)
            lists.append([add("memory", str(m.id), {"title": f"memory ({m.memory_type})", "content": m.content,
                                                    "citation": f"JARV memory {str(m.id)[:8]}"})
                          for m in memories])
        except Exception as exc:  # noqa: BLE001
            logger.info(f"memories not searched: {exc}")
    return [dict(items[key], score=round(score, 5)) for key, score in fuse(*lists)[:limit]]
