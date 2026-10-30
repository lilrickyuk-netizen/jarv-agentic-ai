"""Local sherpa-onnx KWS model management and streaming helpers."""

import asyncio
import hashlib
import shutil
import tarfile
import tempfile
import threading
from pathlib import Path

import httpx
from fastapi import HTTPException

from app.core.config import settings

MODEL_ARCHIVE = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/{MODEL_ARCHIVE}"
MODEL_SHA256 = "f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a"
MODEL_FILES = {
    "encoder": "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    "decoder": "decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
    "joiner": "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    "tokens": "tokens.txt",
    "bpe": "bpe.model",
    "keywords": "jarv-keywords.txt",
}
WAKE_PHRASE = "TALK TO ME"
WAKE_PHRASE_DISPLAY = "Talk to me."
WAKE_KEYWORD_ID = "TALK_TO_ME"
_MODEL_LOCK = threading.Lock()
_STREAM_LOCK = threading.RLock()
_INSTALL_LOCK = asyncio.Lock()
_spotter = None
_active_streams = 0


def model_directory() -> Path:
    return Path(settings.WAKEWORD_MODEL_DIR).expanduser().resolve()


def model_is_ready() -> bool:
    directory = model_directory()
    return all((directory / name).is_file() for name in MODEL_FILES.values())


def _keyword_spotter():
    global _spotter
    with _MODEL_LOCK:
        if _spotter is not None:
            return _spotter
        if not model_is_ready():
            raise RuntimeError("Wake-word model is not installed")
        import sherpa_onnx

        directory = model_directory()
        _spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(directory / MODEL_FILES["tokens"]),
            encoder=str(directory / MODEL_FILES["encoder"]),
            decoder=str(directory / MODEL_FILES["decoder"]),
            joiner=str(directory / MODEL_FILES["joiner"]),
            num_threads=1,
            max_active_paths=4,
            keywords_file=str(directory / MODEL_FILES["keywords"]),
            keywords_score=1.0,
            keywords_threshold=0.35,
            num_trailing_blanks=1,
            provider="cpu",
        )
        return _spotter


def create_stream():
    global _active_streams
    with _STREAM_LOCK:
        stream = _keyword_spotter().create_stream()
        _active_streams += 1
        return stream


def process_audio_frame(stream, frame: bytes) -> str | None:
    import numpy as np

    if not frame or len(frame) > 128 * 1024 or len(frame) % 4:
        raise ValueError("Invalid wake audio frame")
    samples = np.frombuffer(frame, dtype="<f4")
    if not np.isfinite(samples).all():
        raise ValueError("Wake audio frame contains invalid samples")
    stream.accept_waveform(16000, np.clip(samples, -1.0, 1.0))
    spotter = _keyword_spotter()
    while spotter.is_ready(stream):
        spotter.decode_stream(stream)
        keyword = spotter.get_result(stream)
        if keyword:
            spotter.reset_stream(stream)
            return keyword
    return None


def free_stream(stream) -> None:
    global _active_streams
    if stream is not None:
        try:
            stream.input_finished()
        finally:
            with _STREAM_LOCK:
                _active_streams = max(0, _active_streams - 1)


def _write_keyword_file(directory: Path) -> None:
    import sentencepiece

    tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(directory / MODEL_FILES["bpe"]))
    pieces = tokenizer.encode(WAKE_PHRASE, out_type=str)
    if not pieces:
        raise ValueError("SentencePiece returned no keyword tokens")
    contents = f"{' '.join(pieces)} @{WAKE_KEYWORD_ID}\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, prefix=".jarv-keywords-", delete=False) as temporary_file:
        temporary_file.write(contents)
        temporary_path = Path(temporary_file.name)
    try:
        temporary_path.replace(directory / MODEL_FILES["keywords"])
    finally:
        temporary_path.unlink(missing_ok=True)


