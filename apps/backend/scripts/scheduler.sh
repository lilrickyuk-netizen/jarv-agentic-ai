#!/bin/bash
# JARV Backend - Celery Beat Scheduler Startup Script

# Start Celery beat scheduler for periodic tasks
celery -A app.workers.celery_app beat \
    --loglevel=info \
    --pidfile=/tmp/celerybeat.pid \
    --schedule=/tmp/celerybeat-schedule
