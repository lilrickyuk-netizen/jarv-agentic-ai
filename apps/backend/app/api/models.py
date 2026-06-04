"""
JARV Backend - Model Management API

Endpoints for managing LLM providers and models.
"""
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
import logging

from app.core.providers import (
    get_router,
    CompletionRequest,
    Message,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])


class ModelTestRequest(BaseModel):
    """Request to test a model"""
    model: str = Field(..., description="Model identifier to test")
    prompt: str = Field(
        default="Hello! Please respond with a brief greeting.",
        description="Test prompt to send to model"
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=100, ge=1, le=4096)


class ModelTestResponse(BaseModel):
    """Response from model test"""
    success: bool
    model: str
    provider: str
    response: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    estimated_cost: Optional[float] = None
    error: Optional[str] = None


class ProviderInfo(BaseModel):
    """Information about a provider"""
    name: str
    available: bool
    supports_streaming: bool
    supports_tools: bool
    models: List[str]
    status: str = "ready"  # ready | configured_no_model | unavailable
    message: Optional[str] = None


class ModelInfo(BaseModel):
    """Information about a model"""
    name: str
    provider: str


@router.get(
    "/providers",
    response_model=Dict[str, ProviderInfo],
    summary="List available LLM providers",
    description="Get information about all configured LLM providers including their capabilities and available models"
)
async def list_providers() -> Dict[str, ProviderInfo]:
    """
    List all available LLM providers.

    Returns:
        Dictionary mapping provider names to provider information
    """
    try:
        router_instance = get_router()
        provider_info = router_instance.get_provider_info()

        result = {}
        for provider_name, info in provider_info.items():
            key = provider_name.value if hasattr(provider_name, "value") else str(provider_name)
            models = list(info.get("available_models") or [])
            status_str = "ready"
            message: Optional[str] = None
            available = True

            if "ollama" in key.lower():
                # Real readiness check: query the local Ollama model inventory.
                provider = router_instance.providers.get(provider_name)
                live_models: List[str] = []
                reachable = False
                try:
                    if provider is not None and hasattr(provider, "refresh_models"):
                        live_models = await provider.refresh_models()
                        reachable = True
                except Exception:  # noqa: BLE001
                    reachable = False
                models = live_models
                if reachable and live_models:
                    status_str, available = "ready", True
                    message = f"{len(live_models)} local model(s) available."
                elif reachable and not live_models:
                    status_str, available = "configured_no_model", False
                    message = ("Ollama is reachable but no model is pulled. Run "
                               "`ollama pull llama3` to enable local inference. "
                               "Claude remains the primary provider.")
                else:
                    status_str, available = "unavailable", False
                    message = ("Ollama service is not reachable. It is configured but "
                               "disabled until a local model is available. Claude "
                               "remains the primary provider.")
            else:
                # Claude/OpenAI/Gemini: ready when registered with a known model list.
                available = len(models) > 0
                status_str = "ready" if available else "configured_no_model"
                if not available:
                    message = "Configured but no models listed."

            result[key] = ProviderInfo(
                name=info["name"],
                available=available,
                supports_streaming=info["supports_streaming"],
                supports_tools=info["supports_tools"],
                models=models,
                status=status_str,
                message=message,
            )

        return result

    except Exception as e:
        logger.error(f"Error listing providers: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list providers: {str(e)}"
        )


@router.get(
    "/list",
    response_model=List[ModelInfo],
    summary="List all available models",
    description="Get a list of all available models across all configured providers"
)
async def list_models(provider: Optional[str] = None) -> List[ModelInfo]:
    """
    List all available models.

    Args:
        provider: Optional provider name to filter by

    Returns:
        List of models with their provider information
    """
    try:
        router_instance = get_router()
        available_models = router_instance.get_available_models(provider)

        result = []
        for provider_name, models in available_models.items():
            for model in models:
                result.append(ModelInfo(
                    name=model,
                    provider=provider_name,
                ))

        return result

    except Exception as e:
        logger.error(f"Error listing models: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list models: {str(e)}"
        )


@router.get(
    "/info",
    response_model=Dict[str, Any],
    summary="Get provider information",
    description="Get detailed information about configured providers including capabilities and statistics"
)
async def get_provider_info() -> Dict[str, Any]:
    """
    Get detailed provider information.

    Returns:
        Dictionary with provider information and statistics
    """
    try:
        router_instance = get_router()
        provider_info = router_instance.get_provider_info()

        # Count total models
        total_models = sum(
            len(info["available_models"])
            for info in provider_info.values()
        )

        return {
            "providers": provider_info,
            "total_providers": len(provider_info),
            "total_models": total_models,
            "available_providers": list(provider_info.keys()),
        }

    except Exception as e:
        logger.error(f"Error getting provider info: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get provider info: {str(e)}"
        )


@router.post(
    "/test",
    response_model=ModelTestResponse,
    summary="Test a model",
    description="Send a test prompt to a model to verify it's working correctly"
)
async def test_model(request: ModelTestRequest) -> ModelTestResponse:
    """
    Test a model with a simple completion request.

    Args:
        request: Test request with model and prompt

    Returns:
        Test response with model output and statistics
    """
    try:
        router_instance = get_router()

        # Create completion request
        completion_request = CompletionRequest(
            model=request.model,
            messages=[
                Message(role="user", content=request.prompt)
            ],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False,
        )

        # Get provider for logging
        provider = router_instance._get_provider_for_model(request.model)

        logger.info(f"Testing model {request.model} with provider {provider.provider_name}")

        # Make completion request
        response = await router_instance.complete(completion_request)

        # Estimate cost
        cost = provider.estimate_cost(completion_request, response)

        return ModelTestResponse(
            success=True,
            model=response.model,
            provider=response.provider or provider.provider_name,
            response=response.content,
            usage=response.usage,
            estimated_cost=cost,
        )

    except Exception as e:
        logger.error(f"Error testing model {request.model}: {e}", exc_info=True)
        return ModelTestResponse(
            success=False,
            model=request.model,
            provider="unknown",
            error=str(e),
        )


@router.get(
    "/check/{provider}",
    response_model=Dict[str, Any],
    summary="Check provider availability",
    description="Check if a specific provider is configured and available"
)
async def check_provider(provider: str) -> Dict[str, Any]:
    """
    Check if a provider is available.

    Args:
        provider: Provider name to check

    Returns:
        Dictionary with availability information
    """
    try:
        router_instance = get_router()
        is_available = router_instance.is_provider_available(provider)

        if not is_available:
            return {
                "provider": provider,
                "available": False,
                "message": f"Provider '{provider}' is not configured or unavailable"
            }

        # Get provider info
        provider_info = router_instance.get_provider_info()
        info = provider_info.get(provider, {})

        return {
            "provider": provider,
            "available": True,
            "supports_streaming": info.get("supports_streaming", False),
            "supports_tools": info.get("supports_tools", False),
            "model_count": len(info.get("available_models", [])),
            "models": info.get("available_models", []),
        }

    except Exception as e:
        logger.error(f"Error checking provider {provider}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check provider: {str(e)}"
        )
