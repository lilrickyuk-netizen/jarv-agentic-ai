#!/usr/bin/env python3
"""
JARV Local Runner - Start Script

Starts the local runner service.
"""
import sys
import uvicorn
from pathlib import Path

# Add runner to path
sys.path.insert(0, str(Path(__file__).parent))

from runner.config import settings


def start():
    """Start local runner service"""
    print("=" * 60)
    print("JARV Local Runner - Starting")
    print("=" * 60)
    print()
    print(f"Host: {settings.HOST}")
    print(f"Port: {settings.PORT}")
    print(f"Audit Logging: {settings.AUDIT_ENABLED}")
    print(f"Allowed Folders: {len(settings.ALLOWED_FOLDERS)}")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print()

    # Start server
    uvicorn.run(
        "runner.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    start()
