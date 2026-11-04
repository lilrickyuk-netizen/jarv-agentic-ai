"""
JAI Backend - JAI's model gateway (Wave 6)

The open-source services JAI runs (Graphiti and Mem0 for memory, promptfoo for checking JAI's prompts) each speak
the OpenAI API. They never hold a provider key or reach a provider themselves: they call this gateway on JAI's
private networks with JAI's own gateway token, and the gateway checks today's AI spending limit, passes the call to
OpenAI with JAI's key, prices what it used and adds it to today's total, exactly as every call through JAI's router
is. Only the chat, responses and embeddings endpoints, only the models JAI allows (GATEWAY_MODELS), and no
streaming. Requests for JAI's reasoning model are put into the form it accepts (the same rules as JAI's OpenAI
provider), so a library written for older models works with it.
"""
from __future__ import annotations

import hmac
import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PATHS = ("chat/completions", "responses", "embeddings")
# US dollars per million input tokens (OpenAI's list prices).
EMBEDDING_PRICES = {"text-embedding-3-small": 0.02, "text-embedding-3-large": 0.13}
_SAMPLING = ("temperature", "top_p", "frequency_penalty", "presence_penalty", "logprobs", "top_logprobs",
             "logit_bias", "n")


class GatewayRefused(Exception):
    def __init__(self, status: int, message: str, kind: str = "invalid_request_error"):
        super().__init__(message)
        self.status, self.message, self.kind = status, message, kind

    def body(self) -> Dict[str, Any]:
        return {"error": {"message": self.message, "type": self.kind, "code": self.kind}}


def token() -> str:
    return str(getattr(settings, "JAI_GATEWAY_TOKEN", "") or "")


def allowed_models() -> Tuple[str, ...]:
    raw = str(getattr(settings, "GATEWAY_MODELS", "") or "")
    return tuple(m.strip() for m in raw.split(",") if m.strip())


def authorised(header: Optional[str]) -> bool:
    expected = token()
    if not expected or not header:
        return False
    given = header[7:].strip() if header.lower().startswith("bearer ") else header.strip()
    return hmac.compare_digest(given.encode(), expected.encode())


def _reasoning(model: str) -> bool:
    return model.startswith("gpt-6") or model.startswith("gpt-5") or model[:2] in ("o1", "o3", "o4")


def prepare(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """The request as it goes to OpenAI, or GatewayRefused."""
    if path not in PATHS:
        raise GatewayRefused(404, f"JAI's gateway serves {', '.join(PATHS)} only.")
    if not isinstance(body, dict):
        raise GatewayRefused(400, "The request body must be a JSON object.")
    model = str(body.get("model") or "")
    if model not in allowed_models():
        raise GatewayRefused(403, f"Model '{model}' is not one JAI allows here ({', '.join(allowed_models())}).",
                             "model_not_allowed")
    if body.get("stream"):
        raise GatewayRefused(400, "Streaming is not offered by JAI's gateway; ask without stream.")
    out = dict(body)
    if path == "embeddings":
        return out
    if _reasoning(model):
        for key in _SAMPLING:
            out.pop(key, None)
        if path == "chat/completions":
            if "max_tokens" in out:
                out["max_completion_tokens"] = out.pop("max_tokens")
            # On Chat Completions this model takes function tools only with reasoning switched off.
            if out.get("tools"):
                out["reasoning_effort"] = "none"
            else:
                out.setdefault("reasoning_effort", "low")
        else:
            out.setdefault("reasoning", {"effort": "low"})
    return out


def cost(path: str, model: str, usage: Optional[Dict[str, Any]]) -> float:
    """What one call cost, from the usage OpenAI reports."""
    from app.core import spend

    u = usage or {}
    if path == "embeddings":
        return int(u.get("prompt_tokens") or u.get("total_tokens") or 0) * EMBEDDING_PRICES.get(model, 0.13) / 1e6
    if path == "responses":
        details = u.get("input_tokens_details") or {}
        tokens = {"prompt_tokens": int(u.get("input_tokens") or 0),
                  "completion_tokens": int(u.get("output_tokens") or 0),
                  "cached_tokens": int(details.get("cached_tokens") or 0)}
    else:
        details = u.get("prompt_tokens_details") or {}
        tokens = {"prompt_tokens": int(u.get("prompt_tokens") or 0),
                  "completion_tokens": int(u.get("completion_tokens") or 0),
                  "cached_tokens": int(details.get("cached_tokens") or 0)}
    priced = spend.text_cost(model, tokens)
    return priced if priced is not None else (spend.text_cost("gpt-6-luna", tokens) or 0.0)


async def forward(path: str, body: Dict[str, Any], caller: str = "service",
                  client: Optional[httpx.AsyncClient] = None) -> Tuple[int, Dict[str, Any]]:
    """Check the limit, pass the call to OpenAI, record what it cost: (status, answer)."""
    from app.core import spend

    request = prepare(path, body)
    key = getattr(settings, "OPENAI_API_KEY", None)
    if not key:
        raise GatewayRefused(503, "JAI has no OpenAI key (OPENAI_API_KEY in apps/backend/.env).", "not_configured")
    try:
        await spend.check()
    except spend.SpendLimitReached as exc:
        raise GatewayRefused(429, str(exc), "spend_limit_reached") from exc
    base = str(getattr(settings, "GATEWAY_UPSTREAM", "") or "https://api.openai.com/v1").rstrip("/")
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0))
    try:
        response = await client.post(f"{base}/{path}", json=request,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    except httpx.HTTPError as exc:
        raise GatewayRefused(502, f"OpenAI could not be reached ({type(exc).__name__}).", "upstream_unreachable") from exc
    finally:
        if owned:
            await client.aclose()
    try:
        answer = response.json()
    except ValueError:
        answer = {"error": {"message": response.text[:500], "type": "upstream_error"}}
    if response.status_code < 400:
        spent = cost(path, str(request.get("model")), answer.get("usage"))
        await spend.record("text", spent)
        logger.info("gateway: %s %s for %s, $%.5f", path, request.get("model"), caller, spent)
    else:
        logger.warning("gateway: %s %s for %s answered %s", path, request.get("model"), caller, response.status_code)
    return response.status_code, answer
