"""
JARV Backend - Base LLM Provider Interface

Abstract base class for all LLM providers (Claude, OpenAI, Gemini, etc.)
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, AsyncIterator
from dataclasses import dataclass
from enum import Enum


class ModelProvider(str, Enum):
    """Supported LLM providers"""
    CLAUDE = "claude"
    OPENAI = "openai"
    GEMINI = "gemini"
    OLLAMA = "ollama"


@dataclass
class Message:
    """Standard message format across all providers"""
    role: str  # "user", "assistant", "system"
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


@dataclass
class CompletionRequest:
    """Standard completion request format"""
    messages: List[Message]
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    stop: Optional[List[str]] = None
    stream: bool = False
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[str] = None
    system: Optional[str] = None


@dataclass
class CompletionResponse:
    """Standard completion response format"""
    id: str
    model: str
    content: str
    role: str = "assistant"
    finish_reason: str = "stop"
    usage: Optional[Dict[str, int]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    provider: Optional[str] = None


@dataclass
class StreamChunk:
    """Standard streaming chunk format"""
    id: str
    model: str
    delta: str
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    All provider implementations must inherit from this class and implement
    the required methods.
    """

    def __init__(self, api_key: str, **kwargs):
        """
        Initialize the provider with API credentials.

        Args:
            api_key: API key for the provider
            **kwargs: Additional provider-specific configuration
        """
        self.api_key = api_key
        self.config = kwargs

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """
        Generate a completion for the given request.

        Args:
            request: Standardized completion request

        Returns:
            Standardized completion response

        Raises:
            ProviderError: If the API request fails
        """
        pass

    @abstractmethod
    async def stream_complete(
        self,
        request: CompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """
        Generate a streaming completion for the given request.

        Args:
            request: Standardized completion request

        Yields:
            Stream chunks with incremental content

        Raises:
            ProviderError: If the API request fails
        """
        pass

    @abstractmethod
    def get_available_models(self) -> List[str]:
        """
        Get list of available models for this provider.

        Returns:
            List of model identifiers
        """
        pass

    @abstractmethod
    def validate_model(self, model: str) -> bool:
        """
        Check if a model is valid for this provider.

        Args:
            model: Model identifier

        Returns:
            True if valid, False otherwise
        """
        pass

    @abstractmethod
    def estimate_cost(self, request: CompletionRequest, response: CompletionResponse) -> float:
        """
        Estimate the cost of a completion request/response.

        Args:
            request: The completion request
            response: The completion response

        Returns:
            Estimated cost in USD
        """
        pass

    @abstractmethod
    def count_tokens(self, text: str, model: str) -> int:
        """
        Count tokens in text for the given model.

        Args:
            text: Text to count tokens for
            model: Model identifier

        Returns:
            Number of tokens
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the provider name"""
        pass

    @property
    @abstractmethod
    def supports_streaming(self) -> bool:
        """Check if provider supports streaming"""
        pass

    @property
    @abstractmethod
    def supports_tools(self) -> bool:
        """Check if provider supports tool/function calling"""
        pass


class ProviderError(Exception):
    """Base exception for provider errors"""
    def __init__(
        self,
        message: str,
        provider: str,
        status_code: Optional[int] = None,
        original_error: Optional[Exception] = None
    ):
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.original_error = original_error
        super().__init__(message)


class RateLimitError(ProviderError):
    """Provider rate limit exceeded"""
    pass


class AuthenticationError(ProviderError):
    """Provider authentication failed"""
    pass


class InvalidRequestError(ProviderError):
    """Invalid request to provider"""
    pass


class ModelNotFoundError(ProviderError):
    """Requested model not found"""
    pass
