"""
JAI Backend - What a mission costs (Upgrade 5: measure first)

Every model call a mission makes (its steps, the requirements step, the independent check, the report draft) goes
through ``MeteredRouter``, which adds the call's tokens to the mission's ``Usage``: uncached input, cached input,
cache writes, output and reasoning, per role, and the cost in US dollars from the model's price table. The figures
are stored with the mission's result, so each change to how JAI works is kept only when the numbers improve.

The router also gives every call in one mission the same prompt-cache key, so the provider can reuse the cached
opening of the conversation across the mission's steps.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Optional

# US dollars per million tokens: (uncached input, output, cached input, cache write). Read from the model pages; the
# Claude prices from Anthropic's pricing page on 8 November 2026 (cache hits are 0.05x input, 5-minute cache writes
# 1.25x). A model not listed here is measured in tokens only.
PRICES: Dict[str, tuple] = {
    # US dollars per million tokens: input, output, cached input read, cache write.
    "gpt-6-luna": (0.10, 0.50, 0.01, 0.125),
    "gpt-6-sol": (2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
# Prices that change with the size of a request: past the threshold (prompt tokens, cached and written included) the
# higher rates apply to the whole request. Haiku 5.5: five times the rate once a prompt passes 100K tokens.
CLIFFS: Dict[str, tuple] = {
    "claude-haiku-5-5": (100_000, (0.50, 2.50, 0.05, 0.625)),
}
# What a sandbox run is priced at when its requests' sizes are not known one by one: the higher rate, so a mission's
# cost and allowance are never under-counted.
SANDBOX_PRICES: Dict[str, tuple] = {model: rates for model, (_, rates) in CLIFFS.items()}

ROLES = ("mission", "requirements", "verifier", "report")
# Roles that are light work whatever the mission's model: the report is written from evidence already gathered.
LIGHT_ROLES = ("report",)


def _normalise(usage: Dict[str, Any]) -> Dict[str, int]:
    """One shape for both providers. OpenAI's input count includes cached reads and cache writes; Anthropic's does
    not, and reports them separately."""
    u = {k: int(v or 0) for k, v in (usage or {}).items() if isinstance(v, (int, float))}
    if "input_tokens" in u or "cache_read_input_tokens" in u:  # Anthropic
        cached = u.get("cache_read_input_tokens", 0)
        written = u.get("cache_creation_input_tokens", 0)
        uncached = u.get("input_tokens", 0)
        output = u.get("output_tokens", 0)
    else:  # OpenAI (Responses or Chat Completions)
        cached = u.get("cached_tokens", 0)
        written = u.get("cache_write_tokens", 0)
        uncached = max(0, u.get("prompt_tokens", 0) - cached - written)
        output = u.get("completion_tokens", 0)
    return {"input": uncached, "cached": cached, "cache_write": written, "output": output,
            "reasoning": u.get("reasoning_tokens", 0)}


class Usage:
    def __init__(self) -> None:
        self.totals = {"input": 0, "cached": 0, "cache_write": 0, "output": 0, "reasoning": 0}
        self.by_role: Dict[str, Dict[str, int]] = {}
        self.calls = 0
        self.cost_usd = 0.0
        self.priced = True

    def add(self, usage: Optional[Dict[str, Any]], model: str, role: str) -> None:
        n = _normalise(usage or {})
        self.calls += 1
        for key, value in n.items():
            self.totals[key] += value
        role_totals = self.by_role.setdefault(role, {"calls": 0, "input": 0, "cached": 0, "cache_write": 0,
                                                     "output": 0, "reasoning": 0})
        role_totals["calls"] += 1
        for key, value in n.items():
            role_totals[key] += value
        price = PRICES.get(model)
        if price is None:
            self.priced = False
            return
        cliff = CLIFFS.get(model)
        if cliff and n["input"] + n["cached"] + n["cache_write"] > cliff[0]:
            price = cliff[1]
        inp, out, cached, write = price
        self.cost_usd += (n["input"] * inp + n["output"] * out + n["cached"] * cached
                          + n["cache_write"] * write) / 1_000_000

    def summary(self) -> Dict[str, Any]:
        sent = self.totals["input"] + self.totals["cached"] + self.totals["cache_write"]
        return {
            "calls": self.calls, **self.totals,
            "cache_hit_rate": round(self.totals["cached"] / sent, 3) if sent else 0.0,
            "cost_usd": round(self.cost_usd, 4) if self.priced else None,
            "by_role": self.by_role,
        }


def merge(earlier: Optional[Dict[str, Any]], latest: Dict[str, Any]) -> Dict[str, Any]:
    """A mission's figures across all its rounds: the earlier rounds' totals plus this round's."""
    if not isinstance(earlier, dict) or not earlier.get("usage"):
        return {**latest, "rounds_measured": 1}
    out = dict(latest)
    usage = dict(latest.get("usage") or {})
    for key in ("calls", "input", "cached", "cache_write", "output", "reasoning"):
        usage[key] = int(usage.get(key) or 0) + int((earlier.get("usage") or {}).get(key) or 0)
    if usage.get("cost_usd") is not None and (earlier.get("usage") or {}).get("cost_usd") is not None:
        usage["cost_usd"] = round(usage["cost_usd"] + earlier["usage"]["cost_usd"], 4)
    sent = usage["input"] + usage["cached"] + usage["cache_write"]
    usage["cache_hit_rate"] = round(usage["cached"] / sent, 3) if sent else 0.0
    out["usage"] = usage
    out["steps"] = int(latest.get("steps") or 0) + int(earlier.get("steps") or 0)
    if earlier.get("steps_to_first_edit") is not None:
        out["steps_to_first_edit"] = earlier["steps_to_first_edit"]
    out["rounds_measured"] = int(earlier.get("rounds_measured") or 1) + 1
    return out


class MeteredRouter:
    """The provider router, with every call counted against the mission and sharing its prompt-cache key."""

    def __init__(self, router, usage: Usage, role: str = "mission", cache_key: Optional[str] = None):
        self._router = router
        self.usage = usage
        self.role = role
        self.cache_key = cache_key

    def as_role(self, role: str) -> "MeteredRouter":
        return MeteredRouter(self._router, self.usage, role, self.cache_key)

    async def complete(self, request):
        from app.core.config import settings

        if self.role in LIGHT_ROLES and getattr(settings, "MODEL_TIERS_ENABLED", False):
            request = replace(request, model=settings.LIGHT_MODEL)  # writing up is light work: Luna
        if self.cache_key and getattr(request, "prompt_cache_key", None) is None:
            request = replace(request, prompt_cache_key=self.cache_key)
        response = await self._router.complete(request)
        self.usage.add(getattr(response, "usage", None), getattr(response, "model", "") or request.model, self.role)
        return response

    def __getattr__(self, name):
        return getattr(self._router, name)
