import pytest

from app.api.command import command_info
from app.core.command.service import _provider_name_for_model
from app.core.config import settings
from app.core.providers.base import CompletionRequest, Message
from app.core.providers.openai import OpenAIProvider


def test_gpt_6_luna_is_registered_with_standard_pricing():
    assert OpenAIProvider.MODELS["gpt-6-luna"] == {
        "input_cost": 0.10,
        "output_cost": 0.50,
        "context_window": 1_050_000,
    }


@pytest.mark.asyncio
async def test_gpt_6_luna_request_is_bounded_and_uses_standard_tier():
    provider = OpenAIProvider(api_key="unit-test-key")
    try:
        request = CompletionRequest(
            model="gpt-6-luna",
            messages=[Message(role="user", content="Check service health.")],
            max_tokens=48,
        )

        payload = provider._convert_request(request)

        assert provider.validate_model("gpt-6-luna")
        assert payload["model"] == "gpt-6-luna"
        assert payload["max_completion_tokens"] == 48
        assert payload["reasoning_effort"] == "low"
        assert payload["service_tier"] == "default"
        assert "max_tokens" not in payload
        assert "temperature" not in payload
        assert "frequency_penalty" not in payload
        assert "presence_penalty" not in payload
    finally:
        await provider.client.aclose()


def test_command_provider_name_uses_model_family():
    assert _provider_name_for_model("gpt-6-luna") == "openai"
    assert _provider_name_for_model("claude-sonnet-4-6") == "claude"


@pytest.mark.asyncio
async def test_command_info_reports_configured_model(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_MODEL", "gpt-6-luna")

    assert await command_info() == {"provider": "openai", "model": "gpt-6-luna"}
