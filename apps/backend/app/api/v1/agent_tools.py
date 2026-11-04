"""
JAI Backend - JAI's capabilities for the specialists in its engineering sandbox (an MCP server)

OpenHands takes extra tools from MCP servers; this is JAI's. A specialist in the sandbox gets, beside its shell and
file editor, everything JAI knows and can do: its memory and knowledge graph, what Richard has said he wants, the
specialist knowledge library and source documentation, web search and cited research, page and document reading,
the browser, code understanding (Serena), package and CVE checks, earlier mission reports, and the image, voice,
video and social-draft makers. Each call runs through JAI's own toolbox for the mission's workspace, at the run's
authority (never more than its lead's), and is recorded like every other action; the independent Verifier's run
may look but not add.

POST /api/agent-tools/mcp   MCP over streamable HTTP (JSON answers), with JAI's sandbox token and the run's id in
                            X-JAI-Run. GET and DELETE answer 405: there is no server-sent stream and no session.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response

from app.api.v1.agent_gate import _authorised
from app.core.command import sandbox_engine
from app.core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent-tools", tags=["agent-tools"])

# What the sandbox's own terminal and editor do not give: JAI's knowledge and its services.
JAI_TOOLS = (
    "memory_search", "memory_add", "knowledge_graph_search", "knowledge_graph_add", "recall_richard",
    "consult_specialist_knowledge", "trace_artifact", "read_mission_report", "web_search", "research_web",
    "fetch_url", "read_document", "use_browser", "code_overview", "code_find_symbol", "code_references",
    "code_implementations", "code_diagnostics", "check_package_registry", "check_cve", "asset_licence_check",
    "run_prompt_checks", "generate_image", "make_voiceover", "make_video", "social_channels", "social_draft",
)
# Tools that add something: not for the independent Verifier, which only looks and tests.
ADDS = {"memory_add", "knowledge_graph_add", "generate_image", "make_voiceover", "make_video", "social_draft"}
RESULT_CHARS = 30000
PROTOCOL = "2025-06-18"


def _answer(request_id: Any, result: Optional[Dict[str, Any]] = None, error: Optional[Dict[str, Any]] = None,
            headers: Optional[Dict[str, str]] = None) -> JSONResponse:
    body: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    body.update({"error": error} if error else {"result": result or {}})
    return JSONResponse(body, headers=headers)


def _relative(value: Any, root: str) -> Any:
    """Paths as the sandbox sees them (/host/workspaces/MYCO/docs/x.md) become the workspace's own (docs/x.md)."""
    if isinstance(value, str) and root and (value == root or value.startswith(root.rstrip("/") + "/")):
        return value[len(root):].lstrip("/") or "."
    if isinstance(value, dict):
        return {k: _relative(v, root) for k, v in value.items()}
    if isinstance(value, list):
        return [_relative(v, root) for v in value]
    return value


async def _toolbox(db, run: Dict[str, Any]):
    from app.core.command.agent_executor import mission_toolbox
    from app.core.command.tool_runtime import ToolRuntime

    runtime = ToolRuntime(db, UUID(run["workspace_id"]), UUID(run["task_id"]) if run.get("task_id") else None,
                          operator=f"agent:{run.get('specialist')}", authority_level=int(run.get("authority") or 0),
                          user_id=UUID(run["user_id"]) if run.get("user_id") else None)
    runtime.pause_task_on_boundary = False
    toolbox = mission_toolbox(runtime, run.get("root_host"))
    await toolbox.prepare()
    return toolbox


def _offered(toolbox, run: Dict[str, Any]) -> List[Dict[str, Any]]:
    tools = []
    for spec in toolbox.model_tools():
        name = spec["name"]
        if name not in JAI_TOOLS or (run.get("read_only") and name in ADDS):
            continue
        tools.append({"name": name, "description": f"JAI: {spec['description']} Paths are relative to the "
                                                   "workspace folder.",
                      "inputSchema": spec.get("input_schema") or {"type": "object", "properties": {}}})
    return tools


@router.post("/mcp")
async def mcp(request: Request, _: None = Depends(_authorised), x_jai_run: Optional[str] = Header(default=None),
              db=Depends(get_db)) -> Response:
    try:
        message = await request.json()
    except ValueError:
        return _answer(None, error={"code": -32700, "message": "Not JSON."})
    if not isinstance(message, dict):
        return _answer(None, error={"code": -32600, "message": "One JSON-RPC message per request."})
    method, request_id, params = message.get("method"), message.get("id"), message.get("params") or {}
    if request_id is None:  # a notification (notifications/initialized and the like)
        return Response(status_code=202)
    if method == "initialize":
        return _answer(request_id, {
            "protocolVersion": str(params.get("protocolVersion") or PROTOCOL),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "jai", "version": "1.0"},
            "instructions": ("JAI's own capabilities: its memory and knowledge graph, Richard's wishes, specialist "
                             "knowledge and documentation, research, documents, the browser, code understanding "
                             "and media. Use them before guessing.")})
    if method == "ping":
        return _answer(request_id, {})
    run = await sandbox_engine.load_run(x_jai_run or "") if x_jai_run else None
    if run is None or not run.get("workspace_id"):
        if method == "tools/list":
            return _answer(request_id, {"tools": []})
        return _answer(request_id, error={"code": -32001, "message": "JAI has no record of this sandbox run."})
    if method == "tools/list":
        try:
            toolbox = await _toolbox(db, run)
        except Exception as exc:  # noqa: BLE001 - no workspace record: the sandbox works with its own tools
            logger.warning(f"JAI's tools not offered to sandbox run {x_jai_run}: {exc}")
            return _answer(request_id, {"tools": []})
        return _answer(request_id, {"tools": _offered(toolbox, run)})
    if method == "tools/call":
        name = str(params.get("name") or "")
        if name not in JAI_TOOLS or (run.get("read_only") and name in ADDS):
            return _answer(request_id, {"content": [{"type": "text", "text": f"{name} is not one of JAI's tools for "
                                                                             "this run."}], "isError": True})
        toolbox = await _toolbox(db, run)
        out = await toolbox.call(name, _relative(params.get("arguments") or {}, str(run.get("root") or "")))
        await db.commit()
        failed = isinstance(out, dict) and (out.get("success") is False or bool(out.get("blocked")))
        text = json.dumps(out, default=str)
        return _answer(request_id, {"content": [{"type": "text", "text": text[:RESULT_CHARS]}], "isError": failed})
    return _answer(request_id, error={"code": -32601, "message": f"JAI's tool server does not offer {method}."})


@router.get("/mcp")
async def no_stream(_: None = Depends(_authorised)) -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
async def no_session(_: None = Depends(_authorised)) -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})
