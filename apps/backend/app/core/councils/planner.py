"""
JAI Backend - The Orchestrator splits a mission that needs several agents

Richard's design: he gives JAI a mission and the Orchestrator assigns the agents. Until now one mission went to one
agent, whatever it asked for, and only the two fixed workflow templates ran several agents in turn. A founder's
request such as "Launch Plexecute: research the competitors, write the launch plan, then the launch posts" is work
for the Research Analyst, the Marketing Lead and the Content Lead, one after another.

So, for a short request that names more than one kind of work, the Orchestrator (one model call) decides whether it
is one specialist's job or several agents' work in turn, and if several, writes the plan: two to six steps, each with
the agent that does it and a short brief, and a review gate where Richard has to look at or send something before
the rest goes on. The plan runs on the same LangGraph workflow engine as the templates (councils/engine): each step
is its own mission done by that agent (role_mission for specialists, the builder for software), the next starts when
the one before finishes, a gate waits on the Approvals page, and the whole run survives restarts.

A detailed brief (long, numbered, or about one named file) is one job and is never split; nor is a workflow's own
step, a continuation, or anything while another workflow is open in the workspace. Without a model (tests, no
credit) nothing is split and the mission runs as before.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PLANNED = "planned"            # WorkflowRun.template for a plan the Orchestrator wrote
MAX_STEPS = 6
SHORT = 600                    # longer than this is a detailed brief: one job
_NUMBERED = re.compile(r"(?:^|\s)\d{1,2}[).]\s")
_ONE_FILE = re.compile(r"\b(?:revise|fix|update|edit|tidy|clean up|rework)\b[^.]{0,80}[\w-]\.(?:xlsx|csv|docx|pptx|md|pdf)\b",
                       re.I)
# One piece of work after another: "..., then ...", "followed by", or two different things to do.
_IN_TURN = re.compile(r"\b(and then|then|after that|afterwards|followed by|end[- ]to[- ]end|from start to finish)\b",
                      re.I)
_DOING = re.compile(r"\b(find|build|make|write|research|create|draft|plan|design|prepare|produce|market|launch|"
                    r"analyse|analyze|source|set up)\b", re.I)

_SYSTEM = (
    "You are JAI's Orchestrator. Richard, a founder, gives a mission in a sentence or two. JAI's agents are: "
    "{agents}. Decide whether this mission is ONE agent's job or needs SEVERAL agents working one after another. "
    "A single list, document, deck, plan or piece of software is one agent's job even when it has several parts or "
    "mentions several topics: answer split false. Split only when the mission asks for clearly different pieces of "
    "work that different agents do (for example research, then a plan, then posts; or build a page, then market "
    "it). When you split: two to six steps in the order they must happen, each with the agent that does it, a short "
    "title, and a brief of one or two sentences in Richard's own terms saying what that agent produces and where "
    "(a file in the product's folder). Later steps use what earlier ones left in the folder. Add a gate step only "
    "where Richard must review or send something himself before the next step makes sense. Nothing is sent, "
    "posted, published or paid for by any step. Answer with JSON only: "
    '{{"split": false}} or {{"split": true, "title": "<3-6 words>", "steps": [{{"agent": "<name>", "title": '
    '"<short>", "brief": "<one or two sentences>"}}, {{"gate": true, "title": "<short>", "ask": "<what Richard '
    'does, one sentence>"}}]}}')


def kinds_named(brief: str) -> List[str]:
    """The different kinds of work the brief's own words name (specialists, and "builder" for software)."""
    from app.core.command import work_type

    text = work_type.richard_brief(brief)
    found = [name for name, pattern, _ in work_type._KINDS if pattern.search(text)]
    if work_type._ENGINEERING.search(text) or work_type._BUILDER_KEEPS.search(text):
        found.append("builder")
    return list(dict.fromkeys(found))


