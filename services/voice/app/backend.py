"""JAI's backend, as the voice service reaches it: always as the signed-in operator (his own access token)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/")
BACKEND_ENV_FILE = os.environ.get("BACKEND_ENV_FILE", "/run/jai/backend.env")


# The only keys this service reads: OpenAI (speech in, the conversation's model, OpenAI speech) and Fish Audio
# (the selectable British voice, Upgrade 7).
READABLE_KEYS = ("OPENAI_API_KEY", "FISH_API_KEY")


def backend_key(name: str) -> Optional[str]:
    """One of READABLE_KEYS, from the environment or the backend's .env (mounted read-only)."""
    if name not in READABLE_KEYS:
        raise ValueError(f"The voice service does not read {name}")
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in Path(BACKEND_ENV_FILE).read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() == name:
                return value.strip().strip('"').strip("'") or None
    except OSError:
        return None
    return None


def openai_key() -> Optional[str]:
    return backend_key("OPENAI_API_KEY")


def fish_key() -> Optional[str]:
    return backend_key("FISH_API_KEY")


class Backend:
    def __init__(self, token: str, base_url: str = BACKEND_URL, client: Optional[httpx.AsyncClient] = None):
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(90.0, connect=5.0),
                                                   headers={"Authorization": f"Bearer {token}"})

    def use_session(self, token: Optional[str]) -> None:
        """Carry on as the conversation's session token (from the brief): his own sign-in expires after 30 minutes,
        and every later step of a long conversation (live state, screen, missions) failed with "Invalid
        authentication credentials"."""
        if token:
            self._client.headers["Authorization"] = f"Bearer {token}"

    async def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        response = await self._client.post(path, json=body)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text[:300]
            return {"error": str(detail or f"JAI's backend answered {response.status_code}")}
        return response.json()

    async def brief(self) -> Dict[str, Any]:
        """JAI's instructions for this conversation, its tools, the model and voice to use, and today's spend."""
        response = await self._client.get("/api/voice/live/brief")
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text[:300]
            return {"error": str(detail or f"JAI's backend answered {response.status_code}")}
        return response.json()

    async def tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return await self._post("/api/voice/live/tool", {"name": name, "arguments": arguments or {}})

    async def turn(self, who: str, text: str) -> None:
        try:
            await self._post("/api/voice/live/turn", {"who": who, "text": text[:4000]})
        except httpx.HTTPError:
            pass  # remembering a turn never interrupts the conversation

    async def context(self, text: str) -> Dict[str, Any]:
        """JAI's live state as it bears on what Richard just said (missions, progress, reports, approvals, memory,
        knowledge, spend, the date)."""
        try:
            response = await self._client.post("/api/voice/live/context", json={"text": text[:2000]},
                                               timeout=httpx.Timeout(4.0, connect=2.0))
            return response.json() if response.status_code < 400 else {"error": response.text[:200]}
        except (httpx.HTTPError, ValueError) as exc:
            return {"error": str(exc)}

    async def spend(self, kind: str, **usage: Any) -> Dict[str, Any]:
        try:
            return await self._post("/api/voice/live/spend", {"kind": kind, **usage})
        except httpx.HTTPError as exc:
            return {"error": str(exc)}

    async def close(self) -> None:
        await self._client.aclose()
