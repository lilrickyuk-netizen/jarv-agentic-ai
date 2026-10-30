ARG VOICEBOX_REF=8af7efe62fab8d33e2a5dfbedabaa45f68a5184f

FROM alpine/git:2.47.2 AS source
ARG VOICEBOX_REF
RUN git init /src \
    && git -C /src remote add origin https://github.com/jamiepine/voicebox.git \
    && git -C /src fetch --depth 1 origin "$VOICEBOX_REF" \
    && git -C /src checkout --detach FETCH_HEAD

FROM oven/bun:1 AS frontend
WORKDIR /build
COPY --from=source /src/package.json /src/bun.lock /src/CHANGELOG.md ./
COPY --from=source /src/app/ ./app/
COPY --from=source /src/web/ ./web/
RUN sed -i 's/\r$//' package.json \
    && sed -i '/"tauri"/d' package.json \
    && sed -i -z 's/,\n  ]/\n  ]/' package.json
RUN bun install --no-save
RUN cd web && bunx --bun vite build

FROM python:3.12-slim AS backend-builder
ARG VOICEBOX_REF
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --upgrade pip
COPY --from=source /src/backend/requirements.txt ./requirements.txt
RUN printf 'torch==2.6.0+cu124\ntorchaudio==2.6.0+cu124\n' > /tmp/cuda-constraints.txt
ENV PIP_CONSTRAINT=/tmp/cuda-constraints.txt
ENV PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu124
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
RUN pip install --no-cache-dir --prefix=/install --no-deps chatterbox-tts
RUN pip install --no-cache-dir --prefix=/install --no-deps hume-tada
RUN pip install --no-cache-dir --prefix=/install --no-deps omnivoice
RUN pip install --no-cache-dir --prefix=/install git+https://github.com/QwenLM/Qwen3-TTS.git
COPY --from=source /src/backend/ /build/backend/

FROM python:3.12-slim AS runtime
RUN groupadd -r voicebox && useradd -r -g voicebox -m -s /bin/bash voicebox
RUN mkdir -p /home/voicebox/.cache/huggingface /app/data/generations \
    && chown -R voicebox:voicebox /home/voicebox/.cache/huggingface /app/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg sox gcc g++ curl gosu \
    && rm -rf /var/lib/apt/lists/*
COPY --from=backend-builder /install /usr/local
COPY --from=source --chown=voicebox:voicebox /src/backend/ /app/backend/
COPY --from=source --chown=voicebox:voicebox /src/LICENSE /app/LICENSE
COPY --from=frontend --chown=voicebox:voicebox /build/web/dist /app/frontend/
RUN mkdir -p /app/data/generations /app/data/profiles /app/data/cache \
    && chown -R voicebox:voicebox /app/data
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
EXPOSE 17493
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=90s \
    CMD curl -f http://localhost:17493/health || exit 1
COPY --from=source --chmod=755 /src/scripts/rocm-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "17493"]
