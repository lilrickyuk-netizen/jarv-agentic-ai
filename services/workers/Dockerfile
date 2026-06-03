# Multi-stage build for optimized production image
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry==1.7.1

# Copy Poetry files
COPY pyproject.toml poetry.lock* ./

# Install dependencies without dev packages
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root --only main

# Copy application code
COPY . .

# Install the application
RUN poetry install --no-interaction --no-ansi --only main


# Production stage
FROM python:3.11-slim

WORKDIR /app

# Install only runtime dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd -r jarv && useradd -r -g jarv jarv

# Copy installed dependencies and application from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder --chown=jarv:jarv /app /app

# Switch to non-root user
USER jarv

# Health check for Celery worker
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD celery -A workers.celery_app inspect ping -d celery@$$HOSTNAME || exit 1

# Default command (can be overridden in docker-compose)
CMD ["celery", "-A", "workers.celery_app", "worker", "--loglevel=info", "--concurrency=4"]
