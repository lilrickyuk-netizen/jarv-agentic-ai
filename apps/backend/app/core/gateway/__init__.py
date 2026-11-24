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

import hashlib
import hmac
import json
import logging
import secrets
from typing import Any, AsyncIterator, Dict, Optional, Tuple

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
    models = [m.strip() for m in raw.split(",") if m.strip()]
    # The sandbox's own models are always allowed, even when an older .env lists the gateway's models itself.
    for own in (getattr(settings, "OPENHANDS_MODEL", ""), getattr(settings, "OPENHANDS_SPECIALIST_MODEL", ""),
                getattr(settings, "OPENHANDS_STUCK_MODEL", ""), getattr(settings, "OPENHANDS_RESEARCH_MODEL", ""),
                getattr(settings, "OPENHANDS_RESEARCH_FALLBACK_MODEL", "")):
        if own and own not in models:
            models.append(str(own))
    return tuple(models)


def authorised(header: Optional[str]) -> bool:
    expected = token()
    if not expected or not header:
        return False
    given = header[7:].strip() if header.lower().startswith("bearer ") else header.strip()
    return hmac.compare_digest(given.encode(), expected.encode())


# 24 November (audit batch 3): a Claude Agent SDK session in the sandbox thinks through this gateway with a token of
# its own run, never JAI's gateway token. The token lives while the run is registered (sandbox_engine issues it and
# revokes it when the run ends), serves only Anthropic's Messages API, and is refused once its run has spent the
# run's own allowance, on top of today's limit. So a token read by the agent's shell can do no more than the
# session itself was allowed to.
RUN_TOKEN_KEY = "gateway:run-token:{}"
RUN_SPEND_KEY = "gateway:run-spend:{}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def issue_run_token(run_id: str, ttl_seconds: int, max_cost_usd: Optional[float] = None) -> str:
    """A new token for one sandbox run's model calls, held to max_cost_usd (None: today's limit only)."""
    from app.core.redis import get_redis

    value = "jai-run-" + secrets.token_urlsafe(32)
    record = {"run": run_id, "max_cost_usd": float(max_cost_usd) if max_cost_usd else None}
    await (await get_redis()).set(RUN_TOKEN_KEY.format(_digest(value)), json.dumps(record), ex=int(ttl_seconds))
    return value


async def revoke_run_token(value: Optional[str]) -> None:
    if not value:
        return
    from app.core.redis import get_redis

    redis = await get_redis()
    await redis.delete(RUN_TOKEN_KEY.format(_digest(value)), RUN_SPEND_KEY.format(_digest(value)))


def _bare(header: Optional[str]) -> str:
    return (header or "")[7:].strip() if (header or "").lower().startswith("bearer ") else (header or "").strip()


async def run_of_token(header: Optional[str]) -> Optional[Dict[str, Any]]:
    """The sandbox run a token belongs to ({"run", "max_cost_usd", "key"}), while that run is registered."""
    given = _bare(header)
    if not given.startswith("jai-run-"):
        return None
    try:
        from app.core.redis import get_redis

        found = await (await get_redis()).get(RUN_TOKEN_KEY.format(_digest(given)))
        record = json.loads(found) if found else None
    except Exception:  # noqa: BLE001 - no answer is a refusal
        return None
    if not isinstance(record, dict) or not record.get("run"):
        return None
    return {**record, "key": _digest(given)}


async def run_spent(run: Optional[Dict[str, Any]]) -> float:
    if not run:
        return 0.0
    from app.core.redis import get_redis

    value = await (await get_redis()).get(RUN_SPEND_KEY.format(run["key"]))
    return float(value or 0)


async def check_run(run: Optional[Dict[str, Any]]) -> None:
    """GatewayRefused when a run token's run has spent its own allowance."""
    limit = (run or {}).get("max_cost_usd")
    if limit and await run_spent(run) >= float(limit):
        raise GatewayRefused(429, f"This run has used its spending allowance (${float(limit):.2f}).",
                             "spend_limit_reached")


