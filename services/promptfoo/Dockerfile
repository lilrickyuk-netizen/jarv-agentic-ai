# JAI's prompt checks: promptfoo (open source, MIT) 0.125.1 behind JAI's small API (server.js). Every model call
# goes to JAI's model gateway (metered, inside the daily limit); promptfoo has no provider key of its own.
FROM node:22-bookworm-slim

ENV NODE_ENV=production PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1 \
    PROMPTFOO_DISABLE_REMOTE_GENERATION=true PROMPTFOO_DISABLE_SHARING=1 PROMPTFOO_CACHE_ENABLED=false \
    PROMPTFOO_DISABLE_WAL_MODE=true PROMPTFOO_CONFIG_DIR=/home/node/.promptfoo
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && npm install -g promptfoo@0.125.1 && npm cache clean --force
WORKDIR /jai
COPY server.js test.js ./
USER node
EXPOSE 8792
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8792/health || exit 1
CMD ["node", "server.js"]
