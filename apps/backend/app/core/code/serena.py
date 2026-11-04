"""
JAI Backend - Serena, JAI's code understanding (Wave 5)

Serena (open source, MIT) answers questions about a codebase through language servers, as an IDE would: what is in a
file, where a symbol is defined and its body, who uses it, its implementations and declaration, and the
diagnostics (errors and warnings) a file has. It runs as an MCP server; this is a small MCP client for its
streamable HTTP transport (JSON-RPC over HTTP, answers as JSON or server-sent events). Only Serena's read-only
tools are used: every change still goes through JAI's own confined, recorded edit tools.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

import httpx

PROTOCOL = "2025-06-18"
# JAI tool name -> Serena tool name. Read-only only.
TOOLS = {"code_overview": "get_symbols_overview", "code_find_symbol": "find_symbol",
         "code_references": "find_referencing_symbols", "code_implementations": "find_implementations", "code_diagnostics": "get_diagnostics_for_file"}


class CodeUnavailable(RuntimeError):
    """Serena is not running or could not answer."""


def serena_url() -> str:
    from app.core.config import settings

    return str(getattr(settings, "SERENA_URL", "") or "").rstrip("/")


def _parse(response: httpx.Response) -> Dict[str, Any]:
    """A JSON-RPC answer, sent as JSON or as server-sent events."""
    kind = response.headers.get("content-type", "")
    if "text/event-stream" in kind:
        last: Dict[str, Any] = {}
        for line in response.text.splitlines():
            if line.startswith("data:"):
                try:
                    last = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if "result" in last or "error" in last:
                    return last
        return last
    return response.json() if response.content else {}


class SerenaClient:
    def __init__(self, base: str, client: Optional[httpx.AsyncClient] = None):
        self.base = base.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0))
        self.session: Optional[str] = None
        self.project: Optional[str] = None
        self.lock = asyncio.Lock()
        self._id = 0

    async def _post(self, body: Dict[str, Any]) -> httpx.Response:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                   "MCP-Protocol-Version": PROTOCOL}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        try:
            return await self.client.post(f"{self.base}/mcp", headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise CodeUnavailable(f"JAI's code understanding (Serena) could not be reached ({type(exc).__name__}).") from exc

    async def _rpc(self, method: str, params: Dict[str, Any]) -> Any:
        self._id += 1
        response = await self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        if response.status_code in (400, 404) and self.session:
            self.session = None  # the server forgot the session: start again once
            await self._initialise()
            response = await self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        if response.status_code >= 400:
            raise CodeUnavailable(f"Serena answered {response.status_code}: {response.text[:200]}")
        answer = _parse(response)
        if answer.get("error"):
            raise CodeUnavailable(f"Serena: {answer['error'].get('message')}")
        return answer.get("result")

    async def _initialise(self) -> None:
        self._id += 1
        response = await self._post({"jsonrpc": "2.0", "id": self._id, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "jai", "version": "1"}}})
        if response.status_code >= 400:
            raise CodeUnavailable(f"Serena would not start a session: {response.status_code} {response.text[:200]}")
        self.session = response.headers.get("mcp-session-id") or self.session
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.project = None

    async def call(self, project: str, tool: str, arguments: Dict[str, Any]) -> str:
        """Run one Serena tool for the project at this container path; the answer as text."""
        async with self.lock:  # Serena works on one project at a time
            if not self.session:
                await self._initialise()
            if self.project != project:
                await self._rpc("tools/call", {"name": "activate_project", "arguments": {"project": project}})
                self.project = project
            result = await self._rpc("tools/call", {"name": tool, "arguments": arguments}) or {}
        text = "\n".join(str(part.get("text", "")) for part in result.get("content") or [] if isinstance(part, dict))
        if result.get("isError"):
            raise CodeUnavailable(text[:500] or "Serena could not answer that.")
        return text


_client: Dict[str, SerenaClient] = {}


def client() -> SerenaClient:
    base = serena_url()
    if not base:
        raise CodeUnavailable("JAI's code understanding (Serena) is turned off on this computer.")
    if base not in _client:
        _client[base] = SerenaClient(base)
    return _client[base]


def arguments(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """JAI's tool arguments as Serena's (paths relative to the project root)."""
    path = str(args.get("path") or "").replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    path = path.lstrip("/")
    if ".." in path.split("/"):
        raise CodeUnavailable("Code paths stay inside the workspace.")
    if tool in ("code_overview", "code_diagnostics") and not path:
        raise CodeUnavailable("Give the path of a source file in the workspace.")
    if tool != "code_overview" and tool != "code_diagnostics" and not str(args.get("symbol") or "").strip():
        raise CodeUnavailable("Give the name of the symbol, for example MyClass or MyClass/method.")
    if tool == "code_overview":
        return {"relative_path": path, "depth": 1}
    if tool == "code_find_symbol":
        return {"name_path_pattern": str(args.get("symbol") or ""), "relative_path": path,
                "include_body": bool(args.get("include_body")), "substring_matching": True, "depth": 0}
    if tool in ("code_references", "code_implementations"):
        return {"name_path": str(args.get("symbol") or ""), "relative_path": path}
    if tool == "code_diagnostics":
        return {"relative_path": path}
    raise CodeUnavailable(f"Unknown code tool {tool}.")
