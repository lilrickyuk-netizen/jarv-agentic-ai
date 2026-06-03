#!/bin/bash
# JARV Backend - Celery Worker Startup Script

# Start Celery worker with appropriate configuration
celery -A app.workers.celery_app worker \
    --loglevel=info \
    --concurrency=4 \
    --max-tasks-per-child=1000 \
    --time-limit=300 \
    --soft-time-limit=240