def install_status() -> dict:
    phrase_current = False
    if model_is_ready():
        try:
            import sentencepiece

            tokenizer = sentencepiece.SentencePieceProcessor(
                model_file=str(model_directory() / MODEL_FILES["bpe"])
            )
            expected = " ".join(tokenizer.encode(WAKE_PHRASE, out_type=str)) + f" @{WAKE_KEYWORD_ID}"
            actual = (model_directory() / MODEL_FILES["keywords"]).read_text(encoding="utf-8").strip()
            phrase_current = actual == expected
        except (OSError, RuntimeError, ValueError):
            phrase_current = False
    return {
        "installed": model_is_ready(),
        "phrase_current": phrase_current,
        "model": "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01",
        "phrase": WAKE_PHRASE_DISPLAY,
        "runtime": "local CPU keyword spotting",
        "license": "Apache-2.0",
    }


async def install_model() -> dict:
    global _spotter
    async with _INSTALL_LOCK:
        if model_is_ready():
            target = model_directory()
            keyword_path = target / MODEL_FILES["keywords"]
            with _STREAM_LOCK:
                if _active_streams:
                    raise HTTPException(status_code=409, detail="Disable hands-free before updating the wake phrase")
                previous_keywords = keyword_path.read_bytes()
                with _MODEL_LOCK:
                    previous_spotter = _spotter
                _write_keyword_file(target)
                with _MODEL_LOCK:
                    _spotter = None
                try:
                    await asyncio.to_thread(_keyword_spotter)
                except Exception as exc:
                    keyword_path.write_bytes(previous_keywords)
                    with _MODEL_LOCK:
                        _spotter = previous_spotter
                    raise HTTPException(status_code=502, detail="Updated wake phrase failed runtime validation") from exc
            return install_status()

        target = model_directory()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise HTTPException(status_code=409, detail="An incomplete wake model directory exists; remove it before retrying")

        with tempfile.TemporaryDirectory(prefix="jarv-kws-", dir=target.parent) as temporary:
            staging = Path(temporary)
            archive_path = staging / MODEL_ARCHIVE
            digest = hashlib.sha256()
            total = 0
            try:
                timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    async with client.stream("GET", MODEL_URL) as response:
                        response.raise_for_status()
                        with archive_path.open("wb") as archive_file:
                            async for chunk in response.aiter_bytes(1024 * 1024):
                                total += len(chunk)
                                if total > 30 * 1024 * 1024:
                                    raise HTTPException(status_code=502, detail="Wake model archive exceeds expected size")
                                digest.update(chunk)
                                archive_file.write(chunk)
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=503, detail="Could not download the official wake model") from exc

            if digest.hexdigest() != MODEL_SHA256:
                raise HTTPException(status_code=502, detail="Wake model checksum verification failed")

            extracted = staging / "model"
            extracted.mkdir()
            required = {name for name in MODEL_FILES.values() if name != MODEL_FILES["keywords"]}
            try:
                with tarfile.open(archive_path, mode="r:bz2") as archive:
                    for member in archive.getmembers():
                        name = Path(member.name).name
                        if name not in required:
                            continue
                        if not member.isfile() or member.size > 25 * 1024 * 1024:
                            raise HTTPException(status_code=502, detail="Wake model contains an invalid file")
                        source = archive.extractfile(member)
                        if source is None:
                            raise HTTPException(status_code=502, detail="Wake model file could not be read")
                        with source, (extracted / name).open("wb") as destination_file:
                            shutil.copyfileobj(source, destination_file)
            except (tarfile.TarError, OSError) as exc:
                raise HTTPException(status_code=502, detail="Wake model archive is invalid") from exc

            missing = required.difference(path.name for path in extracted.iterdir())
            if missing:
                raise HTTPException(status_code=502, detail="Wake model archive is missing required files")

            try:
                _write_keyword_file(extracted)
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                raise HTTPException(status_code=502, detail="Could not prepare the exact wake phrase") from exc

            extracted.rename(target)

        with _MODEL_LOCK:
            _spotter = None
        try:
            await asyncio.to_thread(_keyword_spotter)
        except Exception as exc:
            shutil.rmtree(target, ignore_errors=True)
            raise HTTPException(status_code=502, detail="Wake model failed its runtime validation") from exc
        return install_status()
