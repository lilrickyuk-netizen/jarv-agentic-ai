"""
JARV Backend - OpenAI (GPT) Provider

Implementation of OpenAI API provider for LLM completions.
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


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI API provider implementation.

    Supports GPT-4, GPT-4 Turbo, GPT-3.5 Turbo, and other OpenAI models.
    """

    # Available OpenAI models with their pricing (per million tokens)
    MODELS = {
        "gpt-4-turbo": {
            "input_cost": 10.00,
            "output_cost": 30.00,
            "context_window": 128000,
        },
        "gpt-4-turbo-2024-04-09": {
            "input_cost": 10.00,
            "output_cost": 30.00,
            "context_window": 128000,
        },
        "gpt-4": {
            "input_cost": 30.00,
            "output_cost": 60.00,
            "context_window": 8192,
        },
        "gpt-4-32k": {
            "input_cost": 60.00,
            "output_cost": 120.00,
            "context_window": 32768,
        },
        "gpt-3.5-turbo": {
            "input_cost": 0.50,
            "output_cost": 1.50,
            "context_window": 16385,
        },
        "gpt-3.5-turbo-16k": {
            "input_cost": 3.00,
            "output_cost": 4.00,
            "context_window": 16385,
        },
    }

    API_BASE = "https://api.openai.com/v1"

    def __init__(self, api_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        self.client = httpx.AsyncClient(
            base_url=self.API_BASE,
            timeout=httpx.Timeout(300.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate a completion using OpenAI API"""
        try:
            # Convert to OpenAI format
            openai_request = self._convert_request(request)

            # Make API request
            response = await self.client.post(
                "/chat/completions", json=openai_request
            )

            # Handle errors
            if response.status_code != 200:
                await self._handle_error(response)

            # Parse response
            data = response.json()
            return self._convert_response(data)

        except httpx.HTTPError as e:
            raise ProviderError(
                f"HTTP error calling OpenAI API: {e}",
                provider="openai",
                original_error=e,
            )

    async def stream_complete(
        self, request: CompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming completion using OpenAI API"""
        try:
            # Convert to OpenAI format with streaming
            openai_request = self._convert_request(request)
            openai_request["stream"] = True

            # Make streaming API request
            async with self.client.stream(
                "POST", "/chat/completions", json=openai_request
            ) as response:
                # Handle errors
                if response.status_code != 200:
                    content = await response.aread()
                    await self._handle_error_from_content(
                        response.status_code, content
                    )

                # Stream response chunks
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    data_str = line[6:]  # Remove "data: " prefix
                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                        chunk = self._convert_stream_chunk(data)
                        if chunk:
                            yield chunk
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse stream chunk: {data_str}")
                        continue

        except httpx.HTTPError as e:
            raise ProviderError(
                f"HTTP error calling OpenAI API: {e}",
                provider="openai",
                original_error=e,
            )

    def get_available_models(self) -> List[str]:
        """Get list of available OpenAI models"""
        return list(self.MODELS.keys())

    def validate_model(self, model: str) -> bool:
        """Check if a model is valid for OpenAI"""
        return model in self.MODELS

    def estimate_cost(
        self, request: CompletionRequest, response: CompletionResponse
    ) -> float:
        """Estimate the cost of an OpenAI API request"""
        if not response.usage or request.model not in self.MODELS:
            return 0.0

        model_pricing = self.MODELS[request.model]
        input_tokens = response.usage.get("prompt_tokens", 0)
        output_tokens = response.usage.get("completion_tokens", 0)

        # Calculate cost (pricing is per million tokens)
        input_cost = (input_tokens / 1_000_000) * model_pricing["input_cost"]
        output_cost = (output_tokens / 1_000_000) * model_pricing["output_cost"]

        return input_cost + output_cost

    def count_tokens(self, text: str, model: str) -> int:
        """
        Estimate token count for text.

        Note: This is a rough estimate. For accurate counts, use tiktoken library.
        """
        # Rough estimate: ~4 characters per token
        return len(text) // 4

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_tools(self) -> bool:
        return True

    def _convert_request(self, request: CompletionRequest) -> Dict[str, Any]:
        """Convert standard request to OpenAI API format"""
        messages = []

        # Add system message if provided
        if request.system:
            messages.append({
                "role": "system",
                "content": request.system,
            })

        # Add conversation messages
        for msg in request.messages:
            message_dict = {
                "role": msg.role,
                "content": msg.content,
            }

            if msg.name:
                message_dict["name"] = msg.name

            if msg.tool_calls:
                message_dict["tool_calls"] = msg.tool_calls

            if msg.tool_call_id:
                message_dict["tool_call_id"] = msg.tool_call_id

            messages.append(message_dict)

        openai_request = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "top_p": request.top_p,
            "frequency_penalty": request.frequency_penalty,
            "presence_penalty": request.presence_penalty,
        }

        if request.stop:
            openai_request["stop"] = request.stop

        if request.tools:
            openai_request["tools"] = request.tools

        if request.tool_choice:
            openai_request["tool_choice"] = request.tool_choice

        return openai_request

    def _convert_response(self, data: Dict[str, Any]) -> CompletionResponse:
        """Convert OpenAI API response to standard format"""
        choice = data["choices"][0]
        message = choice["message"]

        return CompletionResponse(
            id=data["id"],
            model=data["model"],
            content=message.get("content", ""),
            role=message["role"],
            finish_reason=choice.get("finish_reason", "stop"),
            usage={
                "prompt_tokens": data["usage"]["prompt_tokens"],
                "completion_tokens": data["usage"]["completion_tokens"],
                "total_tokens": data["usage"]["total_tokens"],
            },
            tool_calls=message.get("tool_calls"),
            provider="openai",
        )

    def _convert_stream_chunk(self, data: Dict[str, Any]) -> Optional[StreamChunk]:
        """Convert OpenAI streaming chunk to standard format"""
        if not data.get("choices"):
            return None

        choice = data["choices"][0]
        delta = choice.get("delta", {})

        content = delta.get("content", "")
        finish_reason = choice.get("finish_reason")

        if content or finish_reason:
            return StreamChunk(
                id=data["id"],
                model=data["model"],
                delta=content,
                finish_reason=finish_reason,
                usage=data.get("usage"),
            )

        return None

    async def _handle_error(self, response: httpx.Response):
        """Handle HTTP errors from OpenAI API"""
        try:
            error_data = response.json()
            error_message = error_data.get("error", {}).get("message", str(response.text))
        except:
            error_message = response.text

        await self._handle_error_from_content(response.status_code, error_message)

    async def _handle_error_from_content(self, status_code: int, content: Any):
        """Handle errors based on status code and content"""
        if status_code == 429:
            raise RateLimitError(
                f"OpenAI API rate limit exceeded: {content}",
                provider="openai",
                status_code=status_code,
            )
        elif status_code == 401:
            raise AuthenticationError(
                f"OpenAI API authentication failed: {content}",
                provider="openai",
                status_code=status_code,
            )
        elif status_code == 400:
            raise InvalidRequestError(
                f"Invalid request to OpenAI API: {content}",
                provider="openai",
                status_code=status_code,
            )
        elif status_code == 404:
            raise ModelNotFoundError(
                f"Model not found: {content}",
                provider="openai",
                status_code=status_code,
            )
        else:
            raise ProviderError(
                f"OpenAI API error: {content}",
                provider="openai",
                status_code=status_code,
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
