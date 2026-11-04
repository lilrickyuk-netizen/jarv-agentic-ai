"""
JAI Backend - Noticing when a mission is going round in circles (Wave 5)

After OpenHands' StuckDetector (MIT): an agent that repeats the same action and gets the same result, keeps hitting
the same error, or swaps back and forth between two actions is not making progress, however many steps it has left.
When that happens the agent is told plainly, once per loop, and asked to change approach; the steps are not
wasted silently.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SAME_RESULT = 4      # the same action with the same result this many times in a row
SAME_ERROR = 3       # the same action failing with the same error this many times in a row
PING_PONG = 6        # two actions (and their results) alternating over this many steps


def _digest(value: Any) -> str:
    try:
        text = json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def _error(out: Any) -> Optional[str]:
    if not isinstance(out, dict):
        return None
    if out.get("success") is False or out.get("error"):
        return str(out.get("error") or out.get("reason") or out.get("stderr") or "failed")[:300]
    if isinstance(out.get("exit_code"), int) and out["exit_code"] != 0:
        return str(out.get("stderr") or out.get("stdout") or f"exit code {out['exit_code']}")[-300:]
    return None


@dataclass
class Step:
    action: str
    result: str
    error: Optional[str]
    name: str


@dataclass
class StuckDetector:
    history: List[Step] = field(default_factory=list)
    nudges: int = 0

    def observe(self, name: str, args: Dict[str, Any], out: Any) -> Optional[str]:
        """Record one tool call and its result; a message for the agent when it is going round in circles."""
        error = _error(out)
        self.history.append(Step(_digest([name, args]), _digest(error if error else out), error, name))
        found = self._loop()
        if not found:
            return None
        kind, step = found
        self.history.clear()  # one message per loop: the next one has to be a new loop
        self.nudges += 1
        return message(kind, step, self.nudges)

    def _loop(self) -> Optional[Tuple[str, Step]]:
        h = self.history
        if len(h) >= SAME_ERROR:
            tail = h[-SAME_ERROR:]
            if tail[-1].error and all(s.action == tail[-1].action and s.error == tail[-1].error for s in tail):
                return "error", tail[-1]
        if len(h) >= SAME_RESULT:
            tail = h[-SAME_RESULT:]
            if all(s.action == tail[-1].action and s.result == tail[-1].result for s in tail):
                return "repeat", tail[-1]
        if len(h) >= PING_PONG:
            tail = h[-PING_PONG:]
            a, b = tail[-2], tail[-1]
            if a.action != b.action and all(
                    (s.action, s.result) == ((a if i % 2 == 0 else b).action, (a if i % 2 == 0 else b).result)
                    for i, s in enumerate(tail)):
                return "alternating", b
        return None


def message(kind: str, step: Step, nudges: int) -> str:
    if kind == "error":
        what = (f"you have run {step.name} the same way {SAME_ERROR} times and it failed the same way each time: "
                f"{step.error}")
        how = ("Read that error properly, find its cause (read the file or log it points to, or web_search the "
               "exact message), and fix the cause or try a different way. Do not run it again unchanged.")
    elif kind == "repeat":
        what = f"you have run {step.name} the same way {SAME_RESULT} times and got the same result each time"
        how = "You already have that result: use it and take the next step of the mission."
    else:
        what = f"you are switching back and forth between the same two actions (the last was {step.name})"
        how = "Step back, decide what is actually stopping you, and take a different route."
    return (f"[STUCK] You are going round in circles: {what}. {how}"
            + (" This is not the first loop in this mission: if something only Richard can give is truly in the "
               "way, call finish and name it." if nudges >= 3 else ""))
