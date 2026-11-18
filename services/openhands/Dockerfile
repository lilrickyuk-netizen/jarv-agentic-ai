# JAI's engineering sandbox: the OpenHands Software Agent SDK (MIT) 1.58.2 with the toolchain JAI's own agents use
# (git, Node 24 with npm, pnpm and yarn, uv with Python 3.12 to 3.14, Task, Terraform, Helm, Syft, Trivy, Gitleaks,
# a C compiler, jq, ripgrep, mise for any other language, and ffmpeg with headless Chromium for video work). The service (app/server.py) runs as root and holds the tokens; the
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
    PIP_DISABLE_PIP_VERSION_CHECK=1 LITELLM_LOCAL_MODEL_COST_MAP=True

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
    && rm -rf /tmp/* \
    && task --version && terraform version && helm version --short && syft version && trivy --version && gitleaks version

# After the toolchain, so adding these never makes Docker download the pinned tools again.
# Video and browser work (BRAG Slim launch videos, rendering a project's real UI): ffmpeg, headless Chromium and
# fonts, so a specialist can draw frames in a browser and render the MP4 itself.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg chromium fonts-liberation fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*
ENV CHROME_PATH=/usr/bin/chromium PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium PUPPETEER_SKIP_DOWNLOAD=1 \
    JAI_SKILLS_DIR=/jai/skills

# The agent's user, and git for it: commits it makes are authored as JAI; the workspace folders belong to the
# Windows user, so git is told they are safe.
RUN useradd --create-home --uid 1000 --shell /bin/bash openhands \
    && git config --system user.name "JAI" && git config --system user.email "jai@jarv.local" \
    && git config --system safe.directory '*' && git config --system init.defaultBranch main

RUN pip install "openhands-sdk==1.58.2" "openhands-tools==1.58.2" "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1" \
        "httpx>=0.28,<1" "pytest>=8,<10"

# Hyperframes, the renderer the BRAG and Hyperframes skills call as `npx hyperframes`: installed once at the version
# that renders in this sandbox, which npx then uses instead of fetching the newest (npx runs an installed package
# when the command names no version). 17 November: 0.9.64 hung at capture start with 0 frames, render after render;
# 0.9.58 rendered each 22-second ad in about 73 seconds. 0.9.65 (17 November) changes nothing in capture. Raise it
# only after a render of the newer version passes here. It comes after the large installs above, so a rebuild for
# a new version downloads only Hyperframes (18 November: putting it earlier re-downloaded OpenHands, and a slow
# connection timed the build out).
ARG HYPERFRAMES_VERSION=0.9.58
RUN npm install -g "hyperframes@${HYPERFRAMES_VERSION}" && npm cache clean --force

# Hyperframes' voice: `hyperframes tts` runs Kokoro through kokoro-onnx (MIT) and soundfile (BSD-3-Clause) in Python.
# Installed once here in their own environment, which Hyperframes uses through HYPERFRAMES_PYTHON (its documented
# override), so a video no longer installs them in every run and they cannot clash with OpenHands' packages. The
# agent's shell is a login shell (su openhands -), which keeps none of the image's environment, so the setting is
# also in /etc/profile.d. The voice models (about 340 MB) download once into the sandbox home, which is kept.
ARG KOKORO_ONNX_VERSION=0.6.1
ARG SOUNDFILE_VERSION=0.14.0
RUN python3 -m venv /opt/kokoro \
    && /opt/kokoro/bin/pip install "kokoro-onnx==${KOKORO_ONNX_VERSION}" "soundfile==${SOUNDFILE_VERSION}" \
    && /opt/kokoro/bin/python -c "import kokoro_onnx, soundfile" \
    && chmod -R a+rX /opt/kokoro \
    && printf 'export HYPERFRAMES_PYTHON=/opt/kokoro/bin/python\n' > /etc/profile.d/jai-voice.sh \
    && chmod 644 /etc/profile.d/jai-voice.sh
ENV HYPERFRAMES_PYTHON=/opt/kokoro/bin/python

# OpenMontage (calesthio/OpenMontage, AGPL-3.0): an agent-run video studio (character animation, animated explainers,
# starting from a reference video), at a pinned commit in /opt/openmontage, owned by the agent's user because the
# studio keeps its working files in its own folder; its projects go into the mission's folder
# (OPENMONTAGE_PROJECTS_DIR). Its Python environment has its own requirements plus what its reference-video analysis
# and character renders import (faster-whisper, PySceneDetect with OpenCV, Playwright with its Chromium). It renders
# through the Hyperframes installed above. Remotion's packages are not installed: its character pipeline renders
# with Hyperframes.
ARG OPENMONTAGE_COMMIT=2e003e65fa99a0f329478a2c1cdcf26bc481933a
RUN git clone --quiet https://github.com/calesthio/OpenMontage.git /opt/openmontage \
    && git -C /opt/openmontage checkout --quiet "${OPENMONTAGE_COMMIT}" \
    && rm -rf /opt/openmontage/.git \
    && python3 -m venv /opt/openmontage/.venv \
    && /opt/openmontage/.venv/bin/pip install -r /opt/openmontage/requirements.txt \
        "faster-whisper>=1.1,<2" "scenedetect[opencv-headless]>=0.6.4,<0.7" "playwright>=1.49,<2" \
    && PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright /opt/openmontage/.venv/bin/python -m playwright install \
        --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chown -R openhands:openhands /opt/openmontage && chmod -R a+rX /opt/ms-playwright \
    && printf 'export OPENMONTAGE_HOME=/opt/openmontage\nexport PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright\n' \
        > /etc/profile.d/jai-studio.sh && chmod 644 /etc/profile.d/jai-studio.sh
ENV OPENMONTAGE_HOME=/opt/openmontage PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

WORKDIR /jai
COPY app ./app
COPY tests ./tests
# jai-check: checks the way an agent should see them (failures only, passing runs cached while nothing changed).
RUN printf '#!/bin/sh\nexec python3 /jai/app/jai_check.py "$@"\n' > /usr/local/bin/jai-check \
    && chmod 755 /usr/local/bin/jai-check && chmod -R a+rX /jai/app
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8010/health || exit 1
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8010", "--no-access-log"]
