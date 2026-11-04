"""
JAI's knowledge service (Wave 6): Graphiti's temporal knowledge graph and Mem0's memory of Richard.

- Graphiti (Apache-2.0, Zep) keeps what JAI learns from its work as facts between things (Plexecute -> uses ->
  Stripe), each with when it became true and when it stopped being true, so a fact that changes is replaced rather
  than contradicted. One graph per workspace (its group). It runs on FalkorDB Lite, embedded in this service, with
  its data in this service's volume.
- Mem0 (Apache-2.0) keeps what Richard tells JAI about himself and how he wants things done, deciding for each new
  thing whether it adds to, updates or replaces what it already knows. Its vectors live in JAI's own PostgreSQL
  (pgvector, its own database).

Neither holds a provider key: both call JAI's model gateway with JAI's gateway token, so every call is priced and
inside JAI's daily spending limit. Adding (which needs the model) is queued and done one at a time in the order it
arrived; searching answers at once.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("jai.knowledge")
logging.basicConfig(level=logging.INFO)

TOKEN = os.environ.get("KNOWLEDGE_TOKEN", "")
GATEWAY = os.environ.get("JAI_GATEWAY_URL", "http://backend:8000/api/gateway/v1")
GATEWAY_TOKEN = os.environ.get("JAI_GATEWAY_TOKEN", "")
MODEL = os.environ.get("KNOWLEDGE_MODEL", "gpt-6-luna")
EMBEDDING_MODEL = os.environ.get("KNOWLEDGE_EMBEDDING_MODEL", "text-embedding-3-small")
GRAPH_FILE = os.environ.get("GRAPH_FILE", "/data/graph/jai.db")
HISTORY_FILE = os.environ.get("MEM0_HISTORY_FILE", "/data/mem0/history.db")
QUEUE_LIMIT = 500


class Store:
    """The two stores, started on first use so the service answers its health check at once."""

    def __init__(self) -> None:
        self.graph = None
        self.memory = None
        self.errors: Dict[str, str] = {}
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self.done = 0
        self.failed = 0
        self.last_error: Optional[str] = None
        self.worker: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()

    async def graphiti(self):
        async with self.lock:
            if self.graph is None:
                from graphiti_core import Graphiti
                from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
                from graphiti_core.driver.falkordb_driver import FalkorDriver
                from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
                from graphiti_core.llm_client.config import LLMConfig
                from graphiti_core.llm_client.openai_client import OpenAIClient
                from redislite.async_falkordb_client import AsyncFalkorDB

                os.makedirs(os.path.dirname(GRAPH_FILE), exist_ok=True)
                llm = LLMConfig(api_key=GATEWAY_TOKEN, base_url=GATEWAY, model=MODEL, small_model=MODEL)
                graph = Graphiti(
                    graph_driver=FalkorDriver(falkor_db=AsyncFalkorDB(dbfilename=GRAPH_FILE)),
                    llm_client=OpenAIClient(config=llm),
                    embedder=OpenAIEmbedder(config=OpenAIEmbedderConfig(
                        api_key=GATEWAY_TOKEN, base_url=GATEWAY, embedding_model=EMBEDDING_MODEL)),
                    cross_encoder=OpenAIRerankerClient(config=llm))
                await graph.build_indices_and_constraints()
                self.graph = graph
            return self.graph

    def mem0_config(self) -> Dict[str, Any]:
        return {
            "llm": {"provider": "openai", "config": {"model": MODEL, "api_key": GATEWAY_TOKEN,
                                                     "openai_base_url": GATEWAY}},
            "embedder": {"provider": "openai", "config": {"model": EMBEDDING_MODEL, "api_key": GATEWAY_TOKEN,
                                                          "openai_base_url": GATEWAY, "embedding_dims": 1536}},
            "vector_store": {"provider": "pgvector", "config": {
                "dbname": os.environ.get("MEM0_DB", "mem0"), "user": os.environ.get("MEM0_DB_USER", "mem0"),
                "password": os.environ.get("MEM0_DB_PASSWORD", ""),
                "host": os.environ.get("MEM0_DB_HOST", "postgres"), "port": int(os.environ.get("MEM0_DB_PORT", "5432")),
                "collection_name": "jai_memories", "embedding_model_dims": 1536}},
            "history_db_path": HISTORY_FILE,
        }

    async def mem0(self):
        async with self.lock:
            if self.memory is None:
                from mem0 import Memory

                os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
                self.memory = await asyncio.to_thread(Memory.from_config, self.mem0_config())
            return self.memory

    def start(self) -> None:
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._work())

    async def _work(self) -> None:
        while True:
            job = await self.queue.get()
            started = time.monotonic()
            try:
                await job["run"]()
                self.done += 1
                log.info("%s done in %.1fs", job["what"], time.monotonic() - started)
            except Exception as exc:  # noqa: BLE001 - one failed add never stops the queue
                self.failed += 1
                self.last_error = f"{job['what']}: {type(exc).__name__}: {str(exc)[:300]}"
                log.warning(self.last_error)
            finally:
                self.queue.task_done()

    def enqueue(self, what: str, run) -> int:
        self.start()
        try:
            self.queue.put_nowait({"what": what, "run": run})
        except asyncio.QueueFull as exc:
            raise HTTPException(503, "JAI's knowledge queue is full; try again shortly.") from exc
        return self.queue.qsize()


STORE = Store()
app = FastAPI(title="JAI knowledge")


def _check(authorization: Optional[str]) -> None:
    raw = authorization or ""
    given = raw[7:] if raw.lower().startswith("bearer ") else raw
    if not TOKEN or not hmac.compare_digest(given.encode(), TOKEN.encode()):
        raise HTTPException(401, "Not JAI's knowledge token.")


def _group(value: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in value)[:64]
    if not cleaned:
        raise HTTPException(400, "A group (workspace) is needed.")
    return cleaned


def _when(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat(timespec="minutes") if value else None


class Episode(BaseModel):
    group: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=60000)
    source: str = Field(default="JAI", max_length=200)
    reference_time: Optional[datetime] = None


class GraphSearch(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    groups: List[str] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=10, ge=1, le=50)


class Remember(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    user: str = Field(default="richard", max_length=80)
    role: str = Field(default="user", pattern="^(user|assistant)$")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Recall(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    user: str = Field(default="richard", max_length=80)
    limit: int = Field(default=8, ge=1, le=50)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"ok": True, "graph_started": STORE.graph is not None, "memory_started": STORE.memory is not None,
            "queued": STORE.queue.qsize(), "done": STORE.done, "failed": STORE.failed,
            "last_error": STORE.last_error, "gateway": bool(GATEWAY_TOKEN)}


@app.post("/start")
async def start(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Open both stores now (the graph builds its indexes; Mem0 makes its table) and say whether they work."""
    _check(authorization)
    out: Dict[str, Any] = {}
    for name, opener in (("graph", STORE.graphiti), ("memory", STORE.mem0)):
        try:
            await opener()
            out[name] = "ready"
        except Exception as exc:  # noqa: BLE001
            out[name] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return out


