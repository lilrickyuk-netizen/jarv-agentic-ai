# JAI's natural voice: Chatterbox Turbo (Resemble AI, open source, MIT) on the NVIDIA GPU, speaking in the voice of
# a short reference clip (JAI's British George, made with Kokoro, Apache-2.0). PyTorch 2.6 with CUDA 12.4 runs on
# the driver already installed. The model is downloaded while building, so the running service needs no internet.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf

RUN apt-get update && apt-get install -y --no-install-recommends git curl libsndfile1 ffmpeg build-essential \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 1000 jaivoice

ARG CHATTERBOX_REF=5de7a54aa4e5e2baadb0182dde554908b48b85c2
RUN pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124 \
    && pip install "chatterbox-tts @ git+https://github.com/resemble-ai/chatterbox.git@${CHATTERBOX_REF}" \
    && pip install "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1" "pytest>=8,<10" "httpx>=0.27,<1"
RUN python -c "from huggingface_hub import snapshot_download; \
[snapshot_download(repo_id=r, allow_patterns=['*.safetensors', '*.json', '*.txt', '*.pt', '*.model']) \
 for r in ('ResembleAI/chatterbox-turbo', 'ResembleAI/chatterbox-nano')]" \
    && chown -R jaivoice:jaivoice /opt/hf

WORKDIR /srv/chatterbox
COPY server.py ./
COPY tests ./tests
RUN mkdir -p /srv/voices && chown jaivoice:jaivoice /srv/voices
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

USER jaivoice
EXPOSE 8770
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8770/health || exit 1
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8770", "--no-access-log"]
