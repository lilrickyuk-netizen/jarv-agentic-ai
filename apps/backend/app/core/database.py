"""
JARV Backend Database Configuration
SQLAlchemy setup with async support
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
import logging
import os

from app.core.config import settings

logger = logging.getLogger(__name__)


# Create async engine
# Convert postgresql:// to postgresql+asyncpg://
database_url = str(settings.DATABASE_URL).replace(
    "postgresql://", "postgresql+asyncpg://"
)

# Celery workers run each job in a fresh event loop (asyncio.run). Pooled asyncpg
# connections are bound to the loop that opened them, so a pool would fail on a
# worker's second job. Worker processes therefore open a connection per use.
IS_WORKER_PROCESS = os.getenv("JARV_PROCESS_ROLE", "").lower() == "worker"

if IS_WORKER_PROCESS:
    engine = create_async_engine(database_url, echo=settings.DEBUG, poolclass=NullPool)
else:
    engine = create_async_engine(
        database_url,
        echo=settings.DEBUG,
        pool_pre_ping=True,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=10,
        pool_recycle=3600,
    )

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting async database sessions.

    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database - create all tables.

    Note: In production, use Alembic migrations instead.
    This is for development/testing only.
    """
    # Import Base and all models
    from app.models.base import Base
    import app.models  # noqa: F401 - Import to register all models

    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")


async def close_db() -> None:
    """Close database connection"""
    await engine.dispose()
    logger.info("Database connection closed")


# Import Base for re-export
from app.models.base import Base

# Export for convenience
__all__ = [
    "Base",
    "engine",
    "AsyncSessionLocal",
    "get_db",
    "init_db",
    "close_db",
]
