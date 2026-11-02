"""
JARV Backend - Source documentation ingestion (Upgrade 1)

Turns an official documentation page into searchable passages for the agents that use it:

1. fetch the page in full (public http(s) only, the same SSRF guard as fetch_url, 2 MB cap);
2. extract the main text as Markdown with trafilatura (menus, footers and banners dropped);
3. keep the text only when the source's licence allows it (``store``); a ``link_only`` source is listed and found
   by its title, and its text is read live when needed, never stored;
4. split on headings into passages of at most about 800 tokens, each under its own heading path;
5. embed the passages in batches; 6. version: changed text makes a new version and retires the old passages.

Secrets that appear in a page (example keys in documentation) are redacted before anything is stored.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_library import LICENCE_LINK_ONLY, LICENCE_STORE, KnowledgeChunk, KnowledgeSource

logger = logging.getLogger(__name__)

MAX_PAGE_BYTES = 2_000_000
FETCH_TIMEOUT = 30.0
CHARS_PER_TOKEN = 4
MAX_TOKENS = 800
USER_AGENT = "JARV-Knowledge/1.0 (documentation indexing)"

_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")


@dataclass
class Passage:
    heading_path: str
    content: str

    @property
    def tokens(self) -> int:
        return max(1, len(self.content) // CHARS_PER_TOKEN)


def extract_markdown(html: str, url: Optional[str] = None) -> str:
    """The page's main content as Markdown. Requires trafilatura (a declared dependency)."""
    import trafilatura

    text = trafilatura.extract(html, output_format="markdown", include_tables=True, include_links=False,
                               include_formatting=True, favor_precision=True, url=url)
    return (text or "").strip()


def split_passages(markdown: str, title: str = "") -> List[Passage]:
    """Split on headings (#, ##, ###, ####) into passages of at most MAX_TOKENS, each carrying the path of
    headings it sits under."""
    max_chars = MAX_TOKENS * CHARS_PER_TOKEN
    path: List[str] = [title] if title else []
    base = len(path)
    sections: List[Passage] = []
    body: List[str] = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            sections.append(Passage(" › ".join(p for p in path if p), text))
        body.clear()

    for line in markdown.splitlines():
        match = _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            del path[base + level - 1:]
            while len(path) < base + level - 1:
                path.append("")
            path.append(match.group(2).strip())
            continue
        body.append(line)
    flush()

    # Each heading's text stays under its own heading path, so a citation names the exact section; short sections
    # are kept as they are (merging them with neighbours put text under the wrong heading). Long ones split on
    # paragraph breaks into passages of at most MAX_TOKENS.
    passages: List[Passage] = []
    for section in sections:
        if len(section.content) <= max_chars:
            passages.append(section)
            continue
        piece: List[str] = []
        for paragraph in re.split(r"\n\s*\n", section.content):
            if piece and sum(len(p) for p in piece) + len(paragraph) > max_chars:
                passages.append(Passage(section.heading_path, "\n\n".join(piece)))
                piece = []
            piece.append(paragraph[: max_chars])
        if piece:
            passages.append(Passage(section.heading_path, "\n\n".join(piece)))
    return passages


async def fetch_page(url: str) -> Dict[str, Any]:
    """GET one public page in full. Returns {ok, url, html, reason}."""
    from app.core.internet import _ssrf_ok

    ok, reason = _ssrf_ok(url)
    if not ok:
        return {"ok": False, "url": url, "reason": reason}
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        return {"ok": False, "url": url, "reason": f"{type(exc).__name__}: {exc}"}
    final_ok, final_reason = _ssrf_ok(str(response.url))
    if not final_ok:
        return {"ok": False, "url": str(response.url), "reason": f"redirected to a blocked address: {final_reason}"}
    if response.status_code >= 400:
        return {"ok": False, "url": str(response.url), "reason": f"HTTP {response.status_code}"}
    return {"ok": True, "url": str(response.url), "html": response.text[:MAX_PAGE_BYTES]}


def _clean(text: str) -> str:
    from app.core.security import redact_text

    return redact_text(text)


