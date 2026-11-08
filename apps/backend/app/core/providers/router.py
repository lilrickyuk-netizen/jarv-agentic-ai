"""
JAI Backend - Model Router

Routes completion requests to the appropriate LLM provider based on model name.
"""
from dataclasses import replace
from typing import Any, Dict, List, Optional, AsyncIterator
import asyncio
import logging
import time

from app.core.providers.base import (
    BaseLLMProvider,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    ModelProvider,
    ProviderError,
    ModelNotFoundError,
    AuthenticationError,
    RateLimitError,
    InvalidRequestError,
)
from app.core.providers.claude import ClaudeProvider
from app.core.providers.openai import OpenAIProvider
from app.core.providers.gemini import GeminiProvider
from app.core.providers.ollama import OllamaProvider
from app.core.config import settings

logger = logging.getLogger(__name__)

# Model tiers per provider, used when a request has to move to another provider.
TIER_MODELS: Dict[str, Dict[str, str]] = {
    # Opus 5.5 for hard work; light work that has to leave OpenAI goes to the quick, cheap Haiku.
    ModelProvider.CLAUDE: {"top": "claude-opus-5-5", "standard": "claude-haiku-4-5", "fast": "claude-haiku-4-5"},
    ModelProvider.GEMINI: {"top": "gemini-1.5-pro", "standard": "gemini-1.5-pro", "fast": "gemini-1.5-flash"},
}
PROVIDER_REST_SECONDS = 600
# A provider out of credit stays at the back of the queue for hours, not minutes: topping up takes a person.
NO_CREDIT_REST_SECONDS = 6 * 3600
NO_CREDIT_KEY = "provider:{}:no_credit"
_ACCOUNT_PROBLEMS = ("credit balance", "billing", "quota", "insufficient", "payment", "exceeded your current")


def _provider_for_model_name(model: str) -> Optional[str]:
    name = (model or "").lower()
    if name.startswith("claude-"):
        return ModelProvider.CLAUDE
    if name.startswith("gpt-") or name.startswith(("o1", "o3", "o4")):
        return ModelProvider.OPENAI
    if name.startswith("gemini-"):
        return ModelProvider.GEMINI
    if name:
        return ModelProvider.OLLAMA
    return None


def _tier(model: str) -> str:
    name = (model or "").lower()
    if any(word in name for word in ("haiku", "flash", "mini", "nano", "3.5")):
        return "fast"
    if any(word in name for word in ("opus", "-pro", "gpt-4-32k")):
        return "top"
    return "standard"


def _tier_model(provider_key: str, tier: str) -> str:
    if provider_key == ModelProvider.OPENAI:
        if tier == "top":  # Opus's stand-in on OpenAI: Sol
            return getattr(settings, "OPENAI_REASONING_MODEL", "gpt-6-sol") or "gpt-6-sol"
        return getattr(settings, "OPENAI_MODEL", "gpt-6-luna") or "gpt-6-luna"
    if provider_key == ModelProvider.OLLAMA:
        return getattr(settings, "OLLAMA_MODEL", "llama3.1") or "llama3.1"
    return TIER_MODELS[provider_key][tier]


def tiered(model: str) -> str:
    """The model JAI's tiers choose for a request: hard thinking (the default model, Sol, any top-tier model)
    stays as asked; everything else is light work for LIGHT_MODEL."""
    if not getattr(settings, "MODEL_TIERS_ENABLED", False):
        return model
    heavy = {str(getattr(settings, "DEFAULT_MODEL", "") or ""), str(getattr(settings, "OPENAI_REASONING_MODEL", ""))}
    if model in heavy or _tier(model) == "top":
        return model
    return str(getattr(settings, "LIGHT_MODEL", "") or model)


def _out_of_credit(exc: ProviderError) -> bool:
    return any(word in str(exc).lower() for word in _NO_CREDIT)


async def mark_no_credit(provider_key: str) -> None:
    """Tell the rest of JAI (the sandbox among them) that this provider has no credit, for a few hours."""
    try:
        from app.core.redis import get_redis

        await (await get_redis()).set(NO_CREDIT_KEY.format(provider_key), "1", ex=NO_CREDIT_REST_SECONDS)
    except Exception as exc:  # noqa: BLE001 - the router itself already knows
        logger.info(f"no-credit mark not shared: {exc}")


