"""JAI's backend, as the voice service reaches it: always as the signed-in operator (his own access token)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/")
BACKEND_ENV_FILE = os.environ.get("BACKEND_ENV_FILE", "/run/jai/backend.env")


def openai_key() -> Optional[str]:
    """The OpenAI key, from the environment or the backend's .env (mounted read-only). Only this key is read."""
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    try:
        for line in Path(BACKEND_ENV_FILE).read_text(encoding="utf-8").splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name.strip() == "OPENAI_API_KEY":
                return value.strip().strip('"').strip("'") or None
    except OSError:
        return None
    return None


class Backend:
    def __init__(self, token: str, base_url: str = BACKEND_URL, client: Optional[httpx.AsyncClient] = None):
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(90.0, connect=5.0),
                                                   headers={"Authorization": f"Bearer {token}"})

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

    async def spend(self, kind: str, **usage: Any) -> Dict[str, Any]:
        try:
            return await self._post("/api/voice/live/spend", {"kind": kind, **usage})
        except httpx.HTTPError as exc:
            return {"error": str(exc)}

    async def close(self) -> None:
        await self._client.aclose()