def may_need_several(brief: str) -> bool:
    """Worth asking the Orchestrator: a short founder's request that names more than one kind of work and more
    than one thing to do. A detailed brief is one job."""
    from app.core.command import work_type
    from app.core.command.resume import CARRY_ON
    from app.core.knowledge.skill_packs import named_skill

    text = work_type.richard_brief(brief or "").strip()
    if not text or len(text) > SHORT or work_type.named_specialist(text) or CARRY_ON.search(text):
        return False
    if len(_NUMBERED.findall(text)) >= 2 or _ONE_FILE.search(text) or named_skill(text) is not None:
        return False
    if len(kinds_named(text)) < 2:
        return False
    # "Make me an investor pitch deck" names two kinds of work in one job; several agents' work says so: one thing
    # then another, or two different things to do.
    return bool(_IN_TURN.search(text)) or len({m.group(1).lower() for m in _DOING.finditer(text)}) >= 2


def _clean(plan: Any) -> Optional[Dict[str, Any]]:
    """The Orchestrator's plan, checked: real agents, at least two missions by at least two different agents."""
    from app.core.command.resume import CARRY_ON
    from app.core.command.work_type import DESCRIBED

    if not isinstance(plan, dict) or not plan.get("split"):
        return None
    steps: List[Dict[str, Any]] = []
    for item in (plan.get("steps") or [])[:MAX_STEPS]:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title") or "").split())[:80]
        if item.get("gate"):
            ask = " ".join(str(item.get("ask") or "").split())[:400]
            if title and ask and steps and not steps[-1].get("gate"):
                steps.append({"gate": True, "title": title, "ask": ask})
            continue
        agent = str(item.get("agent") or "").strip().lower().replace(" ", "_")
        # A step is new work: words that would make its mission inherit an earlier one's checklist are reworded.
        brief = CARRY_ON.sub("work on", " ".join(str(item.get("brief") or "").split()))[:600]
        if agent in DESCRIBED and title and brief:
            steps.append({"specialist": agent, "title": title, "brief": brief})
    while steps and steps[-1].get("gate"):  # a gate with nothing after it holds nothing back
        steps.pop()
    missions = [s for s in steps if not s.get("gate")]
    if len(missions) < 2 or len({s["specialist"] for s in missions}) < 2:
        return None
    title = " ".join(str(plan.get("title") or "").split())[:60] or "Mission plan"
    return {"title": title, "steps": steps}


async def plan(router, model: str, brief: str) -> Optional[Dict[str, Any]]:
    """The Orchestrator's plan for a mission that needs several agents, or None when it is one agent's job (or no
    model can be asked: never in tests)."""
    from app.core.command.work_type import DESCRIBED, richard_brief
    from app.core.providers.base import CompletionRequest, Message

    if router is None:
        return None
    agents = "; ".join(f"{name} ({what})" for name, what in DESCRIBED.items())
    try:
        response = await router.complete(CompletionRequest(
            model=model, messages=[Message(role="user", content=f"THE MISSION:\n{richard_brief(brief)[:SHORT]}")],
            system=_SYSTEM.format(agents=agents), temperature=0.0, max_tokens=1200))
        found = re.search(r"\{.*\}", response.content or "", re.S)
        return _clean(json.loads(found.group(0))) if found else None
    except Exception as exc:  # noqa: BLE001 - one agent runs the mission as before
        logger.info(f"mission not split by the Orchestrator: {exc}")
        return None


def fill(planned: Dict[str, Any], *, product: str, folder: str) -> List[Dict[str, Any]]:
    """The plan's steps as the workflow engine runs them: ids, and each mission's brief naming its agent, the
    folder and that it is new work building on the steps before it."""
    from app.core.councils.templates import NEW

    steps = []
    for number, step in enumerate(planned["steps"], start=1):
        if step.get("gate"):
            steps.append({"id": f"s{number}", "gate": True, "title": step["title"],
                          "ask": f"{step['ask']} Approve to let the plan go on; reject to stop it here."})
        else:
            steps.append({"id": f"s{number}", "specialist": step["specialist"], "title": step["title"],
                          "brief": (f"Specialist: {step['specialist']}. In {folder}, for {product}: {step['brief']} "
                                    "Use what the earlier steps of this plan left in the folder. " + NEW)})
    return steps
