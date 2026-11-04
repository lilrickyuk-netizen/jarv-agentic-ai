# JAI's engineering sandbox: the OpenHands Software Agent SDK (MIT) 1.58.2 with the toolchain JAI's own agents use
# (git, Node 24 with npm, pnpm and yarn, uv with Python 3.12 to 3.14, Task, Terraform, Helm, a C compiler, jq,
# ripgrep, and mise for any other language). The service (app/server.py) runs as root and holds the tokens; the
# agent's shell runs as the unprivileged user "openhands" (uid 1000, the owner of the workspace folders), so it
# cannot read them. No Docker socket, no database and no other service's secrets are in this container.
ARG NODE_IMAGE=node:24.21.0-bookworm-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.17
ARG MISE_IMAGE=ghcr.io/jdx/mise:2026.10.4
FROM ${NODE_IMAGE} AS node
FROM ${UV_IMAGE} AS uv
FROM ${MISE_IMAGE} AS mise

FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git openssh-client build-essential jq unzip ripgrep tmux procps less \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -s ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
    && corepack enable --install-directory /usr/local/bin pnpm yarn \
    && npm cache clean --force
COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=mise /usr/local/bin/mise /usr/local/bin/mise
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python UV_LINK_MODE=copy npm_config_package_import_method=copy \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0 MISE_YES=1
RUN uv python install 3.12 3.13 3.14 && chmod -R a+rX /opt/uv-python

ARG TASK_VERSION=3.52.0
ARG TERRAFORM_VERSION=1.16.3
ARG HELM_VERSION=4.3.0
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

# The agent's user, and git for it: commits it makes are authored as JAI; the workspace folders belong to the
# Windows user, so git is told they are safe.
RUN useradd --create-home --uid 1000 --shell /bin/bash openhands \
    && git config --system user.name "JAI" && git config --system user.email "jai@jarv.local" \
    && git config --system safe.directory '*' && git config --system init.defaultBranch main

RUN pip install "openhands-sdk==1.58.2" "openhands-tools==1.58.2" "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1" \
        "httpx>=0.28,<1" "pytest>=8,<10"

WORKDIR /jai
COPY app ./app
COPY tests ./tests
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8010/health || exit 1
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8010", "--no-access-log"]
