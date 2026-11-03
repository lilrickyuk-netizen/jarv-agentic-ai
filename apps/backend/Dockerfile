# Toolchain images copied into the runtime stage (declared before the first FROM so they can be
# used there): Node 24 LTS and uv 0.12, per MYCO V3.2 §40.
ARG NODE_IMAGE=node:24.21.0-bookworm-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.17
# mise, the tool-version manager that lets JAI install any language at the version a project pins.
ARG MISE_IMAGE=ghcr.io/jdx/mise:2026.10.4

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
# server JAI runs against (the compose image and pgvector 15/16/17).
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
# Ruff, mypy, and the rest of JAI's backend verification suite.
FROM builder AS test

RUN poetry install --no-interaction --no-ansi --with dev

CMD ["python", "-m", "pytest"]


# Toolchains JAI's agents use to build projects in a workspace (copied into the runtime image).
# Versions follow the most demanding project JAI builds (MYCO V3.2 §40): Node 24 LTS, uv 0.12,
# Task 3.52, Terraform 1.16, Helm 4.3, Syft 1.55 (SBOMs), Trivy 0.76 (licences, vulnerabilities), Gitleaks 8.30
# (secrets). Their versions are set on the download step below, in one place.
FROM ${NODE_IMAGE} AS node
FROM ${UV_IMAGE} AS uv
FROM ${MISE_IMAGE} AS mise

# Production stage
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install runtime dependencies + the toolchain JAI's autonomous agent loop
# needs to build/test real projects from the workspace: git (init/status/diff/commit),
# Node.js 24 LTS with npm and Corepack (each project's pnpm or yarn version, from its
# packageManager field), uv with Python 3.12 to 3.14 (Python projects; uv fetches any exact
# version a project pins), Task (Taskfile.yml), Terraform and Helm (infrastructure modules),
# Syft (software bills of materials), a C/C++ compiler and make (native packages), jq, unzip and ripgrep.
# Anything else a project needs, JAI installs itself from the official registries into its
# tool home (/home/jarv, a persistent volume): uv tool install, uv python install, pnpm, npm.
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
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_LINK_MODE=copy \
    npm_config_package_import_method=copy \
    COREPACK_HOME=/home/jarv/.cache/corepack \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN uv python install 3.12 3.13 3.14 && chmod -R a+rX /opt/uv-python

# PostgreSQL 17 client tools from the PostgreSQL project's apt repository.
# pg_dump must be at least as new as the server it backs up; 17 covers every
# server JAI runs against (the compose image and pgvector 15/16/17).
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
         https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
         > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*

