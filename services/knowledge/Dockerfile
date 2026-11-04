# JAI's knowledge service: Graphiti (Apache-2.0) 0.31.2 on embedded FalkorDB Lite, and Mem0 (Apache-2.0) 2.2.1 on
# JAI's PostgreSQL (pgvector). Both reach a model only through JAI's model gateway (metered, inside the daily limit).
FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GRAPHITI_TELEMETRY_ENABLED=false MEM0_TELEMETRY=false MEM0_DIR=/data/mem0

RUN apt-get update && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 1000 jaiknow \
    && mkdir -p /data/graph /data/mem0 && chown -R jaiknow:jaiknow /data
RUN pip install "graphiti-core[falkordblite]==0.31.2" "mem0ai==2.2.1" "psycopg2-binary>=2.9,<3" \
        "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1" "pytest>=8,<10" "httpx>=0.27,<1"

WORKDIR /jai
COPY server.py ./
COPY tests ./tests
USER jaiknow
VOLUME ["/data"]
EXPOSE 8791
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8791/health || exit 1
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8791", "--no-access-log"]
