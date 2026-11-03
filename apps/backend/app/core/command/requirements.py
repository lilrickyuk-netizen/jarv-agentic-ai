"""
JAI Backend - Requirements first (Upgrade 2)

Before a mission's first tool call, one model call turns the mission and the governing specification's relevant
sections into a numbered list of requirements, each naming where it comes from. The list is saved with the
mission's result, shown to the agent at the start of every round with its status, updated by the agent through
the ``requirement_status`` tool, and handed to the Verifier, which must give evidence for every requirement: a
requirement without evidence is unmet. For a conformance mission, every hard-check finding becomes a requirement
of its own, so a version the specification locks is a numbered item and not a line the agent has to notice.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_REQUIREMENTS = 40
STATUSES = ("open", "done", "waiting")

REQUIREMENTS_TOOL = {
    "name": "record_requirements",
    "description": "Record the mission's requirements: every distinct thing that must be true when it is done.",
    "input_schema": {
        "type": "object",
        "properties": {
            "requirements": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string", "description": "One checkable requirement, concrete (file, value, "
                                                          "command result)"},
                "source": {"type": "string", "description": "Where it comes from: the mission, or the "
                                                            "specification section (for example 'spec §40.1')"}},
                "required": ["text", "source"]}},
        },
        "required": ["requirements"],
    },
}

STATUS_TOOL = {
    "name": "requirement_status",
    "description": ("Mark one of the mission's numbered requirements as done (with the evidence: the file you "
                    "changed, the command and its result), open, or waiting (on Richard, with what for)."),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "The requirement's id, for example R3"},
            "status": {"type": "string", "enum": list(STATUSES)},
            "evidence": {"type": "string"},
        },
        "required": ["id", "status", "evidence"],
    },
}

_SYSTEM = (
    "You are JAI's requirements analyst. Read the mission and the specification sections given, and list "
    "every requirement the finished work must meet, each one concrete enough to check (a file and the value it "
    "must hold, a command that must pass, a document that must say a particular thing). Include requirements "
    "the specification imposes on what the mission covers, citing the section. Do not invent work the mission "
    "and the specification do not ask for. Call record_requirements once.")


def _clean(items: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            out.append({"text": " ".join(str(item["text"]).split())[:500],
                        "source": " ".join(str(item.get("source") or "mission").split())[:120]})
    return out


def number(items: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    return [{"id": f"R{i}", "text": item["text"], "source": item["source"], "status": "open", "evidence": ""}
            for i, item in enumerate(items[:MAX_REQUIREMENTS], start=1)]


async def derive(router, model: str, mission: str, *, spec: str = "",
                 findings: Optional[List[str]] = None) -> Dict[str, Any]:
    """{"requirements": [...], "tokens": n}. Hard-check findings are added as requirements of their own; when
    the model call fails the mission itself is the one requirement, so the mission still runs."""
    from app.core.config import settings
    from app.core.providers import CompletionRequest, Message

    items: List[Dict[str, str]] = []
    tokens = 0
    prompt = (f"MISSION:\n{mission[:6000]}\n\n"
              + (f"SPECIFICATION SECTIONS (the workspace's authority documents):\n{spec[:24000]}\n\n" if spec else "")
              + "List the requirements now.")
    try:
        resp = await router.complete(CompletionRequest(
            model=model, messages=[Message(role="user", content=prompt)], system=_SYSTEM,
            tools=[REQUIREMENTS_TOOL], max_tokens=settings.AGENT_MAX_OUTPUT_TOKENS, temperature=0.0,
            reasoning_effort=getattr(settings, "OPENAI_VERIFIER_REASONING_EFFORT", "high")))
        tokens = int((resp.usage or {}).get("total_tokens", 0) or 0)
        for call in resp.tool_calls or []:
            if call["function"]["name"] == REQUIREMENTS_TOOL["name"]:
                items = _clean((json.loads(call["function"]["arguments"] or "{}") or {}).get("requirements"))
                break
    except Exception as exc:  # noqa: BLE001 - the mission runs without a derived list rather than not at all
        logger.warning(f"requirements step failed: {exc}")
    if not items:
        items = [{"text": " ".join(mission.split())[:500], "source": "mission"}]
    items += [{"text": f"Resolve: {finding}"[:500], "source": "hard check"} for finding in (findings or [])]
    return {"requirements": number(items), "tokens": tokens}


def render(requirements: List[Dict[str, Any]]) -> str:
    lines = []
    for r in requirements:
        line = f"- {r['id']} [{r['status']}] {r['text']} ({r['source']})"
        if r.get("evidence"):
            line += f" — evidence: {r['evidence'][:200]}"
        lines.append(line)
    return "\n".join(lines)


def update(requirements: List[Dict[str, Any]], args: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a requirement_status call. Returns the tool result."""
    wanted = str(args.get("id") or "").strip().upper()
    status = str(args.get("status") or "").strip().lower()
    if status not in STATUSES:
        return {"success": False, "error": f"status must be one of {', '.join(STATUSES)}"}
    for r in requirements:
        if r["id"].upper() == wanted:
            evidence = " ".join(str(args.get("evidence") or "").split())[:500]
            if status == "done" and not evidence:
                return {"success": False, "error": "A requirement is done only with its evidence: name the file "
                                                   "or the command and its result."}
            r["status"], r["evidence"] = status, evidence
            left = [x["id"] for x in requirements if x["status"] != "done"]
            return {"success": True, "id": r["id"], "status": status,
                    "still_open": left or "none: verify, then call finish"}
    return {"success": False, "error": f"No requirement {wanted}; the ids are "
                                       + ", ".join(r["id"] for r in requirements)}


def unmet_without_evidence(requirements: List[Dict[str, Any]], checks: List[Dict[str, Any]]) -> List[str]:
    """Requirements the Verifier gave no met check with evidence for. A check counts for a requirement when it
    names the requirement's id (R3) or repeats its text."""
    unmet = []
    for r in requirements:
        pattern = re.compile(rf"\b{re.escape(r['id'])}\b", re.IGNORECASE)
        matching = [c for c in checks if pattern.search(str(c.get("requirement") or ""))
                    or r["text"][:60].lower() in str(c.get("requirement") or "").lower()]
        if not any(c.get("met") is True and str(c.get("evidence") or "").strip() for c in matching):
            unmet.append(f"{r['id']} ({r['text'][:200]}): the independent check gave no evidence that it is met.")
    return unmet
