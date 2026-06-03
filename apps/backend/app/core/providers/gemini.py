"""
JARV Backend - Google Gemini Provider

Implementation of Google Gemini API provider for LLM completions.
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


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini API provider implementation.

    Supports Gemini Pro, Gemini Pro Vision, and other Gemini models.
    """

    # Available Gemini models with their pricing (per million tokens)
    MODELS = {
        "gemini-pro": {
            "input_cost": 0.50,
            "output_cost": 1.50,
            "context_window": 32760,
        },
        "gemini-pro-vision": {
            "input_cost": 0.50,
            "output_cost": 1.50,
            "context_window": 16384,
        },
        "gemini-1.5-pro": {
            "input_cost": 3.50,
            "output_cost": 10.50,
            "context_window": 1000000,
        },
        "gemini-1.5-flash": {
            "input_cost": 0.35,
            "output_cost": 1.05,
            "context_window": 1000000,
        },
    }

    API_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        self.client = httpx.AsyncClient(
            base_url=self.API_BASE,
            timeout=httpx.Timeout(300.0),
        )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate a completion using Gemini API"""
        try:
            # Convert to Gemini format
            gemini_request = self._convert_request(request)

            # Build API URL with API key
            url = f"/models/{request.model}:generateContent"
            params = {"key": self.api_key}

            # Make API request
            response = await self.client.post(
                url, json=gemini_request, params=params
            )

            # Handle errors
            if response.status_code != 200:
                await self._handle_error(response)

            # Parse response
            data = response.json()
            return self._convert_response(data, request.model)

        except httpx.HTTPError as e:
            raise ProviderError(
                f"HTTP error calling Gemini API: {e}",
                provider="gemini",
                original_error=e,
            )

    async def stream_complete(
        self, request: CompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming completion using Gemini API"""
        try:
            # Convert to Gemini format
            gemini_request = self._convert_request(request)

            # Build API URL with API key
            url = f"/models/{request.model}:streamGenerateContent"
            params = {"key": self.api_key, "alt": "sse"}

            # Make streaming API request
            async with self.client.stream(
                "POST", url, json=gemini_request, params=params
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
                f"HTTP error calling Gemini API: {e}",
                provider="gemini",
                original_error=e,
            )

    def get_available_models(self) -> List[str]:
        """Get list of available Gemini models"""
        return list(self.MODELS.keys())

    def validate_model(self, model: str) -> bool:
        """Check if a model is valid for Gemini"""
        return model in self.MODELS

    def estimate_cost(
        self, request: CompletionRequest, response: CompletionResponse
    ) -> float:
        """Estimate the cost of a Gemini API request"""
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

        Note: This is a rough estimate. For accurate counts, use the
        Gemini tokenization API.
        """
        # Rough estimate: ~4 characters per token
        return len(text) // 4

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_tools(self) -> bool:
        return True

    def _convert_request(self, request: CompletionRequest) -> Dict[str, Any]:
        """Convert standard request to Gemini API format"""
        # Gemini uses a "contents" array with "parts"
        contents = []

        # Add system instruction if provided
        system_instruction = None
        if request.system:
            system_instruction = {"parts": [{"text": request.system}]}

        # Convert messages
        for msg in request.messages:
            role = "model" if msg.role == "assistant" else "user"
            contents.append({
                "role": role,
                "parts": [{"text": msg.content}],
            })

        gemini_request = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
                "topP": request.top_p,
            },
        }

        if system_instruction:
            gemini_request["systemInstruction"] = system_instruction

        if request.stop:
            gemini_request["generationConfig"]["stopSequences"] = request.stop

        if request.tools:
            # Convert tools to Gemini format
            gemini_request["tools"] = self._convert_tools(request.tools)

        return gemini_request

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert standard tool format to Gemini format"""
        # Gemini uses function declarations
        function_declarations = []

        for tool in tools:
            if tool.get("type") == "function":
                function = tool.get("function", {})
                function_declarations.append({
                    "name": function.get("name"),
                    "description": function.get("description"),
                    "parameters": function.get("parameters", {}),
                })

        return [{"functionDeclarations": function_declarations}]

    def _convert_response(self, data: Dict[str, Any], model: str) -> CompletionResponse:
        """Convert Gemini API response to standard format"""
        # Extract content from candidates
        content = ""
        tool_calls = None

        if data.get("candidates"):
            candidate = data["candidates"][0]
            if candidate.get("content", {}).get("parts"):
                for part in candidate["content"]["parts"]:
                    if "text" in part:
                        content += part["text"]
                    elif "functionCall" in part:
                        if tool_calls is None:
                            tool_calls = []
                        tool_calls.append({
                            "type": "function",
                            "function": {
                                "name": part["functionCall"]["name"],
                                "arguments": json.dumps(part["functionCall"]["args"]),
                            },
                        })

        # Extract usage if available
        usage = None
        if data.get("usageMetadata"):
            metadata = data["usageMetadata"]
            usage = {
                "input_tokens": metadata.get("promptTokenCount", 0),
                "output_tokens": metadata.get("candidatesTokenCount", 0),
                "total_tokens": metadata.get("totalTokenCount", 0),
            }

        finish_reason = "stop"
        if data.get("candidates"):
            finish_reason = data["candidates"][0].get("finishReason", "stop").lower()

        return CompletionResponse(
            id=data.get("modelVersion", ""),
            model=model,
            content=content,
            role="assistant",
            finish_reason=finish_reason,
            usage=usage,
            tool_calls=tool_calls,
            provider="gemini",
        )

    def _convert_stream_chunk(
        self, data: Dict[str, Any], model: str
    ) -> Optional[StreamChunk]:
        """Convert Gemini streaming chunk to standard format"""
        if not data.get("candidates"):
            return None

        candidate = data["candidates"][0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        delta = ""
        for part in parts:
            if "text" in part:
                delta += part["text"]

        finish_reason = None
        if candidate.get("finishReason"):
            finish_reason = candidate["finishReason"].lower()

        usage = None
        if data.get("usageMetadata"):
            metadata = data["usageMetadata"]
            usage = {
                "input_tokens": metadata.get("promptTokenCount", 0),
                "output_tokens": metadata.get("candidatesTokenCount", 0),
                "total_tokens": metadata.get("totalTokenCount", 0),
            }

        return StreamChunk(
            id=data.get("modelVersion", ""),
            model=model,
            delta=delta,
            finish_reason=finish_reason,
            usage=usage,
        )

    async def _handle_error(self, response: httpx.Response):
        """Handle HTTP errors from Gemini API"""
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
                f"Gemini API rate limit exceeded: {content}",
                provider="gemini",
                status_code=status_code,
            )
        elif status_code == 401 or status_code == 403:
            raise AuthenticationError(
                f"Gemini API authentication failed: {content}",
                provider="gemini",
                status_code=status_code,
            )
        elif status_code == 400:
            raise InvalidRequestError(
                f"Invalid request to Gemini API: {content}",
                provider="gemini",
                status_code=status_code,
            )
        elif status_code == 404:
            raise ModelNotFoundError(
                f"Model not found: {content}",
                provider="gemini",
                status_code=status_code,
            )
        else:
            raise ProviderError(
                f"Gemini API error: {content}",
                provider="gemini",
                status_code=status_code,
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
