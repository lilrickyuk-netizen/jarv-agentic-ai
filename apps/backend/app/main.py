"""
JARV Backend - FastAPI Application
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager
import logging
import time

from app import __version__
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.database import close_db
from app.core.redis import init_redis, close_redis
from app.core.errors import (
    JARVException,
    jarv_exception_handler,
    http_exception_handler,
    validation_exception_handler,
    general_exception_handler,
)
from app.api import health, auth, models, agents, tasks, tools, evolution, swarm, workspaces, company, standups, operations_feed, memory, experience, approvals, boundary_reports, checkpoints, assets

# Setup logging first
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info(f"Starting JARV Backend v{__version__}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"Log level: {settings.LOG_LEVEL}")
    logger.info(f"Database: {settings.DATABASE_URL}")

    # Initialize Redis
    await init_redis()
    logger.info(f"Redis: {settings.REDIS_URL}")

    # Log feature status
    logger.info(f"Swarm enabled: {settings.SWARM_ENABLED}")
    logger.info(f"Self-evolution enabled: {settings.SELF_EVOLUTION_ENABLED}")
    logger.info(f"Company operator enabled: {settings.COMPANY_OPERATOR_ENABLED}")
    logger.info(f"Self-healing enabled: {settings.SELF_HEALING_ENABLED}")

    yield

    # Shutdown
    logger.info("Shutting down JARV Backend")
    await close_db()
    await close_redis()


# Create FastAPI application
app = FastAPI(
    title="JARV Agentic AI System",
    description="Backend API for JARV - A private autonomous multi-agent AI execution system",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# CORS Middleware
if settings.CORS_ENABLED:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    logger.info(f"CORS enabled for origins: {settings.ALLOWED_ORIGINS}")


# Request ID Middleware
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Add unique request ID to each request"""
    import uuid

    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    # Add to response headers
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id

    return response


# Logging Middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests"""
    start_time = time.time()

    # Log request
    logger.info(
        f"Request started",
        extra={
            "method": request.method,
            "path": request.url.path,
            "client": request.client.host if request.client else None,
            "request_id": getattr(request.state, "request_id", None),
        }
    )

    # Process request
    response = await call_next(request)

    # Calculate duration
    duration = time.time() - start_time

    # Log response
    logger.info(
        f"Request completed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration": f"{duration:.3f}s",
            "request_id": getattr(request.state, "request_id", None),
        }
    )

    return response


# Exception Handlers
app.add_exception_handler(JARVException, jarv_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)


# Include routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(models.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(tools.router, prefix="/api")
app.include_router(evolution.router)
app.include_router(swarm.router)
app.include_router(workspaces.router, prefix="/api")
app.include_router(company.router)
app.include_router(standups.router)
app.include_router(operations_feed.router)
app.include_router(memory.router)
app.include_router(experience.router)
app.include_router(approvals.router)
app.include_router(boundary_reports.router)
app.include_router(checkpoints.router)
app.include_router(assets.router)

# Import and include workflow router
from app.api.v1 import workflows
app.include_router(workflows.router, prefix="/api")

# Import and include assets router
from app.api.v1 import assets
app.include_router(assets.router, prefix="/api")

# Import and include support router
from app.api.v1 import support
app.include_router(support.router, prefix="/api")

# Import and include business operations router
from app.api.v1 import business_ops
app.include_router(business_ops.router, prefix="/api")

# Import and include content and community router
from app.api.v1 import content_community
app.include_router(content_community.router, prefix="/api")

# Import and include voice command router
from app.api.v1 import voice
app.include_router(voice.router, prefix="/api")

# Import and include command execution router (live dashboard command pipeline)
from app.api import command
app.include_router(command.router, prefix="/api")

# Import and include audit log router (persistent audit trail)
from app.api import audit
app.include_router(audit.router, prefix="/api")


# Root endpoint (included in health router but also accessible at root)
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "JARV Agentic AI System - Backend API",
        "version": __version__,
        "environment": settings.ENVIRONMENT,
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=settings.HOT_RELOAD,
        log_level=settings.LOG_LEVEL.lower(),
    )