class KnowledgeIngestor:
    """Installs and refreshes sources and their passages."""

    async def register(self, db: AsyncSession, entry: Dict[str, Any], *,
                       workspace_id=None) -> KnowledgeSource:
        """Create or update a source's catalogue record (no fetch)."""
        url = str(entry["url"]).strip()
        if not url.startswith("https://"):
            raise ValueError(f"Sources must use https: {url}")
        licence_class = entry.get("licence_class") or LICENCE_LINK_ONLY
        if licence_class not in (LICENCE_STORE, LICENCE_LINK_ONLY):
            raise ValueError(f"Unknown licence class {licence_class!r}")
        if licence_class == LICENCE_STORE and not (entry.get("licence") and entry.get("licence_evidence")):
            raise ValueError(f"{url}: storing text needs the licence and where it was read")
        source = (await db.execute(select(KnowledgeSource).where(
            KnowledgeSource.url == url,
            KnowledgeSource.workspace_id.is_(None) if workspace_id is None
            else KnowledgeSource.workspace_id == workspace_id))).scalar_one_or_none()
        if source is None:
            source = KnowledgeSource(url=url, workspace_id=workspace_id, version=0, status="pending", agents=[])
            db.add(source)
        source.title = entry["title"]
        source.publisher = entry["publisher"]
        source.licence = entry.get("licence")
        source.licence_evidence = entry.get("licence_evidence")
        source.licence_class = licence_class
        source.agents = sorted(set(source.agents or []) | set(entry.get("agents") or []))
        await db.flush()
        return source

    async def ingest_text(self, db: AsyncSession, source: KnowledgeSource, markdown: str) -> Dict[str, Any]:
        """Store a source's text as passages (a new version when the text changed)."""
        from app.core.memory.embeddings import get_embedding_service

        now = datetime.now(timezone.utc)
        if source.licence_class != LICENCE_STORE:
            source.status, source.fetched_at, source.last_error = "link_only", now, None
            await db.flush()
            return {"url": source.url, "status": "link_only", "passages": 0}
        markdown = _clean(markdown)
        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        if digest == source.content_sha256:
            source.status, source.fetched_at, source.last_error = "current", now, None
            await db.flush()
            return {"url": source.url, "status": "unchanged", "passages": 0, "version": source.version}
        passages = split_passages(markdown, source.title)
        if not passages:
            source.status, source.last_error = "empty", "No text could be extracted from the page."
            await db.flush()
            return {"url": source.url, "status": "empty", "passages": 0}
        vectors = await get_embedding_service().embed_many(
            [f"{p.heading_path}\n\n{p.content}" for p in passages])
        version = (source.version or 0) + 1
        await db.execute(update(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id,
                                                      KnowledgeChunk.is_active.is_(True)).values(is_active=False))
        for position, (passage, (vector, model_id)) in enumerate(zip(passages, vectors)):
            db.add(KnowledgeChunk(source_id=source.id, version=version, position=position,
                                  heading_path=passage.heading_path[:2000], content=passage.content,
                                  token_estimate=passage.tokens, embedding=vector, embedding_model=model_id,
                                  is_active=True))
        source.version, source.content_sha256 = version, digest
        source.status, source.fetched_at, source.last_error = "current", now, None
        await db.flush()
        return {"url": source.url, "status": "updated", "passages": len(passages), "version": version}

    async def refresh(self, db: AsyncSession, source: KnowledgeSource) -> Dict[str, Any]:
        """Fetch a source again and store its passages when they changed."""
        if source.licence_class != LICENCE_STORE:
            return await self.ingest_text(db, source, "")
        page = await fetch_page(source.url)
        if not page["ok"]:
            source.status, source.last_error = "error", str(page.get("reason"))[:1000]
            await db.flush()
            return {"url": source.url, "status": "error", "reason": page.get("reason")}
        try:
            markdown = extract_markdown(page["html"], page["url"])
        except Exception as exc:  # noqa: BLE001 - one bad page never stops the rest
            source.status, source.last_error = "error", f"extraction failed: {exc}"[:1000]
            await db.flush()
            return {"url": source.url, "status": "error", "reason": str(exc)}
        return await self.ingest_text(db, source, markdown)

    async def install(self, db: AsyncSession, entries: Iterable[Dict[str, Any]], *, fetch: bool = True,
                      agents: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Register the catalogue (optionally only the given agents' sources) and fetch each one."""
        results = []
        entries = list(entries)
        for entry in entries:
            if agents and not set(entry.get("agents") or []) & set(agents):
                continue
            source = await self.register(db, entry)
            results.append(await self.refresh(db, source) if fetch else {"url": source.url, "status": "registered"})
            await db.commit()
        if not agents:
            results += await self.retire_missing(db, {str(e["url"]).strip() for e in entries})
        return results

    async def retire_missing(self, db: AsyncSession, keep: set) -> List[Dict[str, Any]]:
        """Retire JARV-wide sources no longer in the catalogue (a moved page replaced by its new address): their
        passages go inactive and search skips them. Workspace-specific sources are never touched."""
        retired = []
        stale = (await db.execute(select(KnowledgeSource).where(
            KnowledgeSource.workspace_id.is_(None), KnowledgeSource.status != "retired"))).scalars().all()
        for source in stale:
            if source.url in keep:
                continue
            await db.execute(update(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id,
                                                          KnowledgeChunk.is_active.is_(True)).values(is_active=False))
            source.status, source.last_error = "retired", "No longer in the documentation catalogue."
            retired.append({"url": source.url, "status": "retired", "passages": 0})
        await db.commit()
        return retired


knowledge_ingestor = KnowledgeIngestor()
