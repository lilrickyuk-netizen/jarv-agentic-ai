"""
JARV Backend - Claude (Anthropic) Provider

Implementation of Claude API provider for LLM completions.
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


class ClaudeProvider(BaseLLMProvider):
    """
    Claude (Anthropic) API provider implementation.

    Supports Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku, and other models.
    """

    # Available Claude models with their pricing (per million tokens)
    MODELS = {
        # Current models
        "claude-opus-4-8": {
            "input_cost": 5.00,
            "output_cost": 25.00,
            "context_window": 1000000,
        },
        "claude-sonnet-4-6": {
            "input_cost": 3.00,
            "output_cost": 15.00,
            "context_window": 1000000,
        },
        "claude-haiku-4-5": {
            "input_cost": 1.00,
            "output_cost": 5.00,
            "context_window": 200000,
        },
        # Legacy models (retained for compatibility)
        "claude-3-5-sonnet-20241022": {
            "input_cost": 3.00,
            "output_cost": 15.00,
            "context_window": 200000,
        },
        "claude-3-5-sonnet-20240620": {
            "input_cost": 3.00,
            "output_cost": 15.00,
            "context_window": 200000,
        },
        "claude-3-opus-20240229": {
            "input_cost": 15.00,
            "output_cost": 75.00,
            "context_window": 200000,
        },
        "claude-3-sonnet-20240229": {
            "input_cost": 3.00,
            "output_cost": 15.00,
            "context_window": 200000,
        },
        "claude-3-haiku-20240307": {
            "input_cost": 0.25,
            "output_cost": 1.25,
            "context_window": 200000,
        },
    }

    API_BASE = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        self.client = httpx.AsyncClient(
            base_url=self.API_BASE,
            timeout=httpx.Timeout(300.0),
            headers={
                "x-api-key": api_key,
                "anthropic-version": self.API_VERSION,
                "content-type": "application/json",
            },
        )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate a completion using Claude API"""
        try:
            # Convert to Claude format
            claude_request = self._convert_request(request)

            # Make API request
            response = await self.client.post("/messages", json=claude_request)

            # Handle errors
            if response.status_code != 200:
                await self._handle_error(response)

            # Parse response
            data = response.json()
            return self._convert_response(data, request.model)

        except httpx.HTTPError as e:
            raise ProviderError(
                f"HTTP error calling Claude API: {e}",
                provider="claude",
                original_error=e,
            )

    async def stream_complete(
        self, request: CompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming completion using Claude API"""
        try:
            # Convert to Claude format with streaming
            claude_request = self._convert_request(request)
            claude_request["stream"] = True

            # Make streaming API request
            async with self.client.stream(
                "POST", "/messages", json=claude_request
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
                        chunk = self._convert_stream_chunk(data, request.model)
                        if chunk:
                            yield chunk
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse stream chunk: {data_str}")
                        continue

        except httpx.HTTPError as e:
            raise ProviderError(
                f"HTTP error calling Claude API: {e}",
                provider="claude",
                original_error=e,
            )

    def get_available_models(self) -> List[str]:
        """Get list of available Claude models"""
        return list(self.MODELS.keys())

    def validate_model(self, model: str) -> bool:
        """Check if a model is valid for Claude"""
        return model in self.MODELS

    def estimate_cost(
        self, request: CompletionRequest, response: CompletionResponse
    ) -> float:
        """Estimate the cost of a Claude API request"""
        if not response.usage or request.model not in self.MODELS:
            return 0.0

        model_pricing = self.MODELS[request.model]
        input_tokens = response.usage.get("input_tokens", 0)
        output_tokens = response.usage.get("output_tokens", 0)

        # Calculate cost (pricing is per million tokens)
        input_cost = (input_tokens / 1_000_000) * model_pricing["input_cost"]
        output_cost = (output_tokens / 1_000_000) * model_pricing["output_cost"]

        return input_cost + output_cost

    def count_tokens(self, text: str, model: str) -> int:
        """
        Estimate token count for text.

        Note: This is a rough estimate. For accurate counts, use the Anthropic
        tokenizer library or API.
        """
        # Rough estimate: ~4 characters per token
        return len(text) // 4

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_tools(self) -> bool:
        return True

    def _convert_request(self, request: CompletionRequest) -> Dict[str, Any]:
        """Convert standard request to Claude API format"""
        # Separate system message from other messages
        system = None
        messages = []

        for msg in request.messages:
            if msg.role == "system":
                system = msg.content
            else:
                messages.append({
                    "role": msg.role,
                    "content": msg.content,
                })

        # Use explicit system parameter if provided
        if request.system:
            system = request.system

        claude_request = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
        }

        # Sampling parameters: Opus 4.7+ reject temperature/top_p entirely, and
        # all Claude 4+ models reject temperature and top_p together. Send at
        # most one, and none for models that don't accept them.
        no_sampling = any(
            request.model.startswith(prefix)
            for prefix in ("claude-opus-4-8", "claude-opus-4-7")
        )
        if not no_sampling:
            if request.temperature is not None:
                claude_request["temperature"] = request.temperature
            elif request.top_p is not None:
                claude_request["top_p"] = request.top_p

        if system:
            claude_request["system"] = system

        if request.stop:
            claude_request["stop_sequences"] = request.stop

        if request.tools:
            claude_request["tools"] = request.tools

        if request.tool_choice:
            claude_request["tool_choice"] = {"type": request.tool_choice}

        return claude_request

    def _convert_response(self, data: Dict[str, Any], model: str) -> CompletionResponse:
        """Convert Claude API response to standard format"""
        # Extract content
        content = ""
        tool_calls = None

        if data.get("content"):
            for block in data["content"]:
                if block["type"] == "text":
                    content += block["text"]
                elif block["type"] == "tool_use":
                    if tool_calls is None:
                        tool_calls = []
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block["input"]),
                        },
                    })

        return CompletionResponse(
            id=data["id"],
            model=model,
            content=content,
            role=data["role"],
            finish_reason=data.get("stop_reason", "stop"),
            usage={
                "input_tokens": data["usage"]["input_tokens"],
                "output_tokens": data["usage"]["output_tokens"],
                "total_tokens": data["usage"]["input_tokens"]
                + data["usage"]["output_tokens"],
            },
            tool_calls=tool_calls,
            provider="claude",
        )

    def _convert_stream_chunk(
        self, data: Dict[str, Any], model: str
    ) -> Optional[StreamChunk]:
        """Convert Claude streaming chunk to standard format"""
        event_type = data.get("type")

        if event_type == "content_block_delta":
            delta = data.get("delta", {})
            if delta.get("type") == "text_delta":
                return StreamChunk(
                    id=data.get("message", {}).get("id", ""),
                    model=model,
                    delta=delta.get("text", ""),
                )

        elif event_type == "message_stop":
            return StreamChunk(
                id=data.get("message", {}).get("id", ""),
                model=model,
                delta="",
                finish_reason="stop",
            )

        return None

    async def _handle_error(self, response: httpx.Response):
        """Handle HTTP errors from Claude API"""
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
                f"Claude API rate limit exceeded: {content}",
                provider="claude",
                status_code=status_code,
            )
        elif status_code == 401:
            raise AuthenticationError(
                f"Claude API authentication failed: {content}",
                provider="claude",
                status_code=status_code,
            )
        elif status_code == 400:
            raise InvalidRequestError(
                f"Invalid request to Claude API: {content}",
                provider="claude",
                status_code=status_code,
            )
        elif status_code == 404:
            raise ModelNotFoundError(
                f"Model not found: {content}",
                provider="claude",
                status_code=status_code,
            )
        else:
            raise ProviderError(
                f"Claude API error: {content}",
                provider="claude",
                status_code=status_code,
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
