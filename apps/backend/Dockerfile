# Multi-stage build for optimized production image
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# PostgreSQL 17 client tools from the PostgreSQL project's apt repository.
# pg_dump must be at least as new as the server it backs up; 17 covers every
# server JARV runs against (the compose image and pgvector 15/16/17).
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
         https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
         > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
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


# Test stage
# Keeps development/test tooling out of the production runtime image while
# providing a reproducible environment for pytest, fakeredis, aiosqlite,
# Ruff, mypy, and the rest of JARV's backend verification suite.
FROM builder AS test

RUN poetry install --no-interaction --no-ansi --with dev

CMD ["python", "-m", "pytest"]


# Production stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies + the toolchain JARV's autonomous agent loop
# needs to build/test real projects from the workspace: git (clone/status/diff),
# and Node.js + npm (JS/TS builds and tests such as MYCO).
RUN apt-get update && apt-get install -y \
    curl \
    git \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# PostgreSQL 17 client tools from the PostgreSQL project's apt repository.
# pg_dump must be at least as new as the server it backs up; 17 covers every
# server JARV runs against (the compose image and pgvector 15/16/17).
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
         https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
         > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r jarv && useradd -r -g jarv jarv
RUN mkdir -p /data/voice-models /data/backups && chown -R jarv:jarv /data/voice-models /data/backups \
    && chmod 700 /data/backups

# Copy installed dependencies and application from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder --chown=jarv:jarv /app /app

# Switch to non-root user
USER jarv

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application with production settings
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--log-level", "info"]
