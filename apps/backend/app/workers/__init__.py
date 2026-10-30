"""
JARV Backend Workers

Background task workers for async operations. Importing this package marks the
process as a worker before the database engine is created, so the engine opens
a connection per use (see app.core.database).
"""
import os

os.environ.setdefault("JARV_PROCESS_ROLE", "worker")

from app.core.celery import celery_app  # noqa: E402

__all__ = ["celery_app"]
