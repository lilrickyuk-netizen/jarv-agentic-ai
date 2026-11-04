"""
JAI's browser (Wave 6): browser-use (MIT) driving a real headless Chromium, for JAI's agents.

browser-use is used for what it does best: reading a live page as a numbered list of the things on it that can be
clicked, typed into or chosen (its DOM serializer), and carrying out actions on them reliably (its tools). It never
calls an AI model here: JAI's own agent, through JAI's router and inside the daily spending limit, reads the page
and decides what to do next, one action at a time.

Safety, enforced here whatever the caller asks:
- only public http(s) pages: localhost, private, link-local and reserved addresses (JAI's own services, Richard's
  network) are refused, before and after every action;
- nothing is typed into a password, payment-card, bank, one-time-code or security-answer field: entering those is
  Richard's hard boundary;
- no file uploads, no scripts run in the page, no downloads kept;
- every session is a fresh profile with no sign-ins, closed after ten idle minutes, at most MAX_SESSIONS at once.
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import logging
import os
import re
import socket
import tempfile
import time
import urllib.parse
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("jai.browser")
app = FastAPI(title="JAI browser")

TOKEN = os.environ.get("BROWSER_TOKEN", "")
MAX_SESSIONS = int(os.environ.get("BROWSER_MAX_SESSIONS", "2"))
IDLE_SECONDS = int(os.environ.get("BROWSER_IDLE_SECONDS", "600"))
STATE_CHARS = int(os.environ.get("BROWSER_STATE_CHARS", "15000"))
ACTION_SECONDS = 45.0
SETTLE_SECONDS = float(os.environ.get("BROWSER_SETTLE_SECONDS", "10"))
# Also refused by browser-use itself (its security watchdog), as a second lock behind public_url.
PROHIBITED = ("localhost", "127.0.0.1", "backend", "worker", "searxng", "crawl4ai", "moneyprinter", "postgres",
              "redis", "browser", "knowledge", "docling", "promptfoo", "serena", "chatterbox", "comfyui", "postiz")

# JAI action -> browser-use action and the parameters it takes.
ACTIONS = {
    "click": ("click", ("index",)),
    "type": ("input", ("index", "text", "clear")),
    "select": ("select_dropdown", ("index", "text")),
    "options": ("dropdown_options", ("index",)),
    "scroll": ("scroll", ("down", "pages", "index")),
    "keys": ("send_keys", ("keys",)),
    "back": ("go_back", ()),
    "find_text": ("find_text", ("text",)),
    "switch_tab": ("switch", ("tab_id",)),
    "wait": ("wait", ("seconds",)),
}
# Words that mark a field Richard fills in himself: passwords, payment cards, bank details, one-time codes,
# security answers and wallet secrets.
_SECRET = re.compile(r"(?<![a-z])(password|passwd|passcode|pin|pincode|cvv|cvc|csc|iban|bic|swift|otp|2fa|mfa|"
                     r"card ?number|card-number|cardnumber|cc-?(number|csc|exp)|expiry|security (code|answer)|"
                     r"sort ?code|sort-code|account ?number|account-number|routing|one[- ]time|verification code|"
                     r"seed ?phrase|mnemonic|private ?key|recovery phrase)(?![a-z])")
_SECRET_AUTOCOMPLETE = ("current-password", "new-password", "one-time-code", "cc-number", "cc-csc", "cc-exp",
                        "cc-exp-month", "cc-exp-year", "cc-name", "cc-type")


class Refused(Exception):
    def __init__(self, reason: str, boundary: bool = False):
        super().__init__(reason)
        self.reason, self.boundary = reason, boundary


def public_url(url: str) -> Optional[str]:
    """None if the address is a public http(s) page, otherwise why not."""
    try:
        parts = urllib.parse.urlparse(url)
    except ValueError:
        return "That is not a web address."
    if parts.scheme not in ("http", "https"):
        return f"Only http and https pages are opened, not {parts.scheme or 'that'}."
    host = (parts.hostname or "").lower()
    if not host:
        return "The address has no host."
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal") or "." not in host:
        return "Addresses on this computer or its private network are not opened."
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return None  # it will fail to load and say so
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return f"{host} is a private address ({ip}); only public pages are opened."
    return None


def secret_field(node: Any) -> Optional[str]:
    """Why typing into this element would cross a hard boundary, or None."""
    attrs = {str(k).lower(): str(v).lower() for k, v in (getattr(node, "attributes", None) or {}).items()}
    if attrs.get("type") == "password":
        return "a password field"
    if attrs.get("autocomplete", "") in _SECRET_AUTOCOMPLETE:
        return f"a {attrs['autocomplete']} field"
    said = " ".join(attrs.get(k, "") for k in ("name", "id", "autocomplete", "aria-label", "placeholder",
                                               "data-testid", "title", "label"))
    said = re.sub(r"[_\s]+", " ", said)
    found = _SECRET.search(said)
    return f"a field for {found.group(1)}" if found else None


class Session:
    def __init__(self, key: str):
        self.key, self.used, self.browser, self.tools = key, time.monotonic(), None, None
        self.lock = asyncio.Lock()

    async def start(self) -> None:
        from browser_use import BrowserSession
        from browser_use.tools.service import Tools

        self.browser = BrowserSession(
            headless=True, chromium_sandbox=False, keep_alive=True, accept_downloads=False,
            enable_default_extensions=False,  # no ad-blocker or cookie extensions fetched from the web
            user_data_dir=tempfile.mkdtemp(prefix="jai-browser-"),
            prohibited_domains=list(PROHIBITED))
        await self.browser.start()
        self.tools = Tools(exclude_actions=["upload_file", "evaluate", "extract", "save_as_pdf", "read_file",
                                            "replace_file", "write_file", "screenshot", "done"])

    async def close(self) -> None:
        if self.browser is not None:
            try:
                await self.browser.kill()
            except Exception as exc:  # noqa: BLE001
                log.warning("closing %s: %s", self.key, exc)
        self.browser = None

    async def _settled(self):
        """The page once it has finished loading: its document arrived, it has a title of its own or something to
        use on it, and nothing it needs is still downloading; at most SETTLE_SECONDS, then as it is."""
        deadline = time.monotonic() + SETTLE_SECONDS
        while True:
            summary = await asyncio.wait_for(self.browser.get_browser_state_summary(include_screenshot=False),
                                             timeout=ACTION_SECONDS)
            host = urllib.parse.urlparse(summary.url or "").netloc
            titled = bool(summary.title) and summary.title not in (host, summary.url)
            usable = bool(summary.dom_state.selector_map) or titled
            loading = [r for r in summary.pending_network_requests or []
                       if (r.resource_type or "") in ("Document", "Script", "Stylesheet", "XHR", "Fetch")]
            if (usable and not loading) or (summary.url or "").startswith("about:") or time.monotonic() > deadline:
                return summary
            await asyncio.sleep(0.4)

    async def state(self) -> Dict[str, Any]:
        summary = await self._settled()
        problem = public_url(summary.url) if summary.url and not summary.url.startswith("about:") else None
        if problem:
            await self.act_raw("navigate", {"url": "about:blank"})
            raise Refused(f"The page went to an address JAI does not open: {problem}")
        page = summary.dom_state.llm_representation()
        return {"url": summary.url, "title": summary.title,
                "tabs": [{"tab_id": t.target_id[-4:], "url": t.url, "title": t.title} for t in summary.tabs],
                "above_px": summary.pixels_above, "below_px": summary.pixels_below,
                "elements": len(summary.dom_state.selector_map or {}),
                "page": page[:STATE_CHARS], "page_truncated": len(page) > STATE_CHARS,
                "errors": list(summary.browser_errors or [])[:5]}

    async def act_raw(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        result = await asyncio.wait_for(
            self.tools.registry.execute_action(name, params, browser_session=self.browser), timeout=ACTION_SECONDS)
        return {"error": getattr(result, "error", None),
                "said": getattr(result, "extracted_content", None) or getattr(result, "long_term_memory", None)}

    async def node(self, index: int) -> Any:
        summary = await self.browser.get_browser_state_summary(include_screenshot=False, cached=True)
        found = (summary.dom_state.selector_map or {}).get(int(index))
        if found is None:
            raise Refused(f"There is no element {index} on the page now; read the page again.")
        return found


SESSIONS: Dict[str, Session] = {}
_GUARD = asyncio.Lock()


async def _session(key: str, create: bool) -> Session:
    async with _GUARD:
        now = time.monotonic()
        for stale in [k for k, s in SESSIONS.items() if now - s.used > IDLE_SECONDS]:
            await SESSIONS.pop(stale).close()
        found = SESSIONS.get(key)
        if found is None:
            if not create:
                raise Refused("No page is open in this mission's browser; open one first.")
            if len(SESSIONS) >= MAX_SESSIONS:
                oldest = min(SESSIONS, key=lambda k: SESSIONS[k].used)
                await SESSIONS.pop(oldest).close()
            found = Session(key)
            await found.start()
            SESSIONS[key] = found
        found.used = now
        return found


def _check(authorization: Optional[str]) -> None:
    given = (authorization or "")[7:] if (authorization or "").lower().startswith("bearer ") else (authorization or "")
    if not TOKEN or not hmac.compare_digest(given.encode(), TOKEN.encode()):
        raise HTTPException(401, "Not JAI's browser token.")


class Open(BaseModel):
    session: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=4, max_length=2000)


class Act(BaseModel):
    session: str = Field(min_length=1, max_length=80)
    action: str
    index: Optional[int] = None
    text: Optional[str] = Field(default=None, max_length=5000)
    clear: Optional[bool] = None
    down: Optional[bool] = None
    pages: Optional[float] = None
    keys: Optional[str] = Field(default=None, max_length=100)
    tab_id: Optional[str] = Field(default=None, max_length=8)
    seconds: Optional[int] = Field(default=None, ge=1, le=10)


def _refusal(exc: Refused) -> Dict[str, Any]:
    return {"ok": False, "refused": True, "boundary": exc.boundary, "reason": exc.reason}


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"ok": True, "sessions": len(SESSIONS), "max_sessions": MAX_SESSIONS}


@app.post("/open")
async def open_page(body: Open, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check(authorization)
    problem = public_url(body.url)
    if problem:
        return _refusal(Refused(problem))
    try:
        session = await _session(body.session, create=True)
        async with session.lock:
            done = await session.act_raw("navigate", {"url": body.url})
            state = await session.state()
    except Refused as exc:
        return _refusal(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("open %s", body.url)
        return {"ok": False, "reason": f"The page could not be opened: {type(exc).__name__}: {str(exc)[:300]}"}
    return {"ok": not done["error"], "error": done["error"], **state}


@app.post("/act")
async def act(body: Act, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check(authorization)
    if body.action == "read":
        names = ()
    elif body.action not in ACTIONS:
        return _refusal(Refused(f"Unknown action {body.action}; use read, {', '.join(ACTIONS)}."))
    else:
        names = ACTIONS[body.action][1]
    try:
        session = await _session(body.session, create=False)
        async with session.lock:
            done = {"error": None, "said": None}
            if body.action != "read":
                name = ACTIONS[body.action][0]
                params = {k: getattr(body, k) for k in names if getattr(body, k) is not None}
                if "index" in names and "index" not in params and body.action not in ("scroll",):
                    raise Refused(f"{body.action} needs the number of the element on the page.")
                if body.action == "type":
                    why = secret_field(await session.node(body.index))
                    if why:
                        raise Refused(f"Element {body.index} is {why}. Entering passwords, card or bank details "
                                      f"is Richard's to do himself; JAI never types them.", boundary=True)
                if body.action == "switch_tab" and body.tab_id:
                    params = {"tab_id": body.tab_id}
                done = await session.act_raw(name, params)
            state = await session.state()
    except Refused as exc:
        return _refusal(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("act %s", body.action)
        return {"ok": False, "reason": f"{body.action} did not work: {type(exc).__name__}: {str(exc)[:300]}"}
    return {"ok": not done["error"], "error": done["error"], "said": (done["said"] or "")[:2000] or None, **state}


class Close(BaseModel):
    session: str = Field(min_length=1, max_length=80)


@app.post("/close")
async def close(body: Close, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check(authorization)
    async with _GUARD:
        found = SESSIONS.pop(body.session, None)
    if found:
        await found.close()
    return {"ok": True, "closed": bool(found)}
