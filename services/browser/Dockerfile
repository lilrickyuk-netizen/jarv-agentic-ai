# JAI's browser: browser-use (open source, MIT) 0.13.14 with Playwright's Chromium, behind JAI's small API
# (server.py). browser-use reads pages and carries out actions; it never calls an AI model here: JAI's own agent
# decides each step through JAI's router, inside the daily spending limit.
FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright BROWSER_USE_HEADLESS=true ANONYMIZED_TELEMETRY=false \
    BROWSER_USE_CLOUD_SYNC=false BROWSER_USE_LOGGING_LEVEL=warning

RUN apt-get update && apt-get install -y --no-install-recommends curl fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 1000 jaibrowser
RUN pip install "browser-use==0.13.14" "playwright==1.55.0" "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1" \
        "pytest>=8,<10" "pytest-asyncio>=0.23,<2" \
    && playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /ms-playwright

WORKDIR /jai
COPY server.py ./
COPY tests ./tests
USER jaibrowser
EXPOSE 8790
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8790/health || exit 1
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8790", "--no-access-log"]
