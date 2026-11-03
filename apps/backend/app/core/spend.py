"""
JAI Backend - What JAI spends on AI today, and the daily limit (Wave 1: cost control)

Every model call JAI makes through its provider router, and every reply of the live voice conversation, is priced
and added to today's total (London time). When the total reaches ``DAILY_SPEND_LIMIT_USD`` JAI stops spending:
the router refuses new calls with ``SpendLimitReached`` (a provider error, so a running mission pauses to be
carried on rather than failing), and a live conversation is ended and cannot start again until the limit is raised
or the day turns over. Spending beyond the approved budget is one of Richard's hard boundaries; this makes it hold
for AI credit too. A limit of 0 turns the cap off; the meter keeps counting either way.

Totals live in Redis (one hash per day, kept 40 days). If Redis cannot be reached, calls are allowed and logged:
the meter is a guard, never the reason JAI stops working when its own store is down.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.providers.base import ProviderError

logger = logging.getLogger(__name__)

LONDON = ZoneInfo("Europe/London")
KEEP_SECONDS = 40 * 24 * 3600

# Live voice prices, US dollars per million tokens: (audio in, cached in, audio out, text in, text out).
# From OpenAI's Realtime price list as published in October 2026; an unlisted model is priced as the flagship.
REALTIME_PRICES: Dict[str, tuple] = {
    "gpt-realtime": (32.00, 0.40, 64.00, 4.00, 16.00),
    "gpt-realtime-2.1": (32.00, 0.40, 64.00, 4.00, 24.00),
    "gpt-realtime-2.1-mini": (10.00, 0.30, 20.00, 0.60, 2.40),
}


class SpendLimitReached(ProviderError):
    """Today's AI spending limit is reached: no model call is made until it is raised or the day turns over."""

    def __init__(self, spent: float, limit: float):
        super().__init__(f"Today's AI spending limit is reached: ${spent:.2f} of ${limit:.2f} (London day). JAI has "
                         f"paused what needs the AI; raise DAILY_SPEND_LIMIT_USD to carry on today, or it resumes "
                         f"tomorrow.", provider="budget")
        self.spent, self.limit = spent, limit


def day(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(LONDON).date().isoformat()


def key(date: Optional[str] = None) -> str:
    return f"spend:{date or day()}"


def limit_usd() -> float:
    return float(getattr(settings, "DAILY_SPEND_LIMIT_USD", 0) or 0)


def text_cost(model: str, usage: Optional[Dict[str, Any]]) -> Optional[float]:
    """A text model call's cost from JAI's price table, or None for a model the table does not list."""
    from app.core.command.metrics import PRICES, _normalise

    price = PRICES.get(model or "")
    if price is None:
        return None
    n = _normalise(usage or {})
    inp, out, cached, write = price
    return (n["input"] * inp + n["output"] * out + n["cached"] * cached + n["cache_write"] * write) / 1_000_000


def realtime_cost(model: str, usage: Optional[Dict[str, Any]]) -> float:
    """One live voice reply's cost from the usage OpenAI reports on response.done."""
    u = usage or {}
    a_in, cached, a_out, t_in, t_out = REALTIME_PRICES.get(model or "", REALTIME_PRICES["gpt-realtime"])
    details_in = u.get("input_token_details") or {}
    details_out = u.get("output_token_details") or {}
    cached_details = details_in.get("cached_tokens_details") or {}
    audio_in = int(details_in.get("audio_tokens") or 0)
    text_in = int(details_in.get("text_tokens") or 0)
    if not details_in:  # only totals reported: count them as text
        text_in = int(u.get("input_tokens") or 0)
    cached_audio = int(cached_details.get("audio_tokens") or 0)
    cached_text = int(cached_details.get("text_tokens") or 0)
    if not cached_details:
        cached_text = min(text_in, int(details_in.get("cached_tokens") or 0))
    audio_out = int(details_out.get("audio_tokens") or 0)
    text_out = int(details_out.get("text_tokens") or 0) if details_out else int(u.get("output_tokens") or 0)
    return (max(0, audio_in - cached_audio) * a_in + max(0, text_in - cached_text) * t_in
            + (cached_audio + cached_text) * cached + audio_out * a_out + text_out * t_out) / 1_000_000


async def _redis():
    from app.core.redis import get_redis

    return await asyncio.wait_for(get_redis(), timeout=2)


async def today(date: Optional[str] = None) -> Dict[str, Any]:
    """Today's spend: total, text models, live voice, calls, the limit and what is left."""
    date = date or day()
    spent: Dict[str, float] = {}
    try:
        raw = await asyncio.wait_for((await _redis()).hgetall(key(date)), timeout=2)
        spent = {str(k): float(v) for k, v in (raw or {}).items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"spend not read: {exc}")
    total = spent.get("text_usd", 0.0) + spent.get("voice_usd", 0.0)
    cap = limit_usd()
    return {"date": date, "total_usd": round(total, 4), "text_usd": round(spent.get("text_usd", 0.0), 4),
            "voice_usd": round(spent.get("voice_usd", 0.0), 4), "calls": int(spent.get("calls", 0)),
            "limit_usd": cap or None, "remaining_usd": round(max(0.0, cap - total), 4) if cap else None,
            "limit_reached": bool(cap) and total >= cap}


async def record(kind: str, cost_usd: Optional[float]) -> None:
    """Add one call's cost to today's total (kind: text or voice). Never raises."""
    if cost_usd is None or cost_usd < 0:
        cost_usd = 0.0
    field = "voice_usd" if kind == "voice" else "text_usd"
    try:
        redis = await _redis()
        name = key()
        await asyncio.wait_for(redis.hincrbyfloat(name, field, float(cost_usd)), timeout=2)
        await asyncio.wait_for(redis.hincrby(name, "calls", 1), timeout=2)
        await asyncio.wait_for(redis.expire(name, KEEP_SECONDS), timeout=2)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"spend not recorded ({kind} ${cost_usd:.4f}): {exc}")


async def check() -> None:
    """Refuse to spend more once today's limit is reached."""
    cap = limit_usd()
    if not cap:
        return
    state = await today()
    if state["total_usd"] >= cap:
        raise SpendLimitReached(state["total_usd"], cap)
