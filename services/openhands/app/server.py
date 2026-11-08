"""
JAI's engineering sandbox (OpenHands Software Agent SDK, MIT)

Each of JAI's specialist agents does its work package here: OpenHands' agent loop (with its context condenser,
stuck detection and task tracker) drives a full shell and file editor in this container, on the mission's
workspace folder, thinking with JAI's own model through JAI's gateway (inside the daily spending limit). Every
command and file action is checked by JAI's backend first (app/gate.py), so the mission's scope and JAI's hard
boundaries hold exactly as they do for JAI's own tools.

API (all but /health need the bearer token JAI shares with this service):
  GET  /health                 alive, and how many runs are working
  POST /runs                   start a run: {run_id, workspace, brief, standard, model, max_iterations, ...}
  GET  /runs/{run_id}?since=n  its status, steps, tokens, cost, actions from the n-th on, and its final message
  POST /runs/{run_id}/stop     stop it where it is
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, SecretStr

# The service's secrets are taken out of its environment before anything starts, so no program the agent runs
# can inherit them; the agent's shell also runs as another user, who cannot read this process's environment.
SECRETS = {name: os.environ.pop(name, "") for name in ("OPENHANDS_TOKEN", "JAI_GATEWAY_TOKEN")}
BACKEND_URL = os.environ.get("JAI_BACKEND_URL", "http://backend:8000").rstrip("/")
WORKSPACES = Path(os.environ.get("WORKSPACE_ROOT", "/host/workspaces"))
MAX_RUNS = int(os.environ.get("OPENHANDS_MAX_RUNS", "4"))
KEEP_SECONDS = 3600

from app import gate as gates  # noqa: E402 - after the environment is cleaned
from app import skills as skill_packs  # noqa: E402

logger = logging.getLogger("jai.openhands")
logging.basicConfig(level=logging.INFO)
app = FastAPI(title="JAI engineering sandbox (OpenHands)")


class RunRequest(BaseModel):
    run_id: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    workspace: str
    brief: str = Field(min_length=1)
    standard: str = ""
    model: str = "gpt-6-luna"
    provider: str = Field(default="openai", pattern="^(openai|anthropic)$")
    reasoning_effort: str = "medium"
    max_iterations: int = Field(default=80, ge=5, le=400)
    max_cost_usd: Optional[float] = Field(default=None, gt=0)
    input_cost_per_token: Optional[float] = Field(default=None, ge=0)
    output_cost_per_token: Optional[float] = Field(default=None, ge=0)
    jai_tools: bool = True  # JAI's own capabilities, from its MCP server
    # The skill packs' skills for this specialist ("pack/root/skill" folders under /jai/skills), loaded on demand.
    skills: List[str] = Field(default_factory=list, max_length=80)
    # What cached input costs (US dollars per token): Anthropic and OpenAI charge a tenth for a cache read, so the
    # per-run budget must count it at that price, not at the full input price.
    cache_read_cost_per_token: Optional[float] = Field(default=None, ge=0)
    cache_write_cost_per_token: Optional[float] = Field(default=None, ge=0)


class Run:
    def __init__(self, request: RunRequest, gate: gates.Gate):
        self.request, self.gate = request, gate
        self.status = "starting"  # starting, running, finished, stuck, stopped, error
        self.steps = 0
        self.thought = ""
        self.final_message = ""
        self.error = ""
        self.tokens = {"input": 0, "output": 0, "cached": 0}
        self.cost_usd = 0.0
        self.started_at = time.time()
        self.ended_at: Optional[float] = None
        self.conversation: Any = None
        self.notes = ""

    def on_event(self, event: Any) -> None:
        from openhands.sdk.event import ActionEvent, AgentErrorEvent, MessageEvent

        if isinstance(event, ActionEvent):
            self.steps += 1
            said = " ".join(getattr(t, "text", "") for t in (event.thought or [])).strip()
            if said:
                self.thought = said[-600:]
            message = getattr(event.action, "message", None)
            if event.tool_name == "finish" and isinstance(message, str):
                self.final_message = message
        elif isinstance(event, MessageEvent) and event.source == "agent" and event.llm_message is not None:
            text = " ".join(getattr(c, "text", "") for c in (event.llm_message.content or [])).strip()
            if text:
                self.final_message = text
        elif isinstance(event, AgentErrorEvent):
            self.error = str(getattr(event, "error", "") or "")[:1000]

    def measure(self) -> None:
        try:
            metrics = self.conversation.conversation_stats.get_combined_metrics()
            self.cost_usd = float(metrics.accumulated_cost or 0)
            usage = metrics.accumulated_token_usage
            if usage is not None:
                self.tokens = {"input": int(usage.prompt_tokens or 0), "output": int(usage.completion_tokens or 0),
                               "cached": int(getattr(usage, "cache_read_tokens", 0) or 0)}
        except Exception:  # noqa: BLE001 - figures are a report; the run is not affected
            pass

    def view(self, since: int = 0) -> Dict[str, Any]:
        if self.conversation is not None:
            self.measure()
        return {"run_id": self.request.run_id, "status": self.status, "steps": self.steps,
                "max_iterations": self.request.max_iterations, "doing_now": self.thought,
                "final_message": self.final_message, "error": self.error, "notes": self.notes, "tokens": self.tokens,
                "cost_usd": round(self.cost_usd, 6), "actions": self.gate.actions[since:],
                "action_count": len(self.gate.actions),
                "started_at": datetime.fromtimestamp(self.started_at, timezone.utc).isoformat(timespec="seconds"),
                "seconds": int((self.ended_at or time.time()) - self.started_at)}


RUNS: Dict[str, Run] = {}
_LOCK = threading.Lock()


def _authorised(header: Optional[str]) -> None:
    expected = SECRETS["OPENHANDS_TOKEN"]
    given = (header or "")[7:].strip() if (header or "").lower().startswith("bearer ") else (header or "").strip()
    if not expected or not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="JAI's sandbox token is needed.")


def _inside(path: str) -> Path:
    folder = Path(os.path.normpath(path))
    root = Path(os.path.normpath(str(WORKSPACES)))
    if folder != root and root not in folder.parents:
        raise HTTPException(status_code=400, detail=f"{path} is not inside JAI's workspaces.")
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"{path} is not a folder.")
    return folder


# How JAI's engineers work, for every specialist in the sandbox (after the specialist's own standard).
ENGINEERING_RULES = (
    "JAI'S ENGINEERING RULES. "
    "Tools: when the project needs a tool or a version that is not installed (a pinned Syft, Go, a CLI), install it "
    "yourself at the exact version the project pins, from the official source: `mise install <tool>@<version>` then "
    "`mise exec <tool>@<version> -- <command>`, `uv tool install`, `pnpm add -D`, `npx`. Installing a tool is your "
    "job, never Richard's; never report a missing tool as a blocker or as an action for Richard. "
    "Fresh-clone checks: clone into a new folder under /tmp (git clone <workspace> /tmp/clone-<name>), never inside "
    "the repository, and delete leftover clone folders that earlier runs left inside it. "
    "Long commands: run builds and tests once, to the end, with a timeout long enough for them; never start a "
    "server or a watcher that does not finish. "
    "JAI's knowledge: besides the shell and editor you have JAI's own tools: memory_search and "
    "knowledge_graph_search for what JAI already knows about this workspace, recall_richard for what Richard wants, "
    "consult_specialist_knowledge for reference material in your field, research_web, web_search and fetch_url for "
    "current documentation and fixes, read_document for PDFs and Office files, use_browser to click through a "
    "site, the code_* tools to understand code, read_mission_report for earlier missions. Use them before "
    "guessing, and record decisions and lessons with memory_add. "
    "Skills: the skills listed for you are professional procedures (test-driven development, systematic debugging, "
    "verification, design systems, marketing, editing, launch videos); when one fits the task, call invoke_skill "
    "with its name and follow it, adapted to this mission: you work on your own, so where a skill says to ask your "
    "human partner, decide sensibly yourself and say what you decided in your report. Skip skills for trivial "
    "changes. A skill's own files are read-only under /jai/skills; run its scripts from there. "
    "Video and browser work: ffmpeg and ffprobe are installed, and Chromium is at /usr/bin/chromium (headless, "
    "launch it with --no-sandbox; with Playwright use playwright-core and executablePath /usr/bin/chromium). "
    "Evidence: a requirement is done only when a command in this conversation shows it; report failures exactly. "
    "Only Richard can approve pushing, publishing, deploying, spending money and anything outside this workspace.")


def jai_tools(run_id: str) -> Dict[str, Any]:
    """JAI's MCP server for this run: its knowledge and services, each call checked and recorded by JAI."""
    from openhands.sdk.mcp.config import MCPServer

    return {"jai": MCPServer(url=f"{BACKEND_URL}/api/agent-tools/mcp", transport="streamable-http", timeout=600,
                             headers={"Authorization": SecretStr(f"Bearer {SECRETS['OPENHANDS_TOKEN']}"),
                                      "X-JAI-Run": SecretStr(run_id)})}


