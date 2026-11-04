"""
JAI Backend - JAI's browser (Wave 6: browser-use)

The client for JAI's browser service (services/browser): a real headless Chromium that agents drive one action at
a time: open a page, read it as a numbered list of what can be clicked, typed into or chosen, then click, type,
choose, scroll, press keys, go back or switch tabs. The agent's own model decides each step (through JAI's router,
inside the daily limit); the service only acts. It opens public pages only, never types into password, card,
bank or one-time-code fields (Richard's hard boundary), runs no scripts in the page and keeps no downloads. Each
mission has its own browser with a fresh profile and no sign-ins.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

ACTIONS = ("open", "read", "click", "type", "select", "options", "scroll", "keys", "back", "find_text",
           "switch_tab", "wait", "close")


class BrowserUnavailable(RuntimeError):
    """The browser is off or not running."""


def browser_url() -> str:
    return str(getattr(settings, "BROWSER_URL", "") or "").rstrip("/")


async def act(session: str, action: str, args: Dict[str, Any],
              client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    base = browser_url()
    if not base:
        raise BrowserUnavailable("JAI's browser is turned off on this computer.")
    if action not in ACTIONS:
        return {"ok": False, "refused": True, "reason": f"Unknown browser action {action}; use {', '.join(ACTIONS)}."}
    if action == "open":
        path, body = "/open", {"session": session, "url": str(args.get("url") or "")}
    elif action == "close":
        path, body = "/close", {"session": session}
    else:
        body = {"session": session, "action": action,
                **{k: args[k] for k in ("index", "text", "clear", "down", "pages", "keys", "tab_id", "seconds")
                   if args.get(k) is not None}}
        path = "/act"
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))
    try:
        response = await client.post(f"{base}{path}", json=body,
                                     headers={"Authorization": f"Bearer {getattr(settings, 'BROWSER_TOKEN', '') or ''}"})
    except httpx.HTTPError as exc:
        raise BrowserUnavailable(f"JAI's browser could not be reached ({type(exc).__name__}). Switch it on under "JAI's services" in the Command Center.") from exc
    finally:
        if owned:
            await client.aclose()
    if response.status_code >= 400:
        raise BrowserUnavailable(f"JAI's browser answered {response.status_code}: {response.text[:200]}")
    return response.json()
