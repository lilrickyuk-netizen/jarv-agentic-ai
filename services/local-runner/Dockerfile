# Multi-stage build for optimized production image
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    git \
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
    curl \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security (with a home dir — the runner writes its
# auth token under ~/.jarv, which fails if /home/jarv does not exist)
RUN groupadd -r jarv && useradd -r -g jarv -m -d /home/jarv jarv

# Copy installed dependencies and application from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder --chown=jarv:jarv /app /app

# Switch to non-root user
USER jarv

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run the local runner service
CMD ["uvicorn", "runner.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
