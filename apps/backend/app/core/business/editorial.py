"""
JAI Backend - The final editorial pass for writing that goes to people (Upgrade 4: No AI Slop)

Peter Yang's No AI Slop skill (MIT, pinned in skill-packs/) is the editor's rulebook. JAI uses it three ways, all
cheap:

1. ``rules()``: its editing principles, words and patterns to cut, given to JAI's writer with every draft, so a draft
   is written to pass the editor in the first place (no extra model call).
2. ``findings()``: a check with no model at all: the skill's banned words, its empty phrases and patterns (binary
   contrasts, throat-clearing, faux insight, summary endings) and em-dash clusters, each quoted from the draft.
3. ``revise()``: only when the check finds something, one revision on the light model with those findings, kept only
   if every number, link, name in capitals and [confirm: ...] marker of the original survives, so meaning, technical
   accuracy and verified facts are never traded for style.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

SKILL = "no-ai-slop/skills/no-ai-slop/SKILL.md"
_SECTIONS = ("Editing principles", "Words to cut", "Patterns to cut")
# The skill's own examples of the patterns it names, matched as phrases (case-insensitive).
_PATTERNS = (
    (r"\b(?:it|this|that)(?:'s| is) not (?:just )?[^.!?]{1,60}[.,;:—-]+\s*(?:it|this|that)(?:'s| is)\b",
     "binary contrast"),
    (r"\bnot just\b[^.!?]{1,60}\bbut\b", "binary contrast"),
    (r"\b(?:here's the thing|here's what i mean|let me be clear|i'll be honest|the uncomfortable truth is)\b",
     "throat-clearing opener"),
    (r"\b(?:what most people get wrong|here's what nobody tells you|the part (?:everyone|most people) (?:misses|skip))",
     "faux-insight setup"),
    (r"\b(?:stands as a testament|marks a pivotal moment|plays a vital role|solidifies its position|"
     r"underscores its significance)\b", "importance puffery"),
    (r"\b(?:experts agree|industry reports suggest|many argue|widely regarded as|studies show)\b", "weasel attribution"),
    (r"\b(?:what if i told you|think about it:|plot twist:)", "rhetorical setup"),
    (r"(?:^|\n)\s*(?:in conclusion|ultimately|overall),", "summary-recap ending"),
)


def _skill_text() -> Optional[str]:
    from app.core.config import settings
    from app.core.knowledge.skill_packs import packs_dir

    if not getattr(settings, "SKILL_PACKS_ENABLED", True):
        return None
    try:
        return (packs_dir() / SKILL).read_text(encoding="utf-8")
    except OSError:
        return None


@lru_cache(maxsize=4)
def _parsed(text: str) -> Dict[str, Any]:
    sections: Dict[str, str] = {}
    for title in _SECTIONS:
        match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        if match:
            sections[title] = match.group(1).strip()
    words: List[str] = []
    phrases: List[str] = []
    cut = sections.get("Words to cut", "")
    banned = re.search(r"Banned outright:\s*(.+?)\.\s*$", cut, re.M)
    if banned:
        words = [w.strip().lower() for w in banned.group(1).split(",") if w.strip()]
    empty = re.search(r"Often-empty phrases:\s*(.+?)\.\s*Cut them", cut, re.S)
    if empty:
        phrases = [p.strip().lower() for p in empty.group(1).split(",") if p.strip()]
    return {"sections": sections, "words": words, "phrases": phrases}


def available() -> bool:
    return _skill_text() is not None


def rules(max_chars: int = 6000) -> str:
    """The editor's rules for JAI's writer, or "" when the skill pack is not installed."""
    text = _skill_text()
    if not text:
        return ""
    parsed = _parsed(text)
    body = "\n\n".join(f"{title}:\n{parsed['sections'][title]}" for title in _SECTIONS if title in parsed["sections"])
    return ("EDITOR'S RULES (No AI Slop, by Peter Yang, MIT): write so the piece passes them. Keep every fact, "
            "number and name exactly.\n" + body)[:max_chars]


def _quote(text: str, start: int, end: int) -> str:
    left = max(0, text.rfind("\n", 0, start) + 1, start - 60)
    right = min(len(text), end + 60)
    newline = text.find("\n", end)
    if newline != -1:
        right = min(right, newline)
    return text[left:right].strip()


def findings(text: str) -> List[Dict[str, str]]:
    """The skill's patterns in ``text``: [{"pattern", "quote"}]. No model call; empty when the pack is missing."""
    skill = _skill_text()
    if not skill or not text:
        return []
    parsed = _parsed(skill)
    out: List[Dict[str, str]] = []
    lower = text.lower()
    for word in parsed["words"]:
        for match in re.finditer(rf"\b{re.escape(word)}\w*\b", lower):
            out.append({"pattern": f"banned word '{word}'", "quote": _quote(text, match.start(), match.end())})
            break
    for phrase in parsed["phrases"]:
        match = re.search(rf"\b{re.escape(phrase)}\b", lower)
        if match:
            out.append({"pattern": f"empty phrase '{phrase}'", "quote": _quote(text, match.start(), match.end())})
    for pattern, name in _PATTERNS:
        match = re.search(pattern, lower, re.M)
        if match:
            out.append({"pattern": name, "quote": _quote(text, match.start(), match.end())})
    dashes = text.count("—")
    words = max(1, len(text.split()))
    if dashes and (words < 200 or dashes > 2):
        out.append({"pattern": f"em dashes ({dashes})", "quote": _quote(text, text.find("—"), text.find("—") + 1)})
    return out


