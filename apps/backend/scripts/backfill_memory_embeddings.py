"""Embed memory rows that have no vector, or a vector from another embedding model.

Run once after applying the r11_memory_learning migration, and again after
changing EMBEDDING_PROVIDER. Safe to re-run; it only touches rows that need it.

    python -m scripts.backfill_memory_embeddings
"""
import asyncio

from app.core.database import AsyncSessionLocal
from app.core.jarv_memory import memory_service
from app.core.memory.embeddings import get_embedding_service


async def main() -> None:
    total = 0
    while True:
        async with AsyncSessionLocal() as db:
            updated = await memory_service.backfill_embeddings(db, batch=200)
            await db.commit()
        total += updated
        if updated == 0:
            break
        print(f"embedded {total} memories so far")
    print(f"done: {total} memories embedded with {get_embedding_service().model_id}")


if __name__ == "__main__":
    asyncio.run(main())
