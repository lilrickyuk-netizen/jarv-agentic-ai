"""
JAI Backend - Recall that understands time and lets unimportant memories fade

Three ideas from ICM (rtk-ai/icm, Apache-2.0: "Infinite Context Memory", whose recall scores level with the best
on the LoCoMo benchmark with no model call), written for JAI's own memory rather than added as a second memory:

- date_window: a question that names a period ("last week", "yesterday", "in October", "the past 3 days")
  searches that period, in Richard's time (London);
- fade: a memory's rank fades with age by its importance; critical memories (importance 0.9 and above) and the
  records JAI must never forget (decisions, boundaries, approvals, checkpoints, Richard's own inputs) never fade,
  and recalling a memory refreshes it;
- near duplicates: a new memory that says the same thing in other words as one in the same workspace, category and
  task (cosine similarity 0.95 or more, and exactly the same numbers, versions, paths and ids) is merged into it
  instead of piling up a copy (see MemoryService.add). Two memories that differ in any number or id ("R1 passed",
  "R2 passed") are different facts and both are kept.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
NEAR_DUPLICATE = 0.95
NEVER_FADE = {"decision", "boundary", "approval", "checkpoint", "richard_boundary_operator"}
FLOOR = 0.3  # an old memory still counts for something: it ranks lower, it is never lost

_MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"), start=1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_UNITS = {"day": 1, "days": 1, "week": 7, "weeks": 7, "month": 30, "months": 30}


def _midnight(day: datetime) -> datetime:
    return day.replace(hour=0, minute=0, second=0, microsecond=0)


def date_window(query: str, now: Optional[datetime] = None) -> Optional[Tuple[datetime, datetime, str]]:
    """(start, end, the phrase that named it) in UTC for a period the question names, or None."""
    text = (query or "").lower()
    local = (now or datetime.now(timezone.utc)).astimezone(LONDON)
    today = _midnight(local)
    found: Optional[Tuple[datetime, datetime]] = None
    phrase = ""
    patterns = (
        (r"\btoday\b|\bthis morning\b|\bearlier today\b", lambda m: (today, today + timedelta(days=1))),
        (r"\byesterday\b", lambda m: (today - timedelta(days=1), today)),
        (r"\b(?:the )?(?:last|past) (\d{1,3}) (days?|weeks?|months?)\b",
         lambda m: (today - timedelta(days=int(m.group(1)) * _UNITS[m.group(2)]), today + timedelta(days=1))),
        (r"\bthis week\b", lambda m: (today - timedelta(days=today.weekday()), today + timedelta(days=1))),
        (r"\blast week\b", lambda m: (today - timedelta(days=today.weekday() + 7), today - timedelta(days=today.weekday()))),
        (r"\bthis month\b", lambda m: (today.replace(day=1), today + timedelta(days=1))),
        (r"\blast month\b", lambda m: ((today.replace(day=1) - timedelta(days=1)).replace(day=1), today.replace(day=1))),
        (r"\b(?:in|during|from|back in) (" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b(?: (\d{4}))?",
         lambda m: _month(m.group(1), m.group(2), today)),
    )
    for pattern, window in patterns:
        match = re.search(pattern, text)
        if match:
            found, phrase = window(match), match.group(0)
            break
    if found is None:
        return None
    start, end = found
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc), phrase


def _month(name: str, year: Optional[str], today: datetime) -> Tuple[datetime, datetime]:
    month = _MONTHS[name]
    y = int(year) if year else (today.year if month <= today.month else today.year - 1)
    start = today.replace(year=y, month=month, day=1)
    end = start.replace(year=y + 1, month=1) if month == 12 else start.replace(month=month + 1)
    return start, end


def without_phrase(query: str, phrase: str) -> str:
    """The question without the words that only named the period, so they are not searched for as content."""
    if not phrase:
        return query
    rest = " ".join(re.sub(re.escape(phrase), " ", query, flags=re.I).split())
    return rest if re.search(r"[a-z0-9]{3,}", rest.lower()) else ""


def fade(importance: float, category: str, created_at: Optional[datetime], last_used: Optional[datetime],
         now: Optional[datetime] = None) -> float:
    """How much of its rank a memory keeps (FLOOR to 1.0). The half-life grows with importance: about a month for
    a trivial memory, about a year for an important one; critical memories and records JAI must keep never fade."""
    if importance >= 0.9 or category in NEVER_FADE:
        return 1.0
    moments = [t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in (created_at, last_used) if t is not None]
    if not moments:
        return 1.0
    age_days = max(0.0, ((now or datetime.now(timezone.utc)) - max(moments)).total_seconds() / 86400)
    half_life = 30 + 335 * max(0.0, min(1.0, importance))
    return max(FLOOR, 0.5 ** (age_days / half_life))


_IDENTIFIERS = re.compile(r"`[^`]+`|\S*\d\S*|\S+/\S+|\b[A-Z]{2,}[A-Z0-9_-]*\b")


def identifiers(text: str) -> set:
    """The parts of a memory that make it one particular fact: numbers, versions, paths, code and ids."""
    return {token.strip(".,;:!?()[]\"'") for token in _IDENTIFIERS.findall(text or "")}


def same_fact(a: str, b: str) -> bool:
    """Whether two near-identical memories state the same fact (only the wording differs)."""
    return identifiers(a) == identifiers(b)
