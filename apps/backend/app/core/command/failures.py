"""
JAI Backend - What kind of failure an unmet requirement is

OpenAI's Codex team found that when an agent stalls, the fix is to give it the missing tool or structure, not to
retry. That needs the failure's kind: an environment failure (a missing or wrong tool, a network or permission
problem) is fixed by setting the machine up; a specification failure needs a decision; a flaky check needs the
check fixed; a code failure is ordinary work. Reports name the kind, so Richard sees at a glance what is blocking
and the next round is aimed at the cause.
"""
from __future__ import annotations

import re
from typing import Dict, List

KINDS = ("environment", "spec", "flaky", "code")
_PATTERNS = (
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


def label(items: List[str]) -> List[str]:
    """Each unmet item prefixed with its kind ("[environment] syft is not installed")."""
    return [item if str(item).startswith("[") else f"[{classify(str(item))}] {item}" for item in items]


def counts(items: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in items:
        kind = classify(str(item))
        out[kind] = out.get(kind, 0) + 1
    return out
