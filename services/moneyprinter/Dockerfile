# JAI's video maker: MoneyPrinterTurbo (open source, MIT) v1.3.9, driven by JAI. JAI writes the script and search
# terms with its own (metered) model and narrates it with its own voice, so MoneyPrinterTurbo never calls an AI
# provider: it gathers footage (Pexels, when a key is given, or JAI's own generated images), adds subtitles timed
# by faster-whisper on the processor, and renders the video with FFmpeg. jai_render.py is the small API JAI calls.
FROM python:3.11-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 1000 jaivideo

ARG MPT_REF=v1.3.9
WORKDIR /MoneyPrinterTurbo
RUN git clone --depth 1 --branch "$MPT_REF" https://github.com/harry0703/MoneyPrinterTurbo.git . && rm -rf .git \
    && pip install -r requirements.txt && pip install "pytest>=8,<10" "huggingface_hub>=0.24" \
    && cp config.example.toml config.toml
# The subtitle timing model, downloaded while building so rendering needs no model download.
RUN python -c "from huggingface_hub import snapshot_download; \
snapshot_download('Systran/faster-whisper-small', local_dir='/MoneyPrinterTurbo/models/whisper-small')"
COPY jai_render.py ./
COPY tests ./jai_tests
RUN mkdir -p storage && chown -R jaivideo:jaivideo /MoneyPrinterTurbo
ENV PYTHONPATH=/MoneyPrinterTurbo

USER jaivideo
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8090/health || exit 1
CMD ["uvicorn", "jai_render:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
