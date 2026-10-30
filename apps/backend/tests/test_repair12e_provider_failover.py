"""Repair 12e: model routing fails over between providers.

Provider HTTP clients are replaced by in-process doubles that raise the same
ProviderError subclasses the real Claude/OpenAI adapters raise for the matching
HTTP responses; the router's planning, tier mapping, failover, and resting are real.
"""
import asyncio

import pytest

import app.core.config as config
from app.core.providers.base import (
    AuthenticationError, CompletionRequest, CompletionResponse, InvalidRequestError, Message, ModelProvider,
    ProviderError, RateLimitError,
)
from app.core.providers.router import ModelRouter


class FakeProvider:
    def __init__(self, name, error=None):
        self.name, self.error, self.calls = name, error, []

    provider_name = property(lambda self: self.name)

    async def complete(self, request):
        self.calls.append(request.model)
        if self.error is not None:
            raise self.error
        return CompletionResponse(id="r", model=request.model, content=f"{self.name} answered",
                                  usage={"input_tokens": 1, "output_tokens": 1}, provider=self.name)

    def estimate_cost(self, request, response):
        return 0.0

    def validate_model(self, model):
        return True


def _router(monkeypatch, **providers):
    monkeypatch.setattr(config.settings, "PROVIDER_ORDER", "claude,openai,gemini,ollama", raising=False)
    monkeypatch.setattr(config.settings, "OPENAI_MODEL", "gpt-6-luna", raising=False)
    router = ModelRouter.__new__(ModelRouter)
    router.providers = {ModelProvider(k): v for k, v in providers.items()}
    router._resting_until = {}
    return router


def _ask(router, model="claude-sonnet-4-6"):
    return asyncio.run(router.complete(CompletionRequest(messages=[Message(role="user", content="hi")], model=model)))


def test_claude_model_runs_on_openai_when_only_openai_is_configured(monkeypatch):
    openai = FakeProvider("openai")
    response = _ask(_router(monkeypatch, openai=openai))
    assert response.content == "openai answered" and openai.calls == ["gpt-6-luna"]


def test_claude_without_credit_falls_over_to_openai_and_rests(monkeypatch):
    claude = FakeProvider("claude", InvalidRequestError(
        "Invalid request to Claude API: Your credit balance is too low to access the Anthropic API.",
        provider="claude", status_code=400))
    openai = FakeProvider("openai")
    router = _router(monkeypatch, claude=claude, openai=openai)

    first = _ask(router)
    second = _ask(router)

    assert first.content == second.content == "openai answered"
    assert claude.calls == ["claude-sonnet-4-6"]  # rested after the first failure
    assert openai.calls == ["gpt-6-luna", "gpt-6-luna"]


def test_tiers_map_across_providers(monkeypatch):
    gemini = FakeProvider("gemini")
    router = _router(monkeypatch, gemini=gemini)
    _ask(router, "claude-haiku-4-5")
    _ask(router, "claude-opus-4-8")
    assert gemini.calls == ["gemini-1.5-flash", "gemini-1.5-pro"]


def test_malformed_requests_do_not_fail_over(monkeypatch):
    claude = FakeProvider("claude", InvalidRequestError("messages: field required", provider="claude", status_code=400))
    openai = FakeProvider("openai")
    with pytest.raises(InvalidRequestError):
        _ask(_router(monkeypatch, claude=claude, openai=openai))
    assert openai.calls == []


def test_every_provider_failing_reports_each_reason(monkeypatch):
    claude = FakeProvider("claude", AuthenticationError("bad key", provider="claude", status_code=401))
    openai = FakeProvider("openai", RateLimitError("insufficient_quota", provider="openai", status_code=429))
    with pytest.raises(ProviderError, match="claude: bad key.*openai: insufficient_quota"):
        _ask(_router(monkeypatch, claude=claude, openai=openai))


def test_no_provider_names_the_keys_to_add(monkeypatch):
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        _ask(_router(monkeypatch))


def test_ollama_is_only_a_provider_when_switched_on(monkeypatch):
    for key in ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setattr(config.settings, key, None, raising=False)
    monkeypatch.setattr(config.settings, "OLLAMA_ENABLED", False, raising=False)
    assert ModelRouter().providers == {}
    monkeypatch.setattr(config.settings, "OLLAMA_ENABLED", True, raising=False)
    assert list(ModelRouter().providers) == [ModelProvider.OLLAMA]