async def has_no_credit(provider_key: str) -> bool:
    try:
        from app.core.redis import get_redis

        return bool(await (await get_redis()).get(NO_CREDIT_KEY.format(provider_key)))
    except Exception:  # noqa: BLE001
        return False


def _provider_order() -> List[str]:
    known = {p.value: p for p in ModelProvider}
    raw = getattr(settings, "PROVIDER_ORDER", "") or "claude,openai,gemini,ollama"
    order = [known[n.strip().lower()] for n in raw.split(",") if n.strip().lower() in known]
    return order + [p for p in ModelProvider if p not in order]


# A dropped connection, a timeout, an overloaded or briefly failing server: the same provider is asked
# again after these pauses before JAI gives up on it. Account problems (bad key, no credit, quota) are
# never retried: waiting does not fix them.
RETRY_DELAYS_SECONDS = (2.0, 6.0, 15.0)
_NO_CREDIT = ("insufficient_quota", "quota", "billing", "credit balance", "payment")


def _transient(exc: ProviderError) -> bool:
    if isinstance(exc, (AuthenticationError, ModelNotFoundError, InvalidRequestError)):
        return False
    if any(word in str(exc).lower() for word in _NO_CREDIT):
        return False
    status = getattr(exc, "status_code", None)
    return status is None or status in (408, 409, 425, 429, 500, 502, 503, 504, 529)


def _retry_delays() -> tuple:
    return (0.0,) * len(RETRY_DELAYS_SECONDS) if getattr(settings, "TESTING", False) else RETRY_DELAYS_SECONDS


def _fails_over(exc: ProviderError) -> bool:
    """Account and availability problems move to the next provider; a malformed
    request does not (another provider would reject it too)."""
    if isinstance(exc, (AuthenticationError, RateLimitError, ModelNotFoundError)):
        return True
    if isinstance(exc, InvalidRequestError):
        return any(word in str(exc).lower() for word in _ACCOUNT_PROBLEMS)
    status = getattr(exc, "status_code", None)
    return status is None or status >= 500 or status in (402, 403, 408, 409, 529)


