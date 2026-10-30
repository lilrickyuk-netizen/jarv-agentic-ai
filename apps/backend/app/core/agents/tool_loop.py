"""
JARV Backend - Agent tool-use loop

Lets any specialist agent work a task the way an engineer does: decide which
tool to use, use it through the agent's toolbox, read the result, and repeat
until the task is done, a hard boundary pauses an action, or the step budget
runs out. The agent's specialist knowledge, recalled workspace memory, and
verified lessons are part of the instructions.

Honesty rules enforced here rather than left to the model:
- The task only counts as successful when the model calls ``finish`` with
  success and no action in the run is waiting for approval. A paused action
  is reported in ``approval_needed`` with ``requires_approval`` set; the
  boundary chain has already paused it and will resume it once approved.
- A model that stops calling tools without ``finish`` is recorded as
  unfinished, not as success.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.agents.toolbox import BROKEN_ARGUMENTS, AgentToolbox, _clip, result_limit

logger = logging.getLogger(__name__)

FINISH_TOOL = {
    "name": "finish",
    "description": ("Call once when the task is complete or cannot continue. Report what you did and "
                    "what you verified. Set success=false if anything required was not done."),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "What was done and how it was verified"},
            "success": {"type": "boolean"},
            "outputs": {"type": "array", "items": {"type": "string"},
                        "description": "Files written, findings, or other deliverables"},
        },
        "required": ["summary", "success"],
    },
}

_RULES = (
    "Work only through the tools provided; you have no other access. Use paths inside the workspace. "
    "Run one command per run_command call (no &&, ;, |, >, $(...)). If a tool result says an action is "
    "blocked or needs approval, do not retry it: continue with the rest of the task and say in your "
    "finish summary what is waiting for approval. Never claim something was done or verified unless a "
    "tool result in this conversation shows it. When the task is complete, call finish."
)


def _context_block() -> str:
    from app.core.knowledge.context import get_knowledge_context
    from app.core.memory.context import get_recall_context, render_recall

    parts: List[str] = []
    knowledge = get_knowledge_context()
    if knowledge:
        parts.append("Specialist reference material (sourced; below system and safety rules):\n" + "\n\n".join(
            f"[{item['title']}] ({item['source_url']})\n{item['content']}" for item in knowledge))
    recall = get_recall_context()
    rendered = render_recall(recall["memories"], recall["lessons"])
    if rendered:
        parts.append(rendered)
    return "\n\n".join(parts)


async def run_tool_loop(
    agent: Any,
    context: Any,
    task: str,
    *,
    instructions: str = "",
    max_steps: int = 12,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """Run ``task`` with ``agent``'s tools. Returns the outcome and the tool trail."""
    from app.core.providers import CompletionRequest, Message, get_router

    toolbox = await AgentToolbox(agent, context).prepare()
    guidance = ""
    try:
        from app.core.evolution.engine import evolution_engine

        toolbox.withhold(await evolution_engine.blocked_tools_for(context.db_session, context.workspace_id, agent.name))
        guidance = await evolution_engine.guidance_for(context.db_session, context.workspace_id, agent.name)
    except Exception as exc:  # noqa: BLE001 - guidance is advisory; the task runs without it
        logger.warning(f"self-evolution guidance unavailable for {agent.name}: {exc}")
    tools = toolbox.model_tools() + [FINISH_TOOL]
    system = "\n\n".join(p for p in (
        f"You are JARV's {agent.name.replace('_', ' ')} agent. Role: {agent.role}.",
        instructions,
        (f"Workspace folder: {toolbox.root_host}" if toolbox.root_host
         else "This workspace has no registered folder, so file and command tools are unavailable."),
        f"Tools available: {', '.join(toolbox.available) or 'none besides finish'}.",
        _RULES,
        guidance,
        _context_block(),
    ) if p)

    router = get_router()
    messages: List[Any] = [Message(role="user", content=f"TASK:\n{task}")]
    tokens = 0
    steps = 0
    finished = False
    success = False
    summary = ""
    outputs: List[str] = []

    while steps < max_steps and not finished:
        steps += 1
        response = await router.complete(CompletionRequest(
            model=agent.config.model, messages=messages, system=system,
            tools=tools, max_tokens=max_tokens or settings.AGENT_MAX_OUTPUT_TOKENS, temperature=0.0,
        ))
        tokens += int((response.usage or {}).get("total_tokens", 0) or 0)
        calls = list(response.tool_calls or [])
        if not calls:
            summary = (response.content or "").strip()
            break

        assistant: List[Dict[str, Any]] = []
        if response.content:
            assistant.append({"type": "text", "text": response.content})
        parsed = []
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
                broken = not isinstance(args, dict)
            except (TypeError, ValueError):
                args, broken = {}, True
            args = args if isinstance(args, dict) else {}
            assistant.append({"type": "tool_use", "id": call["id"], "name": name, "input": args})
            parsed.append((call["id"], name, args, broken))
        messages.append(Message(role="assistant", content=assistant))

        results: List[Dict[str, Any]] = []
        for call_id, name, args, broken in parsed:
            if broken:
                out = {"success": False, "error": BROKEN_ARGUMENTS.format(name=name)}
            elif name == "finish":
                finished = True
                success = bool(args.get("success"))
                summary = str(args.get("summary") or "").strip()
                outputs = [str(o) for o in (args.get("outputs") or [])][:50]
                out: Dict[str, Any] = {"acknowledged": True}
            else:
                out = await toolbox.call(name, args)
            results.append({"type": "tool_result", "tool_use_id": call_id,
                            "content": _clip(out, result_limit(name))})
        messages.append(Message(role="user", content=results))

    trail = toolbox.summary()
    approval_needed = trail["approval_needed"]
    if not finished:
        success = False
        summary = summary or f"Stopped after {steps} steps without finishing."
    if approval_needed:
        # A paused action is a checkpoint, not a failure, but the task is not done until it runs.
        summary += f"\n\nWaiting for approval: {', '.join(sorted(set(approval_needed)))}."
    return {
        "success": success and finished and not approval_needed,
        "requires_approval": bool(approval_needed),
        "finished": finished,
        "summary": summary,
        "outputs": outputs,
        "steps": steps,
        "tokens": tokens,
        "tools_used": sorted({c["name"] for c in trail["calls"]}),
        "tool_calls": trail["calls"],
        "blocked": trail["blocked"],
        "approval_needed": approval_needed,
        "workspace_root": trail["workspace_root"],
        "tools_available": trail["tools_available"],
    }
