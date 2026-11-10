"""
JAI Backend - The result card at the top of every mission report

Richard, 10 November (from AskRich's two-layer answers): he is a non-technical founder and was pasting every report to
Claude to have it explained. Each mission now starts its report with a short card he can read himself:
  - one plain-English line saying what came out of it;
  - three numbers (requirements met, time, cost, or what the work produced);
  - what needs him, if anything;
  - the next steps;
  - how sure JAI is.
JAI's voice reads the card's first line. The numbers and status come from the mission's own record; the line, the
"needs you" items and the next steps are written by a small model from the report (CARD_MODEL), and from the record
alone when the model cannot be reached (and always in tests, which never spend provider credit).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CARD_SECONDS = 10.0
GBP_PER_USD = 0.78


def _requirements(result: Dict[str, Any]) -> Dict[str, int]:
    reqs = [r for r in (result.get("requirements") or []) if isinstance(r, dict)]
    return {"total": len(reqs), "done": sum(1 for r in reqs if r.get("status") == "done"),
            "waiting": sum(1 for r in reqs if r.get("status") == "waiting")}


def _status(result: Dict[str, Any], waiting: List[str]) -> str:
    if result.get("success") and not waiting:
        return "Done and checked"
    if result.get("success"):
        return "Done: waiting for you"
    if result.get("needs_continuation"):
        return "Not finished yet: JAI carries on"
    return "Not finished"


def _minutes(started_at: Optional[str]) -> Optional[int]:
    try:
        started = datetime.fromisoformat(str(started_at))
    except (TypeError, ValueError):
        return None
    return max(1, round((datetime.now(timezone.utc) - started).total_seconds() / 60))


def _money(usd: float) -> str:
    pounds = usd * GBP_PER_USD
    return f"{round(pounds * 100)}p" if pounds < 1 else f"£{pounds:.2f}"


def facts(result: Dict[str, Any], *, cost_usd: float = 0.0, started_at: Optional[str] = None,
          waiting: Optional[List[str]] = None) -> Dict[str, Any]:
    """What the mission's own record says, with no model involved."""
    waiting = [str(w) for w in (waiting or [])]
    reqs = _requirements(result)
    numbers = []
    if reqs["total"]:
        numbers.append({"label": "requirements met", "value": f"{reqs['done']} of {reqs['total']}"})
    minutes = _minutes(started_at)
    if minutes:
        numbers.append({"label": "time", "value": f"{minutes} min"})
    if cost_usd > 0:
        numbers.append({"label": "cost", "value": _money(cost_usd)})
    unmet = [str(u) for u in ((result.get("verification") or {}).get("unmet") or [])][:3]
    return {"status": _status(result, waiting), "numbers": numbers, "needs_you": waiting[:3],
            "open": unmet, "confidence": (result.get("report") or {}).get("confidence") or
            ("High" if result.get("success") else "Low")}


async def _write(report: str, mission: str, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The plain-English line, what needs Richard and the next steps, from the report, by a small model."""
    from app.core.config import settings
    from app.core.providers.base import CompletionRequest, Message
    from app.core.providers.router import get_router

    if getattr(settings, "TESTING", False):
        return None
    prompt = (
        "You write the result card a busy, non-technical founder reads at the top of a mission report.\n"
        f"The mission he gave: {mission[:1500]}\n"
        f"Its status: {record['status']}\n"
        f"The report:\n{report[:12000]}\n\n"
        "Answer with JSON only, in plain British English and no jargon: "
        '{"headline": "<one sentence, at most 25 words: what came out of it, with the main number>", '
        '"numbers": [<up to 2 {"label": "<2-4 words>", "value": "<short>"} for what the work produced, not time or '
        'cost>], "needs_you": [<up to 3 short things only he can do, empty if none>], '
        '"next_steps": [<up to 3 short, concrete next steps>]}')
    model = str(getattr(settings, "CARD_MODEL", "") or "claude-haiku-5-5")
    response = await asyncio.wait_for(get_router().complete(CompletionRequest(
        model=model, messages=[Message(role="user", content=prompt)], temperature=0.2, max_tokens=500)),
        timeout=CARD_SECONDS)
    found = re.search(r"\{.*\}", response.content or "", re.S)
    return json.loads(found.group(0)) if found else None


async def make(result: Dict[str, Any], *, mission: str, cost_usd: float = 0.0, started_at: Optional[str] = None,
               waiting: Optional[List[str]] = None) -> Dict[str, Any]:
    card = facts(result, cost_usd=cost_usd, started_at=started_at, waiting=waiting)
    written: Optional[Dict[str, Any]] = None
    try:
        written = await _write(str(result.get("answer") or ""), mission, card)
    except Exception as exc:  # noqa: BLE001 - the card is made from the record alone
        logger.info(f"result card written without the model: {exc}")
    if written:
        card["headline"] = str(written.get("headline") or "").strip()[:300]
        made = [n for n in (written.get("numbers") or []) if isinstance(n, dict) and n.get("value")][:2]
        card["numbers"] = [{"label": str(n.get("label"))[:40], "value": str(n.get("value"))[:40]}
                           for n in made] + card["numbers"]
        card["needs_you"] = (card["needs_you"] + [str(x)[:200] for x in (written.get("needs_you") or [])])[:3]
        card["next_steps"] = [str(x)[:200] for x in (written.get("next_steps") or [])][:3]
    card.setdefault("headline", f"{card['status']}." if card["status"].endswith(("checked", "yet")) else card["status"])
    card.setdefault("next_steps", [])
    card["numbers"] = card["numbers"][:4]
    return card


def render(card: Dict[str, Any]) -> str:
    """The card as the top of the report (Markdown)."""
    lines = ["### Result", f"**{card.get('headline') or card.get('status')}**", ""]
    numbers = " · ".join(f"{n['value']} {n['label']}" if n["label"] not in ("time", "cost") else n["value"]
                         for n in card.get("numbers") or [])
    lines.append(f"{card.get('status')}" + (f" · {numbers}" if numbers else "")
                 + f" · confidence: {str(card.get('confidence') or '').lower()}")
    if card.get("needs_you"):
        lines += ["", "**Needs you:**"] + [f"- {item}" for item in card["needs_you"]]
    if card.get("open"):
        lines += ["", "**Still open:**"] + [f"- {item[:200]}" for item in card["open"]]
    if card.get("next_steps"):
        lines += ["", "**Next:**"] + [f"{i}. {step}" for i, step in enumerate(card["next_steps"], 1)]
    return "\n".join(lines) + "\n\n---\n\n"
