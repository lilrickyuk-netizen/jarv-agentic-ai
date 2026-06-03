"""
JARV Backend Health and Version Endpoints
"""
from typing import Dict, Any
from fastapi import APIRouter, status
from datetime import datetime
import platform
import sys

from app import __version__
from app.core.config import settings
from app.core.redis import check_redis_health
from app.core.database import engine
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    response_model=Dict[str, Any],
    summary="Health Check",
    description="Check if the API is healthy and operational"
)
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for monitoring and load balancers.

    Returns:
        Health status information
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "jarv-backend",
        "version": __version__,
    }


@router.get(
    "/version",
    status_code=status.HTTP_200_OK,
    response_model=Dict[str, Any],
    summary="Version Information",
    description="Get detailed version and system information"
)
async def version_info() -> Dict[str, Any]:
    """
    Version information endpoint.

    Returns:
        Detailed version and system information
    """
    return {
        "service": "jarv-backend",
        "version": __version__,
        "environment": settings.ENVIRONMENT,
        "python_version": sys.version,
        "platform": platform.platform(),
        "timestamp": datetime.utcnow().isoformat(),
        "features": {
            "swarm_enabled": settings.SWARM_ENABLED,
            "self_evolution_enabled": settings.SELF_EVOLUTION_ENABLED,
            "company_operator_enabled": settings.COMPANY_OPERATOR_ENABLED,
            "self_healing_enabled": settings.SELF_HEALING_ENABLED,
            "voice_enabled": settings.VOICE_ENABLED,
        },
        "configuration": {
            "log_level": settings.LOG_LEVEL,
            "default_authority_level": settings.DEFAULT_AUTHORITY_LEVEL,
            "max_subagents_per_workspace": settings.MAX_SUBAGENTS_PER_WORKSPACE,
            "max_subagents_global": settings.MAX_SUBAGENTS_GLOBAL,
        },
    }


@router.get(
    "/ready",
    status_code=status.HTTP_200_OK,
    response_model=Dict[str, Any],
    summary="Readiness Check",
    description="Check if the API is ready to handle requests"
)
async def readiness_check() -> Dict[str, Any]:
    """
    Readiness check endpoint for Kubernetes and orchestration systems.

    Returns:
        Readiness status - checks dependencies like database, redis, etc.
    """
    checks = {}
    overall_status = "ready"

    # Check database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = {"status": "healthy"}
    except Exception as e:
        checks["database"] = {"status": "unhealthy", "error": str(e)}
        overall_status = "not_ready"

    # Check Redis
    redis_health = await check_redis_health()
    checks["redis"] = redis_health
    if redis_health["status"] != "healthy":
        overall_status = "not_ready"

    return {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "checks": checks,
    }


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    response_model=Dict[str, str],
    summary="Root Endpoint",
    description="API root with basic information"
)
async def root() -> Dict[str, str]:
    """
    Root endpoint.

    Returns:
        Basic API information
    """
    return {
        "service": "JARV Agentic AI System - Backend API",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }
