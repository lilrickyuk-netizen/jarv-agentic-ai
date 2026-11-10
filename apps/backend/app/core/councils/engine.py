"""
JAI Backend - The workflow engine, on LangGraph

Each workflow template becomes a LangGraph StateGraph. A mission step is two nodes: one starts the mission (in its
own node, so it is never started twice when the graph resumes), the next pauses with LangGraph's interrupt() until
the mission has finished and is resumed with how it went. A gate is the same: one node opens an approval on the
Approvals page, the next pauses until Richard approves or rejects it. A failed or cancelled mission, or a rejected
gate, ends the workflow with the reason; a partial mission (research that found fewer than its target) goes on.

The graph's state is kept by LangGraph's Postgres checkpointer under the run's id (thread_id), so a workflow waits
hours or days, across restarts, and carries on from where it paused. What actually starts a mission or opens a gate
is passed in (Ports), so the graph can be tested with an in-memory checkpointer and no missions.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

# How a finished mission lets the workflow go on: done, or done with gaps (one-round research short of a target).
GOES_ON = frozenset({"completed", "partial"})


class FlowState(TypedDict, total=False):
    run_id: str
    template: str
    product: str
    folder: str
    workspace_id: str
    user_id: str
    tasks: Dict[str, str]                 # step id -> the mission or gate task it started
    results: Dict[str, Dict[str, Any]]    # step id -> how it went
    stopped: Optional[str]                # why the workflow ended early


@dataclass
class Ports:
    """What the graph does in the world: start a mission (returns its task id) and open an approval gate (returns
    the gate's task id). Each is called once per step."""
    start_mission: Callable[[FlowState, Dict[str, Any]], Awaitable[str]]
    open_gate: Callable[[FlowState, Dict[str, Any]], Awaitable[str]]


def _next(after: str, following: str):
    """After a waiting node: the next step, or the end when the workflow was stopped."""
    from langgraph.graph import END

    def route(state) -> str:
        return END if state.get("stopped") else following
    route.__name__ = f"after_{after}"
    return route


def build(steps: List[Dict[str, Any]], ports: Ports):
    """The workflow's graph: start/wait pairs for missions, open/decide pairs for gates, in order."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    graph = StateGraph(FlowState)
    entries: List[str] = []
    exits: List[str] = []
    for step in steps:
        sid = step["id"]
        if step.get("gate"):
            first, second = f"open_{sid}", f"decide_{sid}"

            async def open_gate(state, step=step):
                gate_id = await ports.open_gate(state, step)
                return {"tasks": {**(state.get("tasks") or {}), step["id"]: gate_id}}

            async def decide(state, step=step):
                gate_id = (state.get("tasks") or {}).get(step["id"])
                answer = interrupt({"kind": "gate", "step": step["id"], "task_id": gate_id, "title": step["title"]})
                approved = bool((answer or {}).get("approved"))
                results = {**(state.get("results") or {}),
                           step["id"]: {"status": "approved" if approved else "rejected",
                                        "note": (answer or {}).get("note")}}
                update: Dict[str, Any] = {"results": results}
                if not approved:
                    update["stopped"] = f"Richard stopped the workflow at “{step['title']}”."
                return update

            graph.add_node(first, open_gate)
            graph.add_node(second, decide)
        else:
            first, second = f"start_{sid}", f"wait_{sid}"

            async def start(state, step=step):
                task_id = await ports.start_mission(state, step)
                return {"tasks": {**(state.get("tasks") or {}), step["id"]: task_id}}

            async def wait(state, step=step):
                task_id = (state.get("tasks") or {}).get(step["id"])
                outcome = interrupt({"kind": "mission", "step": step["id"], "task_id": task_id,
                                     "title": step["title"]}) or {}
                status = str(outcome.get("status") or "failed")
                results = {**(state.get("results") or {}),
                           step["id"]: {"status": status, "headline": outcome.get("headline"), "task_id": task_id}}
                update: Dict[str, Any] = {"results": results}
                if status not in GOES_ON:
                    update["stopped"] = (f"“{step['title']}” did not finish (it {status}), so the "
                                         "workflow stopped there.")
                return update

            graph.add_node(first, start)
            graph.add_node(second, wait)
        graph.add_edge(first, second)
        entries.append(first)
        exits.append(second)
    graph.add_edge(START, entries[0])
    for index, exit_node in enumerate(exits):
        following = entries[index + 1] if index + 1 < len(entries) else END
        graph.add_conditional_edges(exit_node, _next(exit_node, following),
                                    [following, END] if following != END else [END])
    return graph


def _postgres_url() -> str:
    """JAI's database for psycopg (LangGraph's Postgres checkpointer): without SQLAlchemy's driver suffix."""
    from app.core.config import settings

    url = str(settings.DATABASE_URL)
    for driver in ("+asyncpg", "+psycopg2", "+psycopg"):
        url = url.replace(driver, "")
    return url


_ready = False


@asynccontextmanager
async def postgres_saver() -> AsyncIterator[Any]:
    """LangGraph's Postgres checkpointer on JAI's database; its tables are created on first use."""
    global _ready
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(_postgres_url()) as saver:
        if not _ready:
            await saver.setup()
            _ready = True
        yield saver


def _pause(snapshot: Any) -> Optional[Dict[str, Any]]:
    """What the graph is paused on (the interrupt's value), if it is paused."""
    for task in getattr(snapshot, "tasks", ()) or ():
        for item in getattr(task, "interrupts", ()) or ():
            value = getattr(item, "value", None)
            if isinstance(value, dict):
                return value
    return None


async def advance(steps: List[Dict[str, Any]], ports: Ports, saver: Any, run_id: str, *,
                  start: Optional[FlowState] = None, resume: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run the workflow until it pauses or ends: from the start (start=the first state) or from its pause
    (resume=what it waited for). Returns {"paused": the pause or None, "finished": bool, "state": the state}."""
    from langgraph.types import Command

    app = build(steps, ports).compile(checkpointer=saver)
    config = {"configurable": {"thread_id": run_id}}
    if start is not None:
        await app.ainvoke(start, config)
    else:
        await app.ainvoke(Command(resume=resume or {}), config)
    snapshot = await app.aget_state(config)
    paused = _pause(snapshot)
    return {"paused": paused, "finished": paused is None and not snapshot.next, "state": dict(snapshot.values)}
