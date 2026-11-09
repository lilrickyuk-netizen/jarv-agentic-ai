"""
JAI Backend - What kind of failure an unmet requirement is

OpenAI's Codex team found that when an agent stalls, the fix is to give it the missing tool or structure, not to
retry. That needs the failure's kind: an environment failure (a missing or wrong tool, a network or permission
problem) is fixed by setting the machine up; a specification failure needs a decision; a flaky check needs the
check fixed; a code failure is ordinary work. Reports name the kind, so Richard sees at a glance what is blocking
and the next round is aimed at the cause.

A fifth kind is not a failure at all: an item only Richard can finish (his review, an approval, the acceptance tag, a
sign-in, a push, a spend) is waiting on him. No round of work can finish it, so it never sends the mission round
again; the mission ends with it listed for him. On 9 November the MYCO Phase 0 tidy-up was finished and verified,
but its last item waited on Richard's manual review, so JAI kept re-running the team and it made six commits that
only re-proved finished work.
"""
from __future__ import annotations

import re
from typing import Dict, List

KINDS = ("richard", "environment", "spec", "flaky", "code")
# What only Richard can do: a gate, not work. Used both to classify and to accept a "waiting" judgement.
RICHARD_GATE = re.compile(
    r"(richard|the owner|manual (review|acceptance|approval|sign-?off)|sign-?off|approv(al|e)|acceptance tag|"
    r"(create|creating|cut|cutting) the tag|\bpush(ing)?\b|publish|deploy|spend|payment|password|log ?in|sign(ing)? in|"
    r"api key|credential)", re.I)
_WAITING = re.compile(
    r"(waiting (on|for) (richard|you|the owner|manual|approval)|needs? richard|only richard|richard (must|has to|needs to)|"
    r"richard'?s?\b[^.;\n]{0,40}\b(review|approval|sign-?off|decision|acceptance)|pending (richard|manual review|approval)|"
    r"after richard|until richard|manual review by richard)", re.I)
_PATTERNS = (
    ("richard", _WAITING),
    ("environment", re.compile(r"(command not found|not installed|no such file or directory: '?[a-z0-9_.-]+'?$|"
                               r"version mismatch|wrong version|expected version|requires? (node|python|pnpm|go|java)|"
                               r"permission denied|eacces|enotfound|network|timed? ?out|could not resolve|"
                               r"econnrefused|no space left|missing tool|toolchain|mise |corepack|(npm|package) registry)", re.I)),
    ("spec", re.compile(r"(ambiguous|unclear|spec(ification)? (does not|doesn't) say|contradict|not specified|"
                        r"needs (a )?decision|which (one|version) to|undefined requirement|conflicts with the spec)",
                        re.I)),
    ("flaky", re.compile(r"(flaky|intermittent|sometimes passes|passed on retry|race condition|nondeterministic|"
                         r"non-deterministic)", re.I)),
)


def classify(text: str) -> str:
    for kind, pattern in _PATTERNS:
        if pattern.search(text or ""):
            return kind
    return "code"


def is_gate(text: str) -> bool:
    """True when what an item waits for is something only Richard can do (a review, an approval, the tag, a sign-in,
    a push or a spend). A "waiting" judgement that names anything else is ordinary unfinished work."""
    return bool(RICHARD_GATE.search(text or ""))


def label(items: List[str]) -> List[str]:
    """Each unmet item prefixed with its kind ("[environment] syft is not installed")."""
    return [item if str(item).startswith("[") else f"[{classify(str(item))}] {item}" for item in items]


def counts(items: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in items:
        kind = classify(str(item))
        out[kind] = out.get(kind, 0) + 1
    return out