# Task, Terraform, Helm, Syft, Trivy and Gitleaks from their official release downloads, checked against the
# published checksums before installing. The versions are declared here, next to the step that uses them, so a
# version change rebuilds only this step and not the system packages, Node and Python before it.
# Trivy and Gitleaks: the Linux 64-bit archive is the one their checksum list names, so the file checked is the
# file installed.
ARG TASK_VERSION=3.52.0
ARG TERRAFORM_VERSION=1.16.3
ARG HELM_VERSION=4.3.0
ARG SYFT_VERSION=1.55.0
ARG TRIVY_VERSION=0.76.1
ARG GITLEAKS_VERSION=8.30.1
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
    && curl -fsSLO "https://github.com/anchore/syft/releases/download/v${SYFT_VERSION}/syft_${SYFT_VERSION}_linux_amd64.tar.gz" \
    && curl -fsSLO "https://github.com/anchore/syft/releases/download/v${SYFT_VERSION}/syft_${SYFT_VERSION}_checksums.txt" \
    && grep " syft_${SYFT_VERSION}_linux_amd64.tar.gz$" "syft_${SYFT_VERSION}_checksums.txt" | sha256sum -c - \
    && tar -xzf "syft_${SYFT_VERSION}_linux_amd64.tar.gz" -C /usr/local/bin syft \
    && curl -fsSLO "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_checksums.txt" \
    && TRIVY_TGZ="$(grep -Eio "trivy_${TRIVY_VERSION}_linux[-_](64bit|amd64)\.tar\.gz" "trivy_${TRIVY_VERSION}_checksums.txt" | head -1)" \
    && test -n "$TRIVY_TGZ" \
    && curl -fsSLO "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/${TRIVY_TGZ}" \
    && grep " ${TRIVY_TGZ}$" "trivy_${TRIVY_VERSION}_checksums.txt" | sha256sum -c - \
    && tar -xzf "${TRIVY_TGZ}" -C /usr/local/bin trivy \
    && curl -fsSLO "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_checksums.txt" \
    && GITLEAKS_TGZ="$(grep -Eio "gitleaks_${GITLEAKS_VERSION}_linux_(x64|amd64)\.tar\.gz" "gitleaks_${GITLEAKS_VERSION}_checksums.txt" | head -1)" \
    && test -n "$GITLEAKS_TGZ" \
    && curl -fsSLO "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${GITLEAKS_TGZ}" \
    && grep " ${GITLEAKS_TGZ}$" "gitleaks_${GITLEAKS_VERSION}_checksums.txt" | sha256sum -c - \
    && tar -xzf "${GITLEAKS_TGZ}" -C /usr/local/bin gitleaks \
    && rm -rf /tmp/*

# Any language, at the version a project pins: mise (one binary from its official image). Go 1.26, Java 25
# (Temurin LTS), Maven and Gradle are installed for every user at build time into /usr/local/share/mise, with
# their commands linked into /usr/local/bin; anything else (Rust, .NET, Ruby, PHP, Deno, Bun, other versions) a
# mission installs itself with "mise install" into JAI's tool home, where it persists, then runs it with
# "mise exec -- <command>". The versions are set here, in one place.
COPY --from=mise /usr/local/bin/mise /usr/local/bin/mise
ARG GO_VERSION=1.26
ARG JAVA_VERSION=temurin-25
ARG MAVEN_VERSION=3
ARG GRADLE_VERSION=9
RUN set -eu; export MISE_DATA_DIR=/usr/local/share/mise MISE_CACHE_DIR=/tmp/mise-cache MISE_YES=1; \
    mise install "go@${GO_VERSION}" "java@${JAVA_VERSION}" "maven@${MAVEN_VERSION}" "gradle@${GRADLE_VERSION}"; \
    ln -sfn "$(mise where "go@${GO_VERSION}")" /opt/go; \
    ln -sfn "$(mise where "java@${JAVA_VERSION}")" /opt/java; \
    for b in go gofmt; do ln -sf "/opt/go/bin/$b" "/usr/local/bin/$b"; done; \
    for b in java javac jar jshell keytool; do ln -sf "/opt/java/bin/$b" "/usr/local/bin/$b"; done; \
    ln -sf "$(mise where "maven@${MAVEN_VERSION}")/bin/mvn" /usr/local/bin/mvn; \
    ln -sf "$(mise where "gradle@${GRADLE_VERSION}")/bin/gradle" /usr/local/bin/gradle; \
    chmod -R a+rX /usr/local/share/mise; rm -rf /tmp/mise-cache; \
    go version; java -version; mvn -v; gradle --version
ENV JAVA_HOME=/opt/java \
    GOROOT=/opt/go \
    GOPATH=/home/jarv/go \
    CARGO_HOME=/home/jarv/.cargo \
    RUSTUP_HOME=/home/jarv/.rustup \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    MISE_YES=1

# Create non-root user for security. Its uid/gid match the owner of the mounted workspace
# folders (the WSL user, 1000, by default), so git, pnpm and uv can set file modes there.
ARG JARV_UID=1000
ARG JARV_GID=1000
RUN groupadd -r -g "${JARV_GID}" jarv && useradd -r -m -d /home/jarv -u "${JARV_UID}" -g jarv jarv
# Package caches and git need a home; commits JAI makes in a workspace are authored as JAI.
# Workspace folders are mounted from the host with another owner, so git is told they are
# safe; JAI's own scope checks decide which folders a command may run in.
ENV HOME=/home/jarv \
    PATH=/home/jarv/.local/bin:$PATH:/home/jarv/go/bin:/home/jarv/.cargo/bin:/home/jarv/.dotnet/tools:/home/jarv/.local/share/mise/shims \
    GIT_AUTHOR_NAME=JAI GIT_AUTHOR_EMAIL=jarv@localhost \
    GIT_COMMITTER_NAME=JAI GIT_COMMITTER_EMAIL=jarv@localhost \
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
