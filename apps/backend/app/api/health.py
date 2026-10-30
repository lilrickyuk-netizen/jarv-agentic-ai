"""
JARV Backend Health and Version Endpoints
"""
from typing import Dict, Any
from fastapi import APIRouter, status
from datetime import datetime

from app import __version__
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
    description="The service name and version"
)
async def version_info() -> Dict[str, Any]:
    """
    Public version endpoint: the service and its version only. Environment, platform,
    feature switches and limits are on the signed-in Settings page (/api/settings/overview).
    """
    return {
        "service": "jarv-backend",
        "version": __version__,
        "timestamp": datetime.utcnow().isoformat(),
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
        checks["database"] = {"status": "unhealthy", "error": type(e).__name__}
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
