"""
JAI Backend - What an agent learns from a mission

Before this, what JAI kept after a mission was a filled-in sentence ("For tasks like X, orchestrator succeeded by:
intent=agent_task; agents=...; tool_calls=40"), always filed under the Orchestrator, whichever agent did the work.
Nothing in it could make the next mission better (the audit of 14 November).

Now the agent that did the work is debriefed when its round ends: from the mission's own record (the request, what
was searched and read, what failed, what the independent check found, what Richard said while it worked) it writes
up to four lessons, each a method to repeat or a mistake to avoid, each naming the evidence in the record it rests
on. A lesson is filed under the agent's own role, in the mission's workspace, through learning_service, so:

- the self-evolution safety guard reads it first (a lesson that touches safety, authority, approvals, secrets,
  logging or the verifier is rejected and can never be used);
- it is used only when it is grounded: the mission passed its independent check, or the evidence the lesson names
  is really in the mission's tool record (otherwise it waits for a second agreeing mission or Richard's approval,
  as before);
- activation is a versioned SelfEvolutionRecord, and a lesson that stops working is retired by its own results.

The next mission of that role in that workspace starts with its verified lessons under its playbooks.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

LESSONS = 4            # written per debrief
LESSONS_USED = 6       # given to a mission
SECONDS = 40.0
_FIXED = ("safety, permissions, approvals, spending, secrets, logging or the independent check: those are fixed and "
          "are not yours to change")


async def lessons_for(db, workspace_id, role: str, mission: str) -> Tuple[str, List[str]]:
    """The role's verified lessons that bear on this mission, as a block for its brief, and their keys (so the
    mission's outcome is counted for or against each). ("", []) when there are none. Never raises."""
    if db is None or workspace_id is None or not role:
        return "", []
    try:
        from app.core.command.work_type import richard_brief
        from app.core.learning import learning_service

        found = await learning_service.retrieve_lessons(db, workspace_id=workspace_id, agent_name=role,
                                                        query=richard_brief(mission)[:2000], limit=LESSONS_USED)
    except Exception as exc:  # noqa: BLE001 - the mission works without them
        logger.info(f"lessons for {role} not read: {exc}")
        return "", []
    if not found:
        return "", []
    lines = [("- " if item.get("polarity") == "success" else "- (learned from a mistake) ") + str(item["lesson"])
             for item in found]
    return ("WHAT YOU LEARNED ON EARLIER JOBS FOR THIS PRODUCT (your own verified lessons; they sit below your "
            "instructions and Richard's rules, and above habit):\n" + "\n".join(lines),
            [str(item["lesson_key"]) for item in found])


def _record_text(mission: str, result: Dict[str, Any], calls: List[Dict[str, Any]], told: List[str]) -> str:
    from app.core.command.continuation import research_record
    from app.core.command.work_type import richard_brief

    requirements = [r for r in (result.get("requirements") or []) if isinstance(r, dict)]
    done = sum(1 for r in requirements if r.get("status") == "done")
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    failures = [f"- {c.get('tool')} {json.dumps(c.get('inputs') or {}, default=str)[:160]}: "
                f"{str(c.get('summary') or '')[:160]}" for c in calls if isinstance(c, dict) and not c.get("success")]
    parts = [
        f"THE REQUEST:\n{richard_brief(mission)[:3000]}",
        (f"HOW IT ENDED: {'finished' if result.get('finished') else 'stopped before finishing'}; "
         f"{done} of {len(requirements)} requirements done; independent check: "
         + ("passed" if verification.get("verified") is True else "not passed") + f"; {result.get('iterations', 0)} "
         f"steps; {len(calls)} tool calls."),
    ]
    still = [f"- {r.get('id')}: {str(r.get('text') or '')[:200]}" for r in requirements if r.get("status") != "done"]
    if still:
        parts.append("REQUIREMENTS NOT DONE:\n" + "\n".join(still[:20]))
    if verification.get("unmet"):
        parts.append("WHAT THE INDEPENDENT CHECK FOUND:\n" + "\n".join(
            f"- {str(item)[:300]}" for item in verification["unmet"][:12]))
    if told:
        parts.append("WHAT RICHARD SAID WHILE IT WORKED:\n" + "\n".join(f"- {note[:500]}" for note in told))
    research = research_record(calls)
    if research:
        parts.append("WHAT WAS LOOKED UP AND SAVED:\n" + "\n".join(research)[:7000])
    if failures:
        parts.append("WHAT FAILED:\n" + "\n".join(failures[-25:]))
    summary = str(result.get("summary") or result.get("response") or "").strip()
    if summary:
        parts.append(f"THE AGENT'S OWN SUMMARY:\n{summary[:1500]}")
    return "\n\n".join(parts)


