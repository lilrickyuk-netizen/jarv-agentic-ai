"""
JAI Backend - JAI's knowledge graph and its memory of Richard (Wave 6: Graphiti and Mem0)

The client for JAI's knowledge service (services/knowledge). Graphiti keeps what JAI learns from its work as facts
that know when they became true and when they stopped being true, one graph per workspace: every finished
mission's report is added, and agents can add and search facts. Mem0 keeps what Richard tells JAI about himself
and how he wants things done, from what he says to the voice; missions and the voice are given what bears on the
moment. Additions are queued in the service (they need the model, through JAI's gateway); searches answer at once
and are given a short time limit, so a slow or stopped service never holds up a reply or a mission.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RICHARD = "richard"


class KnowledgeUnavailable(RuntimeError):
    """The knowledge service is off, not running, or could not answer."""


def knowledge_url() -> str:
    return str(getattr(settings, "KNOWLEDGE_URL", "") or "").rstrip("/")


def enabled() -> bool:
    return bool(knowledge_url())


def group(workspace_id: Any) -> str:
    return "ws-" + str(workspace_id).replace("-", "")[:32]


async def _call(method: str, path: str, body: Optional[Dict[str, Any]] = None, timeout: float = 10.0,
                client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    base = knowledge_url()
    if not base:
        raise KnowledgeUnavailable("JAI's knowledge service is turned off on this computer.")
    headers = {"Authorization": f"Bearer {getattr(settings, 'KNOWLEDGE_TOKEN', '') or ''}"}
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=3.0))
    try:
        response = await client.request(method, f"{base}{path}", json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise KnowledgeUnavailable(f"JAI's knowledge service could not be reached ({type(exc).__name__}).") from exc
    finally:
        if owned:
            await client.aclose()
    if response.status_code >= 400:
        raise KnowledgeUnavailable(f"JAI's knowledge service answered {response.status_code}: {response.text[:200]}")
    return response.json()


async def add_episode(workspace_id: Any, name: str, body: str, source: str = "JAI",
                      reference_time: Optional[datetime] = None, **kw) -> Dict[str, Any]:
    payload = {"group": group(workspace_id), "name": name[:200], "body": body[:60000], "source": source[:200]}
    if reference_time:
        payload["reference_time"] = reference_time.isoformat()
    return await _call("POST", "/graph/episodes", payload, **kw)


async def search_graph(query: str, workspace_ids: List[Any], limit: int = 10, **kw) -> List[Dict[str, Any]]:
    answer = await _call("POST", "/graph/search", {"query": query[:2000], "groups": [group(w) for w in workspace_ids][:50],
                                                   "limit": max(1, min(limit, 50))}, **kw)
    return list(answer.get("facts") or [])


async def remember(text: str, role: str = "user", metadata: Optional[Dict[str, Any]] = None, **kw) -> Dict[str, Any]:
    return await _call("POST", "/memories", {"text": text[:20000], "user": RICHARD, "role": role,
                                             "metadata": metadata or {}}, **kw)


async def recall(query: str, limit: int = 8, **kw) -> List[Dict[str, Any]]:
    answer = await _call("POST", "/memories/search", {"query": query[:2000], "user": RICHARD,
                                                      "limit": max(1, min(limit, 50))}, **kw)
    return [m for m in answer.get("memories") or [] if m.get("memory")]


async def memories(limit: int = 100, **kw) -> List[Dict[str, Any]]:
    return list((await _call("GET", f"/memories?user={RICHARD}&limit={max(1, min(limit, 500))}", **kw)).get("memories") or [])


async def forget(memory_id: str, **kw) -> Dict[str, Any]:
    return await _call("DELETE", f"/memories/{memory_id}", **kw)


async def health(**kw) -> Dict[str, Any]:
    return await _call("GET", "/health", **kw)


async def quietly(coro, default):
    """A lookup that must never hold up or break the caller: its answer, or ``default`` (logged)."""
    try:
        return await coro
    except KnowledgeUnavailable as exc:
        logger.info("knowledge: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("knowledge lookup failed: %s", exc)
    return default
