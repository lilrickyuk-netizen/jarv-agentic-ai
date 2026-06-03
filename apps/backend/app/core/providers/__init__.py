"""
JARV Backend - LLM Providers

Multi-provider LLM integration supporting Claude, OpenAI, and Gemini.
"""
from app.core.providers.base import (
    BaseLLMProvider,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    Message,
    ModelProvider,
    ProviderError,
    RateLimitError,
    AuthenticationError,
    InvalidRequestError,
    ModelNotFoundError,
)
from app.core.providers.claude import ClaudeProvider
from app.core.providers.openai import OpenAIProvider
from app.core.providers.gemini import GeminiProvider
from app.core.providers.ollama import OllamaProvider
from app.core.providers.router import (
    ModelRouter,
    get_router,
    complete,
    stream_complete,
)

__all__ = [
    # Base classes and types
    "BaseLLMProvider",
    "CompletionRequest",
    "CompletionResponse",
    "StreamChunk",
    "Message",
    "ModelProvider",
    # Exceptions
    "ProviderError",
    "RateLimitError",
    "AuthenticationError",
    "InvalidRequestError",
    "ModelNotFoundError",
    # Providers
    "ClaudeProvider",
    "OpenAIProvider",
    "GeminiProvider",
    "OllamaProvider",
    # Router
    "ModelRouter",
    "get_router",
    "complete",
    "stream_complete",
]
