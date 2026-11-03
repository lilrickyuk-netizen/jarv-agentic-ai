# JAI's voice service (Pipecat). Its own image and its own pinned packages, so its newer FastAPI and websockets
# never touch JAI's backend. It holds no secrets: the OpenAI key is read at run time from the backend's .env,
# mounted read-only, and every tool runs on the backend as the signed-in operator.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 jai

WORKDIR /srv/voice
COPY requirements.txt .
RUN pip install -r requirements.txt
# Kokoro (open source, Apache 2.0): JAI's British voice, run on this computer. Its model and voices come from the
# kokoro-onnx release and are checked against the checksums pinned here before they are kept.
ARG KOKORO_RELEASE=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
RUN mkdir -p /srv/voice/models \
    && curl -fsSL -o /srv/voice/models/kokoro-v1.0.onnx "$KOKORO_RELEASE/kokoro-v1.0.onnx" \
    && curl -fsSL -o /srv/voice/models/voices-v1.0.bin "$KOKORO_RELEASE/voices-v1.0.bin" \
    && echo "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5  /srv/voice/models/kokoro-v1.0.onnx" | sha256sum -c - \
    && echo "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d  /srv/voice/models/voices-v1.0.bin" | sha256sum -c -
ENV KOKORO_MODEL=/srv/voice/models/kokoro-v1.0.onnx KOKORO_VOICES=/srv/voice/models/voices-v1.0.bin
COPY app ./app
COPY tests ./tests
COPY pytest.ini .

USER jai
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8765/health || exit 1
# No access log: the WebSocket address carries the sign-in token.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", "--ws-ping-interval", "20", "--no-access-log"]
