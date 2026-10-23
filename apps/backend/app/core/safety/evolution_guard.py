"""
JARV Backend - Self-evolution safety guard

One classifier shared by every path that can change JARV's behaviour from
experience (self-evolution proposals in the command center and learned lessons
injected into agent prompts). A change is unsafe if it would weaken safety,
authority, logging, audit, boundaries, approvals, verification, secret
handling, or sub-agent scoping, or raise spend or swarm limits. Unsafe changes
are blocked; they can never be approved into effect.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

_WEAKEN = (
    r"remove|disable|weaken|bypass|skip|ignore|turn\s*off|switch\s*off|delete|relax|"
    r"loosen|suppress|circumvent|avoid|drop|stop"
)
_CONTROLS = (
    r"safety|authority|authori[sz]ation|auth|permissions?|logging|logs?|audit|"
    r"boundary|boundaries|approvals?|verifier|verification|secrets?|guards?|"
    r"redaction|checks?|sandbox|scope|scoping"
)
_PATTERNS = (
    re.compile(rf"\b({_WEAKEN})\b.{{0,60}}\b({_CONTROLS})\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bwithout\s+(asking|approval|permission|authori[sz]ation|verification|logging)\b",
               re.IGNORECASE),
    re.compile(r"\b(auto[-\s]?approve|self[-\s]?approve|never\s+ask|don'?t\s+ask)\b", re.IGNORECASE),
    re.compile(r"\b(raise|increase|escalate|grant|elevate|exceed)\b.{0,60}\b("
               r"authority|privileges?|permissions?|access\s+level|swarm\s+limits?|"
               r"sub[-\s]?agent\s+(limits?|count|authority)|budget|spend(ing)?\s+limits?)\b",
               re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(sub[-\s]?agents?)\b.{0,60}\b(spawn\s+further|escape|outside\s+(its|their)\s+"
               r"workspace|more\s+authority)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(print|log|store|share|send|expose|reveal)\b.{0,40}\b("
               r"api[-\s]?keys?|passwords?|tokens?|private\s+keys?|seed\s+phrases?|credentials?)\b",
               re.IGNORECASE | re.DOTALL),
)


def classify_change(text: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Return ``(unsafe, matched_phrase)`` for a proposed behavioural change."""
    if not text:
        return False, None
    for pattern in _PATTERNS:
        match = pattern.search(text)
        if match:
            return True, match.group(0)[:120]
    return False, None


def is_unsafe_change(text: Optional[str]) -> bool:
    return classify_change(text)[0]
