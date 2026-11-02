"""
Install or refresh the agents' source documentation, and re-embed memories.

    docker compose exec -T backend python -m app.cli.knowledge ingest                 # every catalogue source
    docker compose exec -T backend python -m app.cli.knowledge ingest --agent verifier
    docker compose exec -T backend python -m app.cli.knowledge status
    docker compose exec -T backend python -m app.cli.knowledge reembed-memories

Each run is written to the audit log. Nothing here changes any project folder.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select


async def _audit(db, action: str, description: str, after: dict) -> None:
    from app.models.operations import AuditLog

    now = datetime.now(timezone.utc)
    db.add(AuditLog(id=uuid4(), workspace_id=None, actor_type="system", action=action,
                    action_category="knowledge", description=description[:1000], target_type="knowledge",
                    target_id=None, after_state=after, success=True, created_at=now, updated_at=now))
    await db.commit()


async def ingest(agents) -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.knowledge.ingest import knowledge_ingestor
    from app.core.knowledge.documentation import catalogue

    async with AsyncSessionLocal() as db:
        results = await knowledge_ingestor.install(db, catalogue(), agents=agents or None)
        counts = Counter(r["status"] for r in results)
        for r in results:
            line = f"{r['status']:>10}  {r.get('passages', 0):>4} passages  {r['url']}"
            print(line + (f"  ({r['reason']})" if r.get("reason") else ""))
        print(f"\n{len(results)} sources: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
        await _audit(db, "knowledge.ingest", f"Knowledge ingest: {dict(counts)}",
                     {"agents": list(agents or []), "counts": dict(counts)})
    return 0 if not counts.get("error") else 1


async def status() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.knowledge_library import KnowledgeChunk, KnowledgeSource

    async with AsyncSessionLocal() as db:
        sources = (await db.execute(select(KnowledgeSource).order_by(KnowledgeSource.url))).scalars().all()
        counts = dict((await db.execute(select(KnowledgeChunk.source_id, func.count()).where(
            KnowledgeChunk.is_active.is_(True)).group_by(KnowledgeChunk.source_id))).all())
        for s in sources:
            print(f"{s.status:>10}  {s.licence_class:>9}  {counts.get(s.id, 0):>4}  {', '.join(s.agents)}  {s.url}")
        print(f"\n{len(sources)} sources, {sum(counts.values())} active passages")
    return 0


async def reembed_memories() -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.jarv_memory import memory_service
    from app.core.memory.embeddings import get_embedding_service

    model = get_embedding_service().model_id
    print(f"Embedding model: {model}")
    if model.startswith("local:"):
        print("No OpenAI key is visible to JARV, so memories stay on the local embedder. Nothing changed.")
        return 1
    total = 0
    async with AsyncSessionLocal() as db:
        while True:
            done = await memory_service.backfill_embeddings(db, batch=200)
            await db.commit()
            total += done
            if done == 0:
                break
            print(f"re-embedded {total} so far")
        await _audit(db, "knowledge.reembed_memories", f"Re-embedded {total} memories with {model}",
                     {"model": model, "count": total})
    print(f"Done: {total} memories now use {model}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.knowledge")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("ingest", help="register and fetch the catalogue's sources")
    run.add_argument("--agent", action="append", default=[], help="only this agent's sources (repeatable)")
    sub.add_parser("status", help="list sources and their passages")
    sub.add_parser("reembed-memories", help="re-embed memories with the current embedding model")
    args = parser.parse_args()
    if args.command == "ingest":
        return asyncio.run(ingest(args.agent))
    if args.command == "status":
        return asyncio.run(status())
    return asyncio.run(reembed_memories())


if __name__ == "__main__":
    raise SystemExit(main())