def register_prices(provider: str, request: "RunRequest") -> bool:
    """Teach LiteLLM the model's full price list, cache reads and writes included, so the run's spending limit
    counts what the provider really charges. A custom per-token price would bill every cached token at the full
    input price (about five times the real cost of an agent loop) and stop specialists long before their limit."""
    if None in (request.input_cost_per_token, request.output_cost_per_token, request.cache_read_cost_per_token):
        return False
    import litellm

    entry = {"input_cost_per_token": request.input_cost_per_token,
             "output_cost_per_token": request.output_cost_per_token,
             "cache_read_input_token_cost": request.cache_read_cost_per_token,
             "cache_creation_input_token_cost": request.cache_write_cost_per_token or request.input_cost_per_token,
             "litellm_provider": provider, "mode": "chat"}
    try:
        litellm.register_model({f"{provider}/{request.model}": dict(entry), request.model: dict(entry)})
    except Exception as exc:  # noqa: BLE001 - the budget falls back to the plain per-token price
        logger.warning("could not register prices for %s: %s", request.model, exc)
        return False
    return True


def build_conversation(run: Run, with_jai_tools: bool = True):
    """The OpenHands conversation for one run: JAI's model through JAI's gateway, JAI's gated terminal and file
    editor, OpenHands' task tracker and context condenser, the specialist's standard in the system prompt."""
    from openhands.sdk import LLM, Agent, AgentContext, Tool
    from openhands.sdk.context.condenser import default_condenser
    from openhands.sdk.conversation import LocalConversation
    from openhands.tools.task_tracker import TaskTrackerTool

    request = run.request
    key = SecretStr(SECRETS["JAI_GATEWAY_TOKEN"] or "unset")
    common = dict(usage_id="agent", api_key=key, reasoning_effort=request.reasoning_effort, timeout=600,
                  num_retries=4)
    provider = "anthropic" if request.provider == "anthropic" else "openai"
    if not register_prices(provider, request):
        # Without cache prices the budget is counted at the full input price, as before.
        common.update(input_cost_per_token=request.input_cost_per_token,
                      output_cost_per_token=request.output_cost_per_token)
    if request.provider == "anthropic":  # Claude through JAI's gateway, which passes Anthropic's Messages API on
        llm = LLM(model=f"anthropic/{request.model}", base_url=f"{BACKEND_URL}/api/gateway/anthropic/v1/messages",
                  **common)
    else:
        llm = LLM(model=f"openai/{request.model}", base_url=f"{BACKEND_URL}/api/gateway/v1", api_mode="responses",
                  **common)
    agent = Agent(
        llm=llm,
        tools=[Tool(name=gates.TerminalTool.name, params={"jai_run": request.run_id}),
               Tool(name=gates.FileEditorTool.name, params={"jai_run": request.run_id}),
               Tool(name=TaskTrackerTool.name)],
        mcp_config=jai_tools(request.run_id) if with_jai_tools else {},
        system_prompt_kwargs={"cli_mode": True},
        condenser=default_condenser(llm.model_copy(update={"usage_id": "condenser"})),
        agent_context=AgentContext(skills=skill_packs.load(request.skills), system_message_suffix="\n\n".join(
            part for part in (request.standard, ENGINEERING_RULES) if part)))
    # LocalConversation itself: the Conversation shortcut does not take the per-run spending limit.
    return LocalConversation(
        agent=agent, workspace=request.workspace, callbacks=[run.on_event],
        max_iteration_per_run=request.max_iterations, stuck_detection=True, visualizer=None,
        max_budget_per_run=request.max_cost_usd)


