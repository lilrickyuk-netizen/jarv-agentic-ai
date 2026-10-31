# Toolchain images copied into the runtime stage (declared before the first FROM so they can be
# used there): Node 24 LTS and uv 0.12, per MYCO V3.2 §40.
ARG NODE_IMAGE=node:24.21.0-bookworm-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.17

# Multi-stage build for optimized production image
FROM python:3.11-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    git \
    openssh-client \
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


# Toolchains JARV's agents use to build projects in a workspace (copied into the runtime image).
# Versions follow the most demanding project JARV builds (MYCO V3.2 §40): Node 24 LTS, uv 0.12,
# Task 3.52, Terraform 1.16, Helm 4.3. Change them here, in one place.
FROM ${NODE_IMAGE} AS node
FROM ${UV_IMAGE} AS uv

# Production stage
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install runtime dependencies + the toolchain JARV's autonomous agent loop
# needs to build/test real projects from the workspace: git (init/status/diff/commit),
# Node.js 24 LTS with npm and Corepack (each project's pnpm or yarn version, from its
# packageManager field), uv with Python 3.12 to 3.14 (Python projects; uv fetches any exact
# version a project pins), Task (Taskfile.yml), Terraform and Helm (infrastructure modules),
# a C/C++ compiler and make (native packages), jq, unzip and ripgrep.
# Anything else a project needs, JARV installs itself from the official registries into its
# tool home (/home/jarv, a persistent volume): uv tool install, uv python install, pnpm, npm.
ARG TASK_VERSION=3.52.0
ARG TERRAFORM_VERSION=1.16.3
ARG HELM_VERSION=4.3.0
RUN apt-get update && apt-get install -y \
    curl \
    git \
    openssh-client \
    build-essential \
    jq \
    unzip \
    ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -s ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
    && corepack enable --install-directory /usr/local/bin pnpm yarn \
    && npm cache clean --force
# Task, Terraform and Helm from their official release downloads, checked against the published
# checksums before installing.
RUN set -eu; cd /tmp \
    && curl -fsSLO "https://github.com/go-task/task/releases/download/v${TASK_VERSION}/task_linux_amd64.tar.gz" \
    && curl -fsSLO "https://github.com/go-task/task/releases/download/v${TASK_VERSION}/task_checksums.txt" \
    && grep " task_linux_amd64.tar.gz$" task_checksums.txt | sha256sum -c - \
    && tar -xzf task_linux_amd64.tar.gz -C /usr/local/bin task \
    && curl -fsSLO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && curl -fsSLO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS" \
    && grep " terraform_${TERRAFORM_VERSION}_linux_amd64.zip$" "terraform_${TERRAFORM_VERSION}_SHA256SUMS" | sha256sum -c - \
    && unzip -o -q "terraform_${TERRAFORM_VERSION}_linux_amd64.zip" terraform -d /usr/local/bin \
    && curl -fsSLO "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz" \
    && curl -fsSLO "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz.sha256sum" \
    && sha256sum -c "helm-v${HELM_VERSION}-linux-amd64.tar.gz.sha256sum" \
    && tar -xzf "helm-v${HELM_VERSION}-linux-amd64.tar.gz" --strip-components=1 -C /usr/local/bin linux-amd64/helm \
    && rm -rf /tmp/*
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_LINK_MODE=copy \
    npm_config_package_import_method=copy \
    COREPACK_HOME=/home/jarv/.cache/corepack \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN uv python install 3.12 3.13 3.14 && chmod -R a+rX /opt/uv-python

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

# Create non-root user for security. Its uid/gid match the owner of the mounted workspace
# folders (the WSL user, 1000, by default), so git, pnpm and uv can set file modes there.
ARG JARV_UID=1000
ARG JARV_GID=1000
RUN groupadd -r -g "${JARV_GID}" jarv && useradd -r -m -d /home/jarv -u "${JARV_UID}" -g jarv jarv
# Package caches and git need a home; commits JARV makes in a workspace are authored as JARV.
# Workspace folders are mounted from the host with another owner, so git is told they are
# safe; JARV's own scope checks decide which folders a command may run in.
ENV HOME=/home/jarv \
    PATH=/home/jarv/.local/bin:$PATH \
    GIT_AUTHOR_NAME=JARV GIT_AUTHOR_EMAIL=jarv@localhost \
    GIT_COMMITTER_NAME=JARV GIT_COMMITTER_EMAIL=jarv@localhost \
    GIT_CONFIG_COUNT=2 \
    GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0=* \
    GIT_CONFIG_KEY_1=init.defaultBranch GIT_CONFIG_VALUE_1=main
RUN mkdir -p /data/voice-models /data/backups && chown -R jarv:jarv /data/voice-models /data/backups /opt/uv-python \
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
