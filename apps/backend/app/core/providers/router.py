"""
JARV Backend - Model Router

Routes completion requests to the appropriate LLM provider based on model name.
"""
from typing import Dict, Optional, AsyncIterator
import logging

from app.core.providers.base import (
    BaseLLMProvider,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    ModelProvider,
    ProviderError,
    ModelNotFoundError,
)
from app.core.providers.claude import ClaudeProvider
from app.core.providers.openai import OpenAIProvider
from app.core.providers.gemini import GeminiProvider
from app.core.providers.ollama import OllamaProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


class ModelRouter:
    """
    Routes completion requests to the appropriate LLM provider.

    Automatically selects the correct provider based on the model name prefix
    (e.g., "gpt-" → OpenAI, "claude-" → Claude, "gemini-" → Gemini).
    """

    def __init__(self):
        """Initialize router with configured providers"""
        self.providers: Dict[str, BaseLLMProvider] = {}
        self._initialize_providers()

    def _initialize_providers(self):
        """Initialize all configured providers"""
        # Claude provider (primary)
        if hasattr(settings, 'CLAUDE_API_KEY') and settings.CLAUDE_API_KEY:
            try:
                self.providers[ModelProvider.CLAUDE] = ClaudeProvider(
                    api_key=settings.CLAUDE_API_KEY
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

        # Ollama provider (optional, local)
        ollama_base_url = getattr(settings, 'OLLAMA_BASE_URL', 'http://localhost:11434')
        if ollama_base_url:
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
        provider = self._get_provider_for_model(request.model)
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
