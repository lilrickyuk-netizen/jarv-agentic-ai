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
from app.core.database import AsyncSessionLocal, close_db
from app.core.redis import init_redis, close_redis
from app.core.errors import (
    JARVException,
    jarv_exception_handler,
    http_exception_handler,
    validation_exception_handler,
    general_exception_handler,
)
from app.api import health, auth, models, agents, tasks, tools, evolution, swarm, workspaces, company, company_ops, business, standups, operations_feed, memory, experience, approvals, boundary_reports, checkpoints, assets, agent_knowledge

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
    logger.info("Database connection configured")

    if not settings.TESTING:
        from app.core.knowledge.catalog import specialist_knowledge
        from app.core.knowledge.service import knowledge_service

        async with AsyncSessionLocal() as session:
            await knowledge_service.ingest(session, specialist_knowledge())
            await session.commit()

    # Initialize Redis
    await init_redis()
    logger.info("Redis connection configured")

    # Recover missions interrupted by a restart (workers also run this every minute).
    if not settings.TESTING:
        try:
            from app.core.runtime.missions import MissionRunner

            recovered = await MissionRunner().recover_stale()
            logger.info(f"Mission recovery at startup: {recovered}")
        except Exception as exc:  # noqa: BLE001 - startup must not fail on recovery
            logger.error(f"Mission recovery at startup failed: {exc}", exc_info=True)

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


# Request tracing, metrics, and logging (Repair 12b)
@app.middleware("http")
async def trace_and_measure(request: Request, call_next):
    """One middleware so every log line for a request carries its request id.

    Accepts a well-formed incoming X-Request-ID (so the dashboard and nginx can
    correlate), records Prometheus metrics by route template, and logs the
    request with method, route, status, and duration.
    """
    import uuid

    from app.core.observability.context import accept_request_id, request_id_var
    from app.core.observability.metrics import http_metrics

    request_id = accept_request_id(request.headers.get("x-request-id")) or str(uuid.uuid4())
    request.state.request_id = request_id
    token = request_id_var.set(request_id)
    start_time = time.perf_counter()
    status_code = 500
    http_metrics.started()
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration = time.perf_counter() - start_time
        route = request.scope.get("route")
        template = getattr(route, "path", None)
        if template is None:
            from starlette.routing import Match

            for candidate in request.app.router.routes:
                if candidate.matches(request.scope)[0] == Match.FULL:
                    template = getattr(candidate, "path", None)
                    break
        template = template or "unmatched"
        if template != "/metrics":
            http_metrics.observe(request.method, template, status_code, duration)
        logger.info(
            f"{request.method} {template} -> {status_code} in {duration * 1000:.0f}ms",
            extra={"method": request.method, "path": request.url.path, "route": template,
                   "status_code": status_code, "duration_ms": round(duration * 1000, 1),
                   "client": request.client.host if request.client else None},
        )
        request_id_var.reset(token)


# Exception Handlers
app.add_exception_handler(JARVException, jarv_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)


# Include routers
app.include_router(health.router)
from app.api import metrics as metrics_api  # noqa: E402
app.include_router(metrics_api.router)
from app.api import observability as observability_api  # noqa: E402
app.include_router(observability_api.router)
from app.api import operations as operations_api  # noqa: E402
app.include_router(operations_api.router)
app.include_router(auth.router)
app.include_router(models.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(tools.router, prefix="/api")
app.include_router(evolution.router)
app.include_router(swarm.router)
app.include_router(workspaces.router, prefix="/api")
app.include_router(company.router)
app.include_router(company_ops.router)
app.include_router(business.router)
app.include_router(standups.router)
app.include_router(operations_feed.router)
app.include_router(memory.router)
app.include_router(experience.router)
app.include_router(approvals.router)
app.include_router(boundary_reports.router)
app.include_router(checkpoints.router)
# Richard Boundary Operator: authenticated hard-boundary decision + resume loop (Repair 8)
from app.api import richard as richard_api
app.include_router(richard_api.router)
app.include_router(assets.router)
app.include_router(agent_knowledge.router, prefix="/api")

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

from app.api.v1 import voicebox
app.include_router(voicebox.router, prefix="/api")

# Import and include command execution router (live dashboard command pipeline)
from app.api import command
app.include_router(command.router, prefix="/api")

# Import and include audit log router (persistent audit trail)
from app.api import audit
app.include_router(audit.router, prefix="/api")

# Autonomous scheduler + external integrations
from app.api import scheduler as scheduler_api
app.include_router(scheduler_api.router, prefix="/api")
from app.api import integrations as integrations_api
app.include_router(integrations_api.router, prefix="/api")
from app.api import internet as internet_api
app.include_router(internet_api.router, prefix="/api")
app.include_router(internet_api.research_router, prefix="/api")
app.include_router(internet_api.assets_lic_router, prefix="/api")


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
