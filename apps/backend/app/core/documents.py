"""
JAI Backend - Reading documents (Wave 6: Docling)

Docling (MIT, IBM Research) turns PDFs, Word, PowerPoint, Excel, HTML and scanned pages or images into Markdown
with their headings, lists and tables kept, reading scans with OCR. It runs as docling-serve on JAI's private
network with its models inside the image, so no document leaves Richard's computer. A conversion is kept in Redis
for a day (by the file's hash), so reading a long document part by part converts it once.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

FORMATS = (".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".csv", ".png", ".jpg", ".jpeg", ".tif",
           ".tiff", ".bmp", ".webp", ".asciidoc", ".adoc", ".xml")
MAX_BYTES = 60_000_000
CHUNK_CHARS = 16000
KEEP_SECONDS = 24 * 3600


class DocumentUnavailable(RuntimeError):
    """Docling is off, not running, or could not read the document."""


def docling_url() -> str:
    return str(getattr(settings, "DOCLING_URL", "") or "").rstrip("/")


def readable(name: str) -> bool:
    return name.lower().endswith(FORMATS)


async def _cached(digest: str) -> Optional[Dict[str, Any]]:
    try:
        from app.core.redis import get_redis

        raw = await asyncio.wait_for((await get_redis()).get(f"document:{digest}"), timeout=2)
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001 - the cache is a convenience
        return None


async def _keep(digest: str, value: Dict[str, Any]) -> None:
    try:
        from app.core.redis import get_redis

        await asyncio.wait_for((await get_redis()).set(f"document:{digest}", json.dumps(value), ex=KEEP_SECONDS),
                               timeout=2)
    except Exception:  # noqa: BLE001
        pass


async def convert(name: str, data: bytes, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """{"markdown", "seconds", "status", "cached"} for one document's bytes."""
    base = docling_url()
    if not base:
        raise DocumentUnavailable("JAI's document reader (Docling) is turned off on this computer.")
    if not readable(name):
        raise DocumentUnavailable(f"Docling does not read {name.rsplit('.', 1)[-1] if '.' in name else 'that'} "
                                  f"files; it reads {', '.join(FORMATS)}.")
    if len(data) > MAX_BYTES:
        raise DocumentUnavailable("The document is larger than 60 MB.")
    digest = hashlib.sha256(data).hexdigest()
    found = await _cached(digest)
    if found:
        return {**found, "cached": True}
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=5.0))
    try:
        response = await client.post(f"{base}/v1/convert/file", files={"files": (name, data)},
                                     data={"to_formats": "md", "image_export_mode": "placeholder", "do_ocr": "true"})
    except httpx.HTTPError as exc:
        raise DocumentUnavailable(f"JAI's document reader (Docling) could not be reached ({type(exc).__name__}).") from exc
    finally:
        if owned:
            await client.aclose()
    if response.status_code >= 400:
        raise DocumentUnavailable(f"Docling could not read {name}: {response.status_code} {response.text[:300]}")
    answer = response.json()
    markdown = str((answer.get("document") or {}).get("md_content") or "")
    status = str(answer.get("status") or "")
    if status not in ("success", "partial_success") or not markdown.strip():
        errors = "; ".join(str(e.get("error_message") or e) for e in answer.get("errors") or [] if e)[:300]
        raise DocumentUnavailable(f"Docling could not read {name} ({status or 'no status'}){': ' + errors if errors else ''}.")
    value = {"markdown": markdown, "seconds": round(float(answer.get("processing_time") or 0), 1), "status": status}
    await _keep(digest, value)
    return {**value, "cached": False}


def part(markdown: str, offset: int = 0) -> Dict[str, Any]:
    """One part of a converted document, with where the next part starts."""
    offset = max(0, int(offset or 0))
    text = markdown[offset:offset + CHUNK_CHARS]
    following = offset + len(text)
    return {"content": text, "offset": offset, "total_chars": len(markdown),
            "next_offset": following if following < len(markdown) else None}
