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
COPY app ./app
COPY tests ./tests
COPY pytest.ini .

USER jai
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8765/health || exit 1
# No access log: the WebSocket address carries the sign-in token.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", "--ws-ping-interval", "20", "--no-access-log"]
