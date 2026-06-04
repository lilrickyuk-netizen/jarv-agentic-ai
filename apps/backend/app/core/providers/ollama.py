"""
JARV Backend - Ollama Local Provider

Implementation of Ollama local LLM provider for running models locally.
"""
from typing import List, Optional, AsyncIterator, Dict, Any
import httpx
import json
import logging

from app.core.providers.base import (
    BaseLLMProvider,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    ProviderError,
    RateLimitError,
    AuthenticationError,
    InvalidRequestError,
    ModelNotFoundError,
)

logger = logging.getLogger(__name__)


class OllamaProvider(BaseLLMProvider):
    """
    Ollama local LLM provider implementation.

    Supports running models locally through Ollama, including:
    - llama2, llama3, mistral, mixtral, codellama, etc.
    - Custom models pulled from Ollama library
    """

    # Default pricing (local models are free, but we track for consistency)
    DEFAULT_PRICING = {
        "input_cost": 0.0,
        "output_cost": 0.0,
        "context_window": 4096,  # Default, varies by model
    }

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,
        **kwargs
    ):
        """
        Initialize Ollama provider.

        Args:
            base_url: Ollama API endpoint (default: http://localhost:11434)
            timeout: Request timeout in seconds
        """
        # Ollama doesn't use API keys, pass empty string to parent
        super().__init__(api_key="", **kwargs)
        self.base_url = base_url
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout),
        )
        self._available_models: Optional[List[str]] = None

    async def _check_availability(self) -> bool:
        """
        Check if Ollama service is available.

        Returns:
            True if Ollama is running and accessible
        """
        try:
            response = await self.client.get("/api/tags")
            return response.status_code == 200
        except (httpx.HTTPError, Exception) as e:
            logger.debug(f"Ollama not available at {self.base_url}: {e}")
            return False

    async def _fetch_available_models(self) -> List[str]:
        """
        Fetch list of available models from Ollama.

        Returns:
            List of model names
        """
        try:
            response = await self.client.get("/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = [model["name"] for model in data.get("models", [])]
                logger.info(f"Found {len(models)} Ollama models")
                return models
            return []
        except Exception as e:
            logger.warning(f"Failed to fetch Ollama models: {e}")
            return []

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate a completion using Ollama API"""
        try:
            # Check if Ollama is available
            if not await self._check_availability():
                raise ProviderError(
                    f"Ollama service not available at {self.base_url}",
                    provider="ollama",
                )

            # Convert to Ollama format
            ollama_request = self._convert_request(request)

            # Make API request
            response = await self.client.post(
                "/api/chat", json=ollama_request
            )

            # Handle errors
            if response.status_code != 200:
                await self._handle_error(response)

            # Parse response
            data = response.json()
            return self._convert_response(data, request.model)

        except httpx.HTTPError as e:
            raise ProviderError(
                f"HTTP error calling Ollama API: {e}",
                provider="ollama",
                original_error=e,
            )

    async def stream_complete(
        self, request: CompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming completion using Ollama API"""
        try:
            # Check if Ollama is available
            if not await self._check_availability():
                raise ProviderError(
                    f"Ollama service not available at {self.base_url}",
                    provider="ollama",
                )

            # Convert to Ollama format with streaming
            ollama_request = self._convert_request(request)
            ollama_request["stream"] = True

            # Make streaming API request
            async with self.client.stream(
                "POST", "/api/chat", json=ollama_request
            ) as response:
                # Handle errors
                if response.status_code != 200:
                    content = await response.aread()
                    await self._handle_error_from_content(
                        response.status_code, content
                    )

                # Stream response chunks
                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        chunk = self._convert_stream_chunk(data, request.model)
                        if chunk:
                            yield chunk

                        # Check if done
                        if data.get("done", False):
                            break
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse stream chunk: {line}")
                        continue

        except httpx.HTTPError as e:
            raise ProviderError(
                f"HTTP error calling Ollama API: {e}",
                provider="ollama",
                original_error=e,
            )

    def get_available_models(self) -> List[str]:
        """Get list of available Ollama models.

        Synchronous to match the provider interface (all other providers and
        the base class are sync, and callers invoke this without awaiting).
        Returns the cached list, or empty until populated via refresh_models().
        """
        return self._available_models or []

    async def refresh_models(self) -> List[str]:
        """Fetch and cache the live model list from the Ollama service."""
        self._available_models = await self._fetch_available_models()
        return self._available_models

    def validate_model(self, model: str) -> bool:
        """
        Check if a model is valid for Ollama.

        Note: Since Ollama models can be pulled dynamically,
        we do a loose validation here.
        """
        # Allow any non-empty model name for Ollama
        return bool(model)

    def estimate_cost(
        self, request: CompletionRequest, response: CompletionResponse
    ) -> float:
        """
        Estimate the cost of an Ollama API request.

        Note: Ollama runs locally, so cost is $0.
        """
        return 0.0

    def count_tokens(self, text: str, model: str) -> int:
        """
        Estimate token count for text.

        Note: This is a rough estimate. Ollama doesn't provide
        a tokenization API.
        """
        # Rough estimate: ~4 characters per token
        return len(text) // 4

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_tools(self) -> bool:
        # Ollama has limited tool support depending on model
        return False

    def _convert_request(self, request: CompletionRequest) -> Dict[str, Any]:
        """Convert standard request to Ollama API format"""
        messages = []

        # Add system message if provided
        if request.system:
            messages.append({
                "role": "system",
                "content": request.system,
            })

        # Add conversation messages
        for msg in request.messages:
            messages.append({
                "role": msg.role,
                "content": msg.content,
            })

        ollama_request = {
            "model": request.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
                "top_p": request.top_p,
            },
        }

        if request.stop:
            ollama_request["options"]["stop"] = request.stop

        return ollama_request

    def _convert_response(self, data: Dict[str, Any], model: str) -> CompletionResponse:
        """Convert Ollama API response to standard format"""
        message = data.get("message", {})
        content = message.get("content", "")

        # Extract usage if available
        usage = None
        if "prompt_eval_count" in data or "eval_count" in data:
            usage = {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            }

        return CompletionResponse(
            id=data.get("created_at", ""),
            model=model,
            content=content,
            role="assistant",
            finish_reason="stop" if data.get("done", False) else "length",
            usage=usage,
            tool_calls=None,
            provider="ollama",
        )

    def _convert_stream_chunk(
        self, data: Dict[str, Any], model: str
    ) -> Optional[StreamChunk]:
        """Convert Ollama streaming chunk to standard format"""
        message = data.get("message", {})
        delta = message.get("content", "")

        if not delta and not data.get("done", False):
            return None

        finish_reason = None
        if data.get("done", False):
            finish_reason = "stop"

        usage = None
        if data.get("done", False):
            if "prompt_eval_count" in data or "eval_count" in data:
                usage = {
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                }

        return StreamChunk(
            id=data.get("created_at", ""),
            model=model,
            delta=delta,
            finish_reason=finish_reason,
            usage=usage,
        )

    async def _handle_error(self, response: httpx.Response):
        """Handle HTTP errors from Ollama API"""
        try:
            error_data = response.json()
            error_message = error_data.get("error", str(response.text))
        except:
            error_message = response.text

        await self._handle_error_from_content(response.status_code, error_message)

    async def _handle_error_from_content(self, status_code: int, content: Any):
        """Handle errors based on status code and content"""
        if status_code == 404:
            raise ModelNotFoundError(
                f"Model not found in Ollama: {content}",
                provider="ollama",
                status_code=status_code,
            )
        elif status_code == 400:
            raise InvalidRequestError(
                f"Invalid request to Ollama API: {content}",
                provider="ollama",
                status_code=status_code,
            )
        else:
            raise ProviderError(
                f"Ollama API error: {content}",
                provider="ollama",
                status_code=status_code,
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