def _execute(run: Run) -> None:
    from openhands.sdk.conversation.state import ConversationExecutionStatus

    request = run.request
    try:
        conversation = build_conversation(run, request.jai_tools)
        try:
            conversation._ensure_agent_ready()  # connects to JAI's tools now, so a failure is handled here
        except Exception as exc:  # noqa: BLE001 - the specialist still works, with its shell and editor
            if not request.jai_tools:
                raise
            logger.warning("run %s: JAI's tools could not be reached: %s", request.run_id, exc)
            run.notes = f"JAI's own tools could not be reached ({type(exc).__name__}); worked with shell and editor."
            conversation.close()
            conversation = build_conversation(run, False)
            conversation._ensure_agent_ready()
        run.conversation = conversation
        run.status = "running"
        conversation.send_message(request.brief)
        conversation.run()
        state = conversation.state.execution_status
        if run.status == "stopped":
            pass
        elif state == ConversationExecutionStatus.FINISHED:
            run.status = "finished"
        elif state == ConversationExecutionStatus.STUCK:
            run.status = "stuck"
        elif state == ConversationExecutionStatus.ERROR:
            run.status = "error"
        else:  # the step allowance ran out, or the budget, before the agent finished
            run.status = "stopped"
            run.error = run.error or f"Stopped at its limit ({run.steps} steps) before it said it had finished."
    except Exception as exc:  # noqa: BLE001 - reported to JAI, which carries on with the rest of the mission
        logger.exception("run %s failed", request.run_id)
        run.status, run.error = "error", f"{type(exc).__name__}: {exc}"[:1000]
    finally:
        if run.conversation is not None:
            run.measure()
            try:
                run.conversation.close()
            except Exception:  # noqa: BLE001
                pass
        run.ended_at = time.time()
        run.gate.close()
        gates.GATES.pop(request.run_id, None)