class ModelRouter:
    """
    Routes completion requests to the appropriate LLM provider.

    Automatically selects the correct provider based on the model name prefix
    (e.g., "gpt-" → OpenAI, "claude-" → Claude, "gemini-" → Gemini).
    """

    def __init__(self):
        """Initialize router with configured providers"""
        self.providers: Dict[str, BaseLLMProvider] = {}
        self._resting_until: Dict[str, float] = {}
        self._initialize_providers()

    def _initialize_providers(self):
        """Initialize all configured providers"""
        # Claude provider (primary)
        claude_key = getattr(settings, 'CLAUDE_API_KEY', None) or getattr(settings, 'ANTHROPIC_API_KEY', None)
        if claude_key:
            try:
                self.providers[ModelProvider.CLAUDE] = ClaudeProvider(
                    api_key=claude_key
                )
                logger.info("Claude provider initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Claude provider: {e}")

        # OpenAI provider (optional)
        if hasattr(settings, 'OPENAI_API_KEY') and settings.OPENAI_API_KEY:
            try:
                self.providers[ModelProvider.OPENAI] = OpenAIProvider(
                    api_key=settings.OPENAI_API_KEY
                )
                logger.info("OpenAI provider initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI provider: {e}")

        # Gemini provider (optional)
        if hasattr(settings, 'GEMINI_API_KEY') and settings.GEMINI_API_KEY:
            try:
                self.providers[ModelProvider.GEMINI] = GeminiProvider(
                    api_key=settings.GEMINI_API_KEY
                )
                logger.info("Gemini provider initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini provider: {e}")

        # Ollama provider (optional, local): only when switched on, since a
        # default URL with no server behind it is not a usable provider.
        ollama_base_url = getattr(settings, 'OLLAMA_BASE_URL', 'http://localhost:11434')
        if ollama_base_url and getattr(settings, 'OLLAMA_ENABLED', False):
            try:
                self.providers[ModelProvider.OLLAMA] = OllamaProvider(
                    base_url=ollama_base_url
                )
                logger.info(f"Ollama provider initialized at {ollama_base_url}")
            except Exception as e:
                logger.warning(f"Failed to initialize Ollama provider: {e}")

        if not self.providers:
            logger.warning(
                "No LLM providers initialized. Please configure API keys."
            )

    def _get_provider_for_model(self, model: str) -> BaseLLMProvider:
        """
        Determine which provider to use for a given model.

        Args:
            model: Model identifier

        Returns:
            Provider instance

        Raises:
            ModelNotFoundError: If no provider supports the model
        """
        # Determine provider based on model name prefix
        model_lower = model.lower()

        if model_lower.startswith("claude-"):
            provider_key = ModelProvider.CLAUDE
        elif model_lower.startswith("gpt-"):
            provider_key = ModelProvider.OPENAI
        elif model_lower.startswith("gemini-"):
            provider_key = ModelProvider.GEMINI
        elif any(model_lower.startswith(prefix) for prefix in [
            "llama", "mistral", "mixtral", "codellama", "phi", "vicuna",
            "orca", "wizardlm", "neural-chat", "starling", "dolphin"
        ]):
            # Common Ollama model prefixes
            provider_key = ModelProvider.OLLAMA
        else:
            # Try to match by checking each provider's available models
            for provider_key, provider in self.providers.items():
                if provider.validate_model(model):
                    return provider

            raise ModelNotFoundError(
                f"No provider found for model: {model}",
                provider="router",
            )

        # Get the provider
        if provider_key not in self.providers:
            available = ", ".join(self.providers.keys())
            raise ProviderError(
                f"Provider {provider_key} not configured. Available providers: {available}",
                provider="router",
            )

        provider = self.providers[provider_key]

        # Validate model is supported by provider
        if not provider.validate_model(model):
            raise ModelNotFoundError(
                f"Model {model} not supported by provider {provider_key}",
                provider=provider_key,
            )

        return provider

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """
        Generate a completion by routing to the appropriate provider.

        Args:
            request: Standardized completion request

        Returns:
            Standardized completion response

        Raises:
            ModelNotFoundError: If no provider supports the model
            ProviderError: If the provider request fails
        """
        # Today's AI spending limit (Wave 1): no call is made once it is reached.
        from app.core import spend

        await spend.check()
        model = tiered(request.model)
        if model != request.model:
            request = replace(request, model=model)
        candidates = self.plan(request.model)
        if not candidates:
            raise ProviderError(
                "No model provider is configured. Add CLAUDE_API_KEY (or ANTHROPIC_API_KEY), "
                "OPENAI_API_KEY or GEMINI_API_KEY to apps/backend/.env, or set OLLAMA_ENABLED=true "
                "with a running Ollama server, then restart backend and worker.",
                provider="router",
            )
        failures: List[str] = []
        for provider_key, model in candidates:
            attempt = request if model == request.model else replace(request, model=model)
            try:
                response = await self._complete_retrying(self.providers[provider_key], attempt)
            except ProviderError as exc:
                if not _fails_over(exc):
                    raise
                failures.append(f"{provider_key.value if hasattr(provider_key, 'value') else provider_key}: {exc}")
                if _out_of_credit(exc):
                    self._resting_until[provider_key] = time.monotonic() + NO_CREDIT_REST_SECONDS
                    await mark_no_credit(str(getattr(provider_key, "value", provider_key)))
                else:
                    self._resting_until[provider_key] = time.monotonic() + PROVIDER_REST_SECONDS
                logger.warning(f"Provider {provider_key} unavailable for {model}; trying the next one. ({exc})")
                continue
            self._resting_until.pop(provider_key, None)
            cost = spend.text_cost(response.model or model, response.usage)
            if cost is None:
                try:
                    cost = float(self.providers[provider_key].estimate_cost(attempt, response) or 0.0)
                except Exception:  # noqa: BLE001 - a model with no price is counted as a call
                    cost = 0.0
            await spend.record("text", cost)
            if model != request.model:
                logger.warning(f"Model {request.model} served by {model} ({provider_key}) instead")
                response.provider = response.provider or str(getattr(provider_key, "value", provider_key))
            return response
        raise ProviderError("Every configured provider failed: " + " | ".join(failures)[:2000],
                            provider="router")

    def plan(self, model: str) -> List[tuple]:
        """(provider, model) pairs to try, in order: the requested model on its
        own provider when configured, then the same tier on each other configured
        provider in PROVIDER_ORDER."""
        own = _provider_for_model_name(model)
        tier = _tier(model)
        plan: List[tuple] = []
        if own is not None and own in self.providers:
            plan.append((own, model))
        for key in _provider_order():
            if key == own or key not in self.providers:
                continue
            plan.append((key, _tier_model(key, tier)))
        # A provider that just failed for an account reason (no credit, bad key,
        # rate limit) is tried last for a while instead of first on every call.
        now = time.monotonic()
        resting = [entry for entry in plan if self._resting_until.get(entry[0], 0) > now]
        return [entry for entry in plan if entry not in resting] + resting

    async def _complete_retrying(self, provider: BaseLLMProvider, request: CompletionRequest) -> CompletionResponse:
        """One provider, asked again after a short pause when the failure is transient."""
        delays = _retry_delays()
        for number in range(len(delays) + 1):
            try:
                return await self._complete_with(provider, request)
            except ProviderError as exc:
                if number >= len(delays) or not _transient(exc):
                    raise
                logger.warning(f"{provider.provider_name} failed transiently ({str(exc)[:200]}); "
                               f"retrying in {delays[number]:.0f}s (attempt {number + 2} of {len(delays) + 1})")
                await asyncio.sleep(delays[number])
        raise RuntimeError("unreachable")

    async def _complete_with(self, provider: BaseLLMProvider, request: CompletionRequest) -> CompletionResponse:
        logger.info(
            f"Routing completion request to {provider.provider_name} "
            f"for model {request.model}"
        )

        try:
            response = await provider.complete(request)

            # Log usage and cost
            if response.usage:
                cost = provider.estimate_cost(request, response)
                logger.info(
                    f"Completion completed: "
                    f"input_tokens={response.usage.get('input_tokens', 0)}, "
                    f"output_tokens={response.usage.get('output_tokens', 0)}, "
                    f"estimated_cost=${cost:.6f}"
                )

            return response

        except Exception as e:
            logger.error(
                f"Error in {provider.provider_name} completion: {e}",
                exc_info=True,
            )
            raise

    async def stream_complete(
        self, request: CompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """
        Generate a streaming completion by routing to the appropriate provider.

        Args:
            request: Standardized completion request

        Yields:
            Stream chunks with incremental content

        Raises:
            ModelNotFoundError: If no provider supports the model
            ProviderError: If the provider request fails
        """
        provider = self._get_provider_for_model(request.model)
        logger.info(
            f"Routing streaming completion request to {provider.provider_name} "
            f"for model {request.model}"
        )

        try:
            async for chunk in provider.stream_complete(request):
                yield chunk

        except Exception as e:
            logger.error(
                f"Error in {provider.provider_name} streaming completion: {e}",
                exc_info=True,
            )
            raise

    def get_available_models(self, provider: Optional[str] = None) -> Dict[str, list]:
        """
        Get available models, optionally filtered by provider.

        Args:
            provider: Optional provider name to filter by

        Returns:
            Dictionary mapping provider names to lists of available models
        """
        if provider:
            if provider in self.providers:
                return {provider: self.providers[provider].get_available_models()}
            return {}

        return {
            provider_name: provider_instance.get_available_models()
            for provider_name, provider_instance in self.providers.items()
        }

    def get_provider_info(self) -> Dict[str, Dict[str, Any]]:
        """
        Get information about configured providers.

        Returns:
            Dictionary with provider information
        """
        return {
            provider_name: {
                "name": provider.provider_name,
                "supports_streaming": provider.supports_streaming,
                "supports_tools": provider.supports_tools,
                "available_models": provider.get_available_models(),
            }
            for provider_name, provider in self.providers.items()
        }

    def is_provider_available(self, provider: str) -> bool:
        """
        Check if a provider is configured and available.

        Args:
            provider: Provider name

        Returns:
            True if available, False otherwise
        """
        return provider in self.providers


# Global router instance
_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    """
    Get the global model router instance.

    Returns:
        ModelRouter instance
    """
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


async def complete(request: CompletionRequest) -> CompletionResponse:
    """
    Convenience function for generating completions.

    Args:
        request: Standardized completion request

    Returns:
        Standardized completion response
    """
    router = get_router()
    return await router.complete(request)


async def stream_complete(request: CompletionRequest) -> AsyncIterator[StreamChunk]:
    """
    Convenience function for generating streaming completions.

    Args:
        request: Standardized completion request

    Yields:
        Stream chunks with incremental content
    """
    router = get_router()
    async for chunk in router.stream_complete(request):
        yield chunk
