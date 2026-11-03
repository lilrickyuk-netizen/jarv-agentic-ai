"""
JARV Backend - OpenAI (GPT) Provider

Implementation of OpenAI API provider for LLM completions.
"""
from typing import List, Optional, AsyncIterator, Dict, Any
import httpx
import json
import logging
import re

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



_UNSAFE_NAME = re.compile(r"[^a-zA-Z0-9_-]")


def _openai_name(name: str) -> str:
    """A tool name OpenAI accepts (letters, digits, _ and -, at most 64): "boundary.detect" -> "boundary__detect"."""
    return _UNSAFE_NAME.sub("__", name)[:64]


def _openai_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    """A tool definition in OpenAI's shape ({"type": "function", "function": {...}}).

    JARV defines tools in the Anthropic shape ({name, description, input_schema});
    OpenAI rejects those ("Missing required parameter: 'tools[0].type'")."""
    if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
        function = tool["function"]
        return {**tool, "function": {**function, "name": _openai_name(function["name"]),
                                     "parameters": _openai_schema(function.get("parameters")
                                                                  or {"type": "object", "properties": {}})}}
    return {"type": "function", "function": {
        "name": _openai_name(tool["name"]),
        "description": tool.get("description") or tool["name"],
        "parameters": _openai_schema(tool.get("input_schema") or tool.get("parameters")
                                     or {"type": "object", "properties": {}}),
    }}