def _prune() -> None:
    now = time.time()
    for run_id in [r for r, run in RUNS.items() if run.ended_at and now - run.ended_at > KEEP_SECONDS]:
        RUNS.pop(run_id, None)


def _active() -> int:
    return sum(1 for run in RUNS.values() if run.ended_at is None)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "runs": _active(), "max_runs": MAX_RUNS,
            "ready": bool(SECRETS["OPENHANDS_TOKEN"] and SECRETS["JAI_GATEWAY_TOKEN"])}


@app.post("/runs")
def start(request: RunRequest, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _authorised(authorization)
    if not SECRETS["JAI_GATEWAY_TOKEN"]:
        raise HTTPException(status_code=503, detail="The sandbox has no gateway token (JAI_GATEWAY_TOKEN in .env).")
    request.workspace = str(_inside(request.workspace))
    with _LOCK:
        _prune()
        if request.run_id in RUNS:
            raise HTTPException(status_code=409, detail=f"Run {request.run_id} exists already.")
        if _active() >= MAX_RUNS:
            raise HTTPException(status_code=429, detail=f"{MAX_RUNS} runs are working already.")
        gate = gates.Gate(BACKEND_URL, SECRETS["OPENHANDS_TOKEN"], request.run_id)
        gates.GATES[request.run_id] = gate
        run = Run(request, gate)
        RUNS[request.run_id] = run
    threading.Thread(target=_execute, args=(run,), name=f"run-{request.run_id}", daemon=True).start()
    return {"run_id": request.run_id, "status": run.status}


@app.get("/runs/{run_id}")
def status(run_id: str, since: int = 0, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _authorised(authorization)
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run {run_id}.")
    return run.view(max(0, since))


@app.post("/runs/{run_id}/stop")
def stop(run_id: str, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _authorised(authorization)
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run {run_id}.")
    if run.ended_at is None:
        run.status = "stopped"
        if run.conversation is not None:
            run.conversation.pause()
    return {"run_id": run_id, "status": run.status}