async def add_run_spend(run: Optional[Dict[str, Any]], spent: float) -> None:
    if not run or spent <= 0:
        return
    from app.core.redis import get_redis

    redis = await get_redis()
    key = RUN_SPEND_KEY.format(run["key"])
    await redis.incrbyfloat(key, float(spent))
    await redis.expire(key, 8 * 3600)


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
    # A reasoning model working through a long engineering task can think for several minutes on one call.
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))
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


ANTHROPIC_UPSTREAM = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


async def forward_anthropic(body: Dict[str, Any], version: Optional[str] = None, beta: Optional[str] = None,
                            caller: str = "service", client: Optional[httpx.AsyncClient] = None,
                            run: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    """Anthropic's Messages API for JAI's sandbox: the same limit, allow-list and pricing as the OpenAI side. A
    "no credit" answer is shared with the rest of JAI, so its work moves to GPT-6 Sol until the account is topped
    up."""
    from app.core import spend
    from app.core.providers.router import mark_no_credit

    model = str(body.get("model") or "")
    if model not in allowed_models():
        raise GatewayRefused(400, f"{model or 'That model'} is not one JAI's gateway allows.", "model_not_allowed")
    if body.get("stream"):
        raise GatewayRefused(400, "Ask for a stream through forward_anthropic_stream.", "stream_not_supported")
    key = getattr(settings, "CLAUDE_API_KEY", None) or getattr(settings, "ANTHROPIC_API_KEY", None)
    if not key:
        raise GatewayRefused(503, "JAI has no Anthropic key (ANTHROPIC_API_KEY in apps/backend/.env).",
                             "not_configured")
    try:
        await spend.check()
    except spend.SpendLimitReached as exc:
        raise GatewayRefused(429, str(exc), "spend_limit_reached") from exc
    await check_run(run)
    headers = {"x-api-key": key, "anthropic-version": version or ANTHROPIC_VERSION,
               "content-type": "application/json"}
    if beta:
        headers["anthropic-beta"] = beta
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))
    try:
        response = await client.post(f"{ANTHROPIC_UPSTREAM}/messages", json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise GatewayRefused(502, f"Anthropic could not be reached ({type(exc).__name__}).",
                             "upstream_unreachable") from exc
    finally:
        if owned:
            await client.aclose()
    try:
        answer = response.json()
    except ValueError:
        answer = {"type": "error", "error": {"type": "api_error", "message": response.text[:500]}}
    if response.status_code < 400:
        spent = spend.text_cost(model, answer.get("usage")) or 0.0
        await spend.record("text", spent)
        await add_run_spend(run, spent)
        logger.info("gateway: anthropic %s for %s, $%.5f", model, caller, spent)
    else:
        message = str((answer.get("error") or {}).get("message") or "").lower()
        if any(word in message for word in ("credit balance", "billing", "insufficient", "quota")):
            await mark_no_credit("claude")
        logger.warning("gateway: anthropic %s for %s answered %s", model, caller, response.status_code)
    return response.status_code, answer


def _anthropic_ready(body: Dict[str, Any], version: Optional[str], beta: Optional[str]) -> Dict[str, str]:
    """The upstream headers for an allowed Anthropic request, or GatewayRefused."""
    model = str(body.get("model") or "")
    if model not in allowed_models():
        raise GatewayRefused(400, f"{model or 'That model'} is not one JAI's gateway allows.", "model_not_allowed")
    key = getattr(settings, "CLAUDE_API_KEY", None) or getattr(settings, "ANTHROPIC_API_KEY", None)
    if not key:
        raise GatewayRefused(503, "JAI has no Anthropic key (ANTHROPIC_API_KEY in apps/backend/.env).",
                             "not_configured")
    headers = {"x-api-key": key, "anthropic-version": version or ANTHROPIC_VERSION,
               "content-type": "application/json"}
    if beta:
        headers["anthropic-beta"] = beta
    return headers


def stream_usage(events: str, usage: Dict[str, Any]) -> Dict[str, Any]:
    """Anthropic's usage from a stream's server-sent events: message_start carries the input side, each
    message_delta the output so far (docs.claude.com: streaming messages). Updates and returns usage."""
    for line in events.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "message_start":
            usage.update({k: v for k, v in ((event.get("message") or {}).get("usage") or {}).items()
                          if isinstance(v, (int, float))})
        elif event.get("type") == "message_delta":
            usage.update({k: v for k, v in (event.get("usage") or {}).items() if isinstance(v, (int, float))})
    return usage


async def forward_anthropic_stream(body: Dict[str, Any], version: Optional[str] = None, beta: Optional[str] = None,
                                   caller: str = "sandbox", client: Optional[httpx.AsyncClient] = None,
                                   run: Optional[Dict[str, Any]] = None
                                   ) -> Tuple[int, Dict[str, str], AsyncIterator[bytes]]:
    """Anthropic's Messages API as a stream, passed on as it arrives (Claude Code always streams): the same limit,
    allow-list and pricing as forward_anthropic, the cost recorded from the stream's own usage when it ends.
    Returns (status, headers, chunks); an upstream error arrives as its own body."""
    from app.core import spend
    from app.core.providers.router import mark_no_credit

    headers = _anthropic_ready(body, version, beta)
    try:
        await spend.check()
    except spend.SpendLimitReached as exc:
        raise GatewayRefused(429, str(exc), "spend_limit_reached") from exc
    await check_run(run)
    model = str(body.get("model") or "")
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))
    try:
        request = client.build_request("POST", f"{ANTHROPIC_UPSTREAM}/messages", json=body, headers=headers)
        response = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        if owned:
            await client.aclose()
        raise GatewayRefused(502, f"Anthropic could not be reached ({type(exc).__name__}).",
                             "upstream_unreachable") from exc
    status = response.status_code
    kind = response.headers.get("content-type", "text/event-stream")

    async def chunks() -> AsyncIterator[bytes]:
        usage: Dict[str, Any] = {}
        pending, seen = "", []
        try:
            async for chunk in response.aiter_bytes():
                if status < 400:
                    pending += chunk.decode("utf-8", errors="replace")
                    complete, _, pending = pending.rpartition("\n\n")
                    if complete:
                        stream_usage(complete, usage)
                else:
                    seen.append(chunk)
                yield chunk
        finally:
            await response.aclose()
            if owned:
                await client.aclose()
            if status < 400:
                stream_usage(pending, usage)
                spent = spend.text_cost(model, usage) or 0.0
                await spend.record("text", spent)
                await add_run_spend(run, spent)
                logger.info("gateway: anthropic stream %s for %s, $%.5f", model, caller, spent)
            else:
                text = b"".join(seen).decode("utf-8", errors="replace").lower()
                if any(word in text for word in ("credit balance", "billing", "insufficient", "quota")):
                    await mark_no_credit("claude")
                logger.warning("gateway: anthropic stream %s for %s answered %s", model, caller, status)

    return status, {"content-type": kind}, chunks()


async def count_anthropic_tokens(body: Dict[str, Any], version: Optional[str] = None, beta: Optional[str] = None,
                                 client: Optional[httpx.AsyncClient] = None) -> Tuple[int, Dict[str, Any]]:
    """Anthropic's free token count (POST /v1/messages/count_tokens), which Claude Code asks for."""
    headers = _anthropic_ready(body, version, beta)
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    try:
        response = await client.post(f"{ANTHROPIC_UPSTREAM}/messages/count_tokens", json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise GatewayRefused(502, f"Anthropic could not be reached ({type(exc).__name__}).",
                             "upstream_unreachable") from exc
    finally:
        if owned:
            await client.aclose()
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"type": "error", "error": {"type": "api_error", "message": response.text[:500]}}