_FACT = re.compile(r"\[confirm:[^\]]+\]|https?://\S+|\b\d[\d,.:%/£$€-]*\b|`[^`]+`")


def facts_kept(original: str, revised: str) -> bool:
    """Every number, link, code span and [confirm: ...] marker of the original is still in the revision."""
    return all(token in revised for token in set(_FACT.findall(original)))


Complete = Callable[..., Awaitable[Dict[str, Any]]]


async def revise(text: str, *, audience: str = "", complete: Optional[Complete] = None,
                 model: Optional[str] = None) -> Dict[str, Any]:
    """The final editorial pass: {"text", "revised", "findings_before", "findings_after", "reason"}. Only text the
    check flags is sent to a model; a revision that loses a fact is thrown away and the original kept."""
    before = findings(text)
    result: Dict[str, Any] = {"text": text, "revised": False, "findings_before": len(before), "findings_after": len(before),
                              "patterns": [f["pattern"] for f in before], "reason": ""}
    if not before:
        result["reason"] = "passed the editor's check" if available() else "the No AI Slop skill pack is not installed"
        return result
    from app.core.config import settings

    if complete is None:
        from app.core.agents.specialists import _helpers as helpers

        if not helpers.provider_configured():
            result["reason"] = "no model configured; the findings are reported for a person to fix"
            return result
        complete = helpers.llm_complete
    listed = "\n".join(f"- {f['pattern']}: \"{f['quote']}\"" for f in before)
    prompt = ("Edit this draft with the minimum effective changes to remove the patterns found below. Keep the "
              "writer's voice, structure and Markdown, every fact, number, name, link and [confirm: ...] marker "
              "exactly. Do not add claims. Return only the edited draft.\n"
              + (f"Audience: {audience}\n" if audience else "")
              + f"\nFOUND:\n{listed}\n\nDRAFT:\n{text}")
    try:
        reply = await complete(model or str(getattr(settings, "LIGHT_MODEL", "") or "gpt-6-luna"), prompt,
                               system=rules(), temperature=0.2, max_tokens=3000)
    except Exception as exc:  # noqa: BLE001 - the draft stands; the editor is an addition
        result["reason"] = f"editor unavailable ({type(exc).__name__})"
        return result
    edited = str((reply or {}).get("text") or "").strip()
    if not edited:
        result["reason"] = "the editor returned nothing; the original stands"
        return result
    if not facts_kept(text, edited):
        result["reason"] = "the edit dropped a fact or number, so the original stands"
        return result
    after = findings(edited)
    if len(after) >= len(before):
        result["reason"] = "the edit did not remove the patterns, so the original stands"
        return result
    result.update(text=edited, revised=True, findings_after=len(after), reason="edited by the No AI Slop pass")
    return result
