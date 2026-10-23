"""Unauthenticated, read-only public research via Stack Exchange's API."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

from app.core.internet import FETCH_TIMEOUT, _ssrf_ok


_API_URL = "https://api.stackexchange.com/2.3/search/advanced"
_MAX_RESULTS = 3
_MAX_EXCERPT_CHARS = 1800


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


async def search_public_sources(query: str, limit: int = _MAX_RESULTS) -> List[Dict[str, Any]]:
    """Search licensed Stack Overflow posts and retain attribution metadata."""
    normalized = query.strip()
    if not normalized:
        return []
    safe, reason = _ssrf_ok(_API_URL)
    if not safe:
        raise RuntimeError(f"Public source endpoint failed SSRF validation: {reason}")

    timeout = httpx.Timeout(FETCH_TIMEOUT)
    headers = {"User-Agent": "JARV-Research/1.0 (public source retrieval)"}
    stopwords = {"about", "after", "also", "and", "are", "for", "from", "how",
                 "into", "more", "that", "the", "this", "with", "what"}
    terms = [term for term in re.findall(r"[a-zA-Z0-9_-]{3,}", normalized)
             if term.lower() not in stopwords]
    query_variants = [normalized[:400]]
    for width in (4, 3):
        compact = " ".join(terms[:width])
        if len(terms) > width and compact and compact not in query_variants:
            query_variants.append(compact)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        matches = []
        for search_query in query_variants:
            response = await client.get(_API_URL, params={
                "order": "desc", "sort": "relevance", "q": search_query,
                "site": "stackoverflow", "pagesize": max(1, min(limit, _MAX_RESULTS)),
                "filter": "withbody",
            }, headers=headers)
            response.raise_for_status()
            search_data = response.json()
            if search_data.get("error_id"):
                raise RuntimeError(
                    f"Stack Exchange API error {search_data['error_id']}: "
                    f"{search_data.get('error_message', 'request failed')}"
                )
            matches = search_data.get("items", []) or []
            if matches:
                break
    retrieved_at = datetime.now(timezone.utc).isoformat()
    sources = []
    for item in matches:
        source_url = item.get("link", "")
        body = item.get("body", "")
        license_name = item.get("content_license", "")
        owner = item.get("owner", {}) or {}
        if (not source_url.startswith("https://stackoverflow.com/questions/")
                or not body or not license_name.startswith("CC BY-SA")):
            continue
        author = str(owner.get("display_name", ""))
        author_url = str(owner.get("link", ""))
        excerpt = _clean(body)[:_MAX_EXCERPT_CHARS]
        sources.append({
            "title": str(item.get("title", ""))[:300],
            "url": source_url,
            "publisher": "Stack Overflow",
            "content": excerpt,
            "license": license_name,
            "author": author,
            "author_url": author_url,
            "score": item.get("score"),
            "answer_count": item.get("answer_count"),
            "page_created_at": datetime.fromtimestamp(
                int(item["creation_date"]), timezone.utc).isoformat()
                if item.get("creation_date") else None,
            "retrieved_at": retrieved_at,
        })
    return sources
