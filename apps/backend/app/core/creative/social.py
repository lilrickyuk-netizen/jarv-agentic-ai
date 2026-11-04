"""
JAI Backend - Social posts through Postiz (Wave 4d)

Postiz (open source, AGPL-3.0) runs on Richard's computer and holds his social accounts, which he connects himself
(signing in is his). JAI reads which channels are connected and writes posts into Postiz as drafts, with their
images or videos attached. It never schedules or publishes: posting publicly from his accounts is a hard
boundary, so every draft waits in Postiz until he schedules it himself.
Setup: open http://localhost:4007, create the account, connect channels, then Settings > Public API: put the key
in apps/backend/.env as POSTIZ_API_KEY and restart the backend.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx


class SocialUnavailable(RuntimeError):
    """Postiz is not running, not set up, or refused the request."""


def _config():
    from app.core.config import settings

    base = str(getattr(settings, "POSTIZ_URL", "") or "").rstrip("/")
    key = getattr(settings, "POSTIZ_API_KEY", None)
    if not base:
        raise SocialUnavailable("Social scheduling (Postiz) is turned off on this computer.")
    if not key:
        raise SocialUnavailable("Postiz is not connected yet: open http://localhost:4007, create the account and "
                                "connect your channels, then put the key from Settings > Public API in "
                                "apps/backend/.env as POSTIZ_API_KEY and restart the backend.")
    return base, key


async def _call(method: str, path: str, client: Optional[httpx.AsyncClient] = None, **kwargs) -> Any:
    base, key = _config()
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
    try:
        try:
            response = await client.request(method, f"{base}/public/v1{path}", headers={"Authorization": key},
                                            **kwargs)
        except httpx.HTTPError as exc:
            raise SocialUnavailable(f"Postiz could not be reached ({type(exc).__name__}).") from exc
        if response.status_code >= 400:
            raise SocialUnavailable(f"Postiz answered {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else {}
    finally:
        if own:
            await client.aclose()


async def channels(client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
    """The social channels Richard has connected in Postiz."""
    found = await _call("GET", "/integrations", client)
    return [{"id": c.get("id"), "name": c.get("name"), "platform": c.get("identifier"),
             "disabled": bool(c.get("disabled"))} for c in found or []]


async def upload(name: str, data: bytes, content_type: str, client: Optional[httpx.AsyncClient] = None) -> Dict:
    return await _call("POST", "/upload", client, files={"file": (name, data, content_type)})


def draft_body(text: str, channel_ids: List[str], platforms: Dict[str, str], media: List[Dict[str, Any]],
               when: Optional[datetime] = None) -> Dict[str, Any]:
    """A Postiz post of type draft (never schedule or now) for each chosen channel."""
    when = when or (datetime.now(timezone.utc) + timedelta(days=1))
    return {"type": "draft", "shortLink": False, "tags": [], "date": when.isoformat(timespec="seconds"),
            "posts": [{"integration": {"id": cid},
                       "value": [{"content": text, "image": [{"id": m.get("id"), "path": m.get("path")}
                                                             for m in media]}],
                       "settings": {"__type": platforms.get(cid, "")}} for cid in channel_ids]}


async def draft(text: str, channel_names: Optional[List[str]] = None, media: Optional[List[Dict[str, Any]]] = None,
                client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """Draft a post in Postiz for the named channels (all connected ones when none are named)."""
    text = (text or "").strip()
    if not text:
        raise SocialUnavailable("The post is empty.")
    connected = [c for c in await channels(client) if not c["disabled"]]
    if not connected:
        raise SocialUnavailable("No social channel is connected in Postiz yet: connect one at http://localhost:4007.")
    wanted = {n.lower() for n in channel_names or []}
    chosen = [c for c in connected if not wanted or c["name"].lower() in wanted or (c["platform"] or "").lower() in wanted]
    if not chosen:
        raise SocialUnavailable(f"None of those channels is connected: {', '.join(c['name'] for c in connected)}.")
    body = draft_body(text, [c["id"] for c in chosen], {c["id"]: c["platform"] or "" for c in chosen}, media or [])
    created = await _call("POST", "/posts", client, json=body)
    return {"drafted": True, "channels": [c["name"] for c in chosen], "postiz": created,
            "note": "Saved as a draft in Postiz; nothing is published until Richard schedules it there."}