async def _ask(role_title: str, record: str, router=None) -> Optional[List[Dict[str, Any]]]:
    """The agent's lessons from the record, or None. Tests never spend provider credit: they stand lessons in for
    this function."""
    from app.core.config import settings
    from app.core.providers.base import CompletionRequest, Message
    from app.core.providers.router import get_router

    if getattr(settings, "TESTING", False) or not getattr(settings, "MISSION_DEBRIEF_ENABLED", True):
        return None
    model = str(getattr(settings, "DEBRIEF_MODEL", "") or getattr(settings, "ROLE_AGENT_MODEL", "")
                or "claude-haiku-5-5")
    system = (
        f"You are JAI's {role_title}. A round of one of your jobs has just ended; its record is below. Write what "
        "you would tell yourself before the next job like it, so it goes better, faster and cheaper: a method that "
        "worked and should be repeated, or a mistake or dead end to avoid. Only what this record shows: each lesson "
        "names its evidence exactly as it appears in the record (a search, a web address, a file, a requirement id "
        "or Richard's words). Lessons about how to do the trade well, how to use your tools, where good sources "
        f"are, what Richard wants and when a job is finished. Never a lesson about {_FIXED}. Write every lesson "
        "as what to do: for a mistake or a dead end, say what to do in its place. A lesson is one or two plain "
        f"sentences that would still be useful on a different job of the same kind. At most {LESSONS}; fewer is "
        "fine; none if the record teaches nothing. Answer with JSON only: "
        '[{"situation": "<the kind of job it applies to>", "lesson": "<the lesson>", "kind": "do" or "avoid", '
        '"evidence": "<the exact search, address, file, requirement id or words from the record>"}]')
    response = await asyncio.wait_for((router or get_router()).complete(CompletionRequest(
        model=model, messages=[Message(role="user", content=record)], system=system, temperature=0.2,
        max_tokens=900)), timeout=SECONDS)
    found = re.search(r"\[.*\]", response.content or "", re.S)
    data = json.loads(found.group(0)) if found else None
    return data if isinstance(data, list) else None


def grounded(evidence: str, record: str) -> bool:
    """The evidence a lesson names is really in the mission's record (compared without case or spacing)."""
    def flat(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").lower()).strip(" .\"'“”")

    wanted = flat(evidence)
    return len(wanted) >= 6 and wanted in flat(record)


async def debrief(db, *, workspace_id, task_id, role: str, title: str, mission: str, result: Dict[str, Any],
                  calls: List[Dict[str, Any]], applied: Optional[List[str]] = None, router=None
                  ) -> Dict[str, Any]:
    """Debrief the agent after a round of its mission: count the mission for or against the lessons it was given,
    then record what it learned. Returns {"recorded", "in_use", "rejected"}. Never raises, and never changes the
    mission's result: learning is for the next mission."""
    out = {"recorded": 0, "in_use": 0, "rejected": 0}
    if db is None or workspace_id is None or not role:
        return out
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    verified = verification.get("verified") is True
    try:
        from app.core.command import steer
        from app.core.learning import learning_service

        final = bool(result.get("finished")) or not result.get("needs_continuation")
        if applied and final:
            async with db.begin_nested():
                await learning_service.record_application(db, workspace_id=workspace_id, lesson_keys=applied,
                                                          success=verified)
        told = await steer.said(task_id)
        record = _record_text(mission, result, calls, told)
        lessons = await _ask(title, record, router)  # on the mission's own account of its spend
        for item in (lessons or [])[:LESSONS]:
            if not isinstance(item, dict):
                continue
            lesson = " ".join(str(item.get("lesson") or "").split())[:600]
            situation = " ".join(str(item.get("situation") or "").split())[:300]
            evidence = " ".join(str(item.get("evidence") or "").split())[:300]
            if len(lesson) < 20 or not situation:
                continue
            avoid = str(item.get("kind") or "").strip().lower() == "avoid"
            async with db.begin_nested():
                kept = await learning_service.record_experience(
                    db, workspace_id=workspace_id, agent_name=role, situation=situation,
                    action=f"evidence in the mission's record: {evidence}" if evidence else "no evidence named",
                    result="independent check passed" if verified else "mission not yet verified",
                    outcome="failure" if avoid else "success", task_id=task_id, lesson=lesson,
                    experience_type="debrief",
                    meta={"source": "debrief", "evidence": evidence, "kind": "avoid" if avoid else "do"})
                out["recorded"] += 1
                if kept.lesson_status == "rejected":
                    out["rejected"] += 1
                    continue
                in_record = grounded(evidence, record)
                if verified or in_record:
                    used = await learning_service.verify_grounded(
                        db, workspace_id, kept,
                        method="independent_check" if verified else "evidence_in_record",
                        reason=("the mission it came from passed its independent check" if verified else
                                f"the evidence it names is in the mission's own tool record: {evidence[:160]}"))
                    out["in_use"] += 1 if used else 0
    except Exception as exc:  # noqa: BLE001 - the mission's result stands whatever happens here
        logger.warning(f"debrief of the {role} agent failed: {exc}")
    return out