def _openai_schema(schema: Any) -> Any:
    """A parameters schema OpenAI accepts: every array names its items, every object its properties."""
    if isinstance(schema, list):
        return [_openai_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    cleaned = {key: _openai_schema(value) for key, value in schema.items()}
    kind = cleaned.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    if "array" in kinds and "items" not in cleaned:
        cleaned["items"] = {}
    if "object" in kinds and "properties" not in cleaned and "additionalProperties" not in cleaned:
        cleaned["properties"] = {}
    return cleaned


def _tool_name(tool: Dict[str, Any]) -> str:
    return (tool.get("function") or {}).get("name") or tool.get("name") or ""


def _openai_messages_from_blocks(role: str, blocks: List[Any]) -> List[Dict[str, Any]]:
    """One Anthropic-shaped message (content blocks) as OpenAI chat messages."""
    text = "\n".join(str(b.get("text", "")) for b in blocks
                     if isinstance(b, dict) and b.get("type") == "text" and b.get("text"))
    if role == "assistant":
        calls = [{"id": b["id"], "type": "function",
                  "function": {"name": _openai_name(b["name"]), "arguments": json.dumps(b.get("input") or {})}}
                 for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
        message: Dict[str, Any] = {"role": "assistant", "content": text or None}
        if calls:
            message["tool_calls"] = calls
        return [message]
    out: List[Dict[str, Any]] = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "tool_result":
            content = b.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, default=str)
            out.append({"role": "tool", "tool_call_id": b.get("tool_use_id"), "content": content})
    if text:
        out.append({"role": role, "content": text})
    if not out:
        out.append({"role": role, "content": json.dumps(blocks, default=str)})
    return out

# Models whose tool-using requests go to the Responses API: on Chat Completions they take function tools only
# with reasoning switched off, so an agent would work every step without thinking.
RESPONSES_MODELS = frozenset({"gpt-6-luna"})
_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")


def _agent_effort(requested: Optional[str] = None) -> str:
    """The request's own effort when it names a valid one (the Verifier and the requirements step ask for
    high), otherwise OPENAI_AGENT_REASONING_EFFORT."""
    from app.core.config import settings

    if requested and str(requested).strip().lower() in _EFFORTS:
        return str(requested).strip().lower()
    effort = str(getattr(settings, "OPENAI_AGENT_REASONING_EFFORT", "medium") or "medium").strip().lower()
    return effort if effort in _EFFORTS else "medium"


def _responses_input(request: CompletionRequest) -> tuple:
    """(instructions, input items) for the Responses API, from JARV's Anthropic-shaped conversation."""
    instructions = [request.system] if request.system else []
    items: List[Dict[str, Any]] = []
    for msg in request.messages:
        if msg.role == "system":
            instructions.append(msg.content if isinstance(msg.content, str) else json.dumps(msg.content))
            continue
        if msg.role == "tool":
            items.append({"type": "function_call_output", "call_id": msg.tool_call_id,
                          "output": msg.content if isinstance(msg.content, str) else json.dumps(msg.content)})
            continue
        if not isinstance(msg.content, list):
            if msg.content:
                items.append({"role": msg.role, "content": msg.content})
            for call in msg.tool_calls or []:
                function = call.get("function") or {}
                items.append({"type": "function_call", "call_id": call.get("id"),
                              "name": _openai_name(function.get("name", "")),
                              "arguments": function.get("arguments") or "{}"})
            continue
        text = "\n".join(str(b.get("text", "")) for b in msg.content
                         if isinstance(b, dict) and b.get("type") == "text" and b.get("text"))
        if text:
            items.append({"role": msg.role, "content": text})
        for block in msg.content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                items.append({"type": "function_call", "call_id": block["id"], "name": _openai_name(block["name"]),
                              "arguments": json.dumps(block.get("input") or {})})
            elif block.get("type") == "tool_result":
                content = block.get("content")
                items.append({"type": "function_call_output", "call_id": block.get("tool_use_id"),
                              "output": content if isinstance(content, str) else json.dumps(content, default=str)})
    return "\n\n".join(instructions), items


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI API provider implementation.

    Supports GPT-4, GPT-4 Turbo, GPT-3.5 Turbo, and other OpenAI models.
    """

    # Available OpenAI models with their pricing (per million tokens)
    MODELS = {
        "gpt-6-luna": {
            "input_cost": 0.10,
            "output_cost": 0.50,
            "context_window": 1_050_000,
        },
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
            if self._uses_responses(request):
                response = await self.client.post("/responses", json=self._responses_request(request))
                if response.status_code != 200:
                    await self._handle_error(response)
                result = self._convert_responses_response(response.json(), request.model)
            else:
                # Convert to OpenAI format
                openai_request = self._convert_request(request)

                # Make API request
                response = await self.client.post(
                    "/chat/completions", json=openai_request
                )

                # Handle errors
                if response.status_code != 200:
                    await self._handle_error(response)

                # Parse response; tool names come back as sent, so restore JARV's own names.
                result = self._convert_response(response.json())
            original = {_openai_name(_tool_name(t)): _tool_name(t) for t in (request.tools or [])}
            for call in result.tool_calls or []:
                function = call.get("function") or {}
                if function.get("name") in original:
                    function["name"] = original[function["name"]]
            return result

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

        # Add conversation messages. JARV's agents speak the Anthropic shape (content
        # blocks: text, tool_use, tool_result); OpenAI needs assistant tool_calls and
        # one role "tool" message per result.
        for msg in request.messages:
            if isinstance(msg.content, list):
                messages.extend(_openai_messages_from_blocks(msg.role, msg.content))
                continue
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

        if request.model == "gpt-6-luna":
            openai_request = {
                "model": request.model,
                "messages": messages,
                "max_completion_tokens": request.max_tokens,
                # gpt-6-luna on chat completions takes function tools only with reasoning off
                # ("Function tools with reasoning_effort are not supported ... set reasoning_effort to 'none'").
                "reasoning_effort": "none" if request.tools else "low",
                "service_tier": "default",
            }
        else:
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
            openai_request["tools"] = [_openai_tool(tool) for tool in request.tools]

        if request.tool_choice:
            openai_request["tool_choice"] = {"any": "required"}.get(request.tool_choice, request.tool_choice)

        return openai_request

    @staticmethod
    def _uses_responses(request: CompletionRequest) -> bool:
        return request.model in RESPONSES_MODELS and bool(request.tools)

    def _responses_request(self, request: CompletionRequest) -> Dict[str, Any]:
        """A tool-using request on the Responses API, with the model reasoning between tool calls."""
        instructions, items = _responses_input(request)
        body: Dict[str, Any] = {
            "model": request.model,
            "input": items,
            "max_output_tokens": request.max_tokens,
            "reasoning": {"effort": _agent_effort(getattr(request, "reasoning_effort", None))},
            "tools": [{"type": "function", "name": t["function"]["name"],
                       "description": t["function"].get("description") or t["function"]["name"],
                       "parameters": t["function"]["parameters"], "strict": False}
                      for t in (_openai_tool(tool) for tool in request.tools or [])],
            "store": False,
            "service_tier": "default",
        }
        if instructions:
            body["instructions"] = instructions
        if request.tool_choice:
            body["tool_choice"] = {"any": "required"}.get(request.tool_choice, request.tool_choice)
        if getattr(request, "prompt_cache_key", None):
            # One key per mission: every step's identical opening is served from the prompt cache.
            body["prompt_cache_key"] = str(request.prompt_cache_key)[:64]
            from app.core.config import settings

            ttl = str(getattr(settings, "OPENAI_PROMPT_CACHE_TTL", "") or "").strip()
            if ttl:
                body["prompt_cache_options"] = {"ttl": ttl}
        return body

    def _convert_responses_response(self, data: Dict[str, Any], model: str) -> CompletionResponse:
        text: List[str] = []
        calls: List[Dict[str, Any]] = []
        for item in data.get("output") or []:
            if item.get("type") == "message":
                text += [part.get("text", "") for part in item.get("content") or []
                         if part.get("type") == "output_text"]
            elif item.get("type") == "function_call":
                calls.append({"id": item.get("call_id") or item.get("id"), "type": "function",
                              "function": {"name": item.get("name", ""), "arguments": item.get("arguments") or "{}"}})
        usage = data.get("usage") or {}
        incomplete = (data.get("incomplete_details") or {}).get("reason")
        return CompletionResponse(
            id=data.get("id", ""), model=data.get("model") or model, content="".join(text),
            finish_reason="tool_calls" if calls else ("length" if incomplete == "max_output_tokens" else "stop"),
            usage={"prompt_tokens": int(usage.get("input_tokens") or 0),
                   "completion_tokens": int(usage.get("output_tokens") or 0),
                   "reasoning_tokens": int((usage.get("output_tokens_details") or {}).get("reasoning_tokens") or 0),
                   "cached_tokens": int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0),
                   "cache_write_tokens": int((usage.get("input_tokens_details") or {}).get("cache_write_tokens")
                                             or usage.get("cache_write_tokens") or 0),
                   "total_tokens": int(usage.get("total_tokens") or 0)},
            tool_calls=calls or None, provider="openai")

    def _convert_response(self, data: Dict[str, Any]) -> CompletionResponse:
        """Convert OpenAI API response to standard format"""
        choice = data["choices"][0]
        message = choice["message"]

        return CompletionResponse(
            id=data["id"],
            model=data["model"],
            content=message.get("content") or "",  # null when the model only calls tools
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