@app.post("/graph/episodes")
async def add_episode(body: Episode, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check(authorization)
    from graphiti_core.nodes import EpisodeType

    group = _group(body.group)

    async def run() -> None:
        graph = await STORE.graphiti()
        await graph.add_episode(name=body.name, episode_body=body.body, source=EpisodeType.text,
                                source_description=body.source, group_id=group,
                                reference_time=body.reference_time or datetime.now(timezone.utc))

    return {"queued": True, "position": STORE.enqueue(f"graph episode {body.name[:60]}", run)}


@app.post("/graph/search")
async def search_graph(body: GraphSearch, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check(authorization)
    graph = await STORE.graphiti()
    groups = [_group(g) for g in body.groups] or None
    edges = await graph.search(body.query, group_ids=groups, num_results=body.limit)
    return {"facts": [{"fact": e.fact, "relation": e.name, "group": getattr(e, "group_id", None),
                       "valid_from": _when(e.valid_at), "valid_until": _when(e.invalid_at),
                       "no_longer_true": e.invalid_at is not None or e.expired_at is not None,
                       "learned": _when(e.created_at)} for e in edges]}


@app.post("/memories")
async def remember(body: Remember, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check(authorization)

    async def run() -> None:
        memory = await STORE.mem0()
        await asyncio.to_thread(memory.add, [{"role": body.role, "content": body.text}], user_id=body.user,
                                metadata=body.metadata or None)

    return {"queued": True, "position": STORE.enqueue("memory", run)}


@app.post("/memories/search")
async def recall(body: Recall, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check(authorization)
    memory = await STORE.mem0()
    found = await asyncio.to_thread(memory.search, body.query, top_k=body.limit, filters={"user_id": body.user})
    rows = found.get("results", found) if isinstance(found, dict) else found
    return {"memories": [{"id": r.get("id"), "memory": r.get("memory"), "score": r.get("score"),
                          "updated": r.get("updated_at") or r.get("created_at")} for r in rows or []]}


@app.get("/memories")
async def all_memories(user: str = "richard", limit: int = 100,
                       authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check(authorization)
    memory = await STORE.mem0()
    found = await asyncio.to_thread(memory.get_all, filters={"user_id": user}, top_k=max(1, min(limit, 500)))
    rows = found.get("results", found) if isinstance(found, dict) else found
    return {"memories": [{"id": r.get("id"), "memory": r.get("memory"),
                          "updated": r.get("updated_at") or r.get("created_at")} for r in rows or []]}


@app.delete("/memories/{memory_id}")
async def forget(memory_id: str, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check(authorization)
    memory = await STORE.mem0()
    try:
        await asyncio.to_thread(memory.delete, memory_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"deleted": memory_id}
