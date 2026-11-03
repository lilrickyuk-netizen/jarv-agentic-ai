"""
JAI Backend - Researching a question on the web (Wave 3)

The method of GPT Researcher (assafelovic/gpt-researcher), run on JAI's own provider router so every model call is
counted against today's AI spend and stops at the daily limit:

1. Plan: JAI's model turns the question into a few distinct search queries (different angles, recent where it
   matters).
2. Search: each query goes to JAI's SearXNG at once; the results are merged, a source found by several queries or
   engines ranking higher.
3. Read: the best sources are read in parallel (JavaScript pages through JAI's Crawl4AI browser), each cut to the
   part worth reading.
4. Write: JAI's model writes the answer from those sources only, citing each claim with [n], saying where they
   disagree or fall short, and listing the sources.

Read-only: nothing is posted, signed in to or downloaded. Pages are fetched through the same SSRF-guarded reader as
fetch_url, and secret-shaped text is removed from them before the model sees it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEPTHS = {"quick": {"queries": 3, "sources": 5, "chars": 5000, "tokens": 1200},
          "deep": {"queries": 5, "sources": 10, "chars": 6000, "tokens": 2600}}
READ_AT_ONCE = 5


def _model() -> str:
    from app.core.command import CommandService

    return CommandService().model


async def _complete(system: str, user: str, max_tokens: int) -> str:
    from app.core.providers import CompletionRequest, Message, get_router

    response = await get_router().complete(CompletionRequest(
        model=_model(), system=system, max_tokens=max_tokens, temperature=0.2, reasoning_effort="low",
        messages=[Message(role="user", content=user)]))
    return (response.content or "").strip()


def _queries_from(text: str, question: str, limit: int) -> List[str]:
    """The planned queries from the model's reply (a JSON list, or one per line), the question itself first."""
    found: List[str] = []
    try:
        match = re.search(r"\[.*\]", text, re.S)
        parsed = json.loads(match.group(0)) if match else []
        found = [str(q) for q in parsed if isinstance(q, (str, int, float))]
    except ValueError:
        found = []
    if not found:
        found = [re.sub(r"^[\s\-*\d.)]+", "", line).strip().strip('"') for line in text.splitlines()]
    queries: List[str] = []
    for q in [question, *found]:
        q = " ".join(str(q).split())[:200]
        if len(q) > 2 and q.lower() not in {x.lower() for x in queries}:
            queries.append(q)
    return queries[:limit]


def rank_sources(searches: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Merge every query's results: a page found by more queries and engines, and higher in them, ranks first;
    one page per site until the other sites run out."""
    scores: Dict[str, Dict[str, Any]] = {}
    for search in searches:
        for position, item in enumerate(search.get("results") or []):
            url = item.get("url")
            if not url:
                continue
            entry = scores.setdefault(url, {**item, "score": 0.0, "queries": 0})
            entry["score"] += 1.0 / (position + 1) + 0.25 * max(0, len(item.get("engines") or []) - 1)
            entry["queries"] += 1
    ranked = sorted(scores.values(), key=lambda e: (e["queries"], e["score"]), reverse=True)
    chosen, sites = [], set()
    for entry in ranked:
        site = urlparse(entry["url"]).netloc.removeprefix("www.")
        if site not in sites:
            chosen.append(entry)
            sites.add(site)
    for entry in ranked:
        if len(chosen) >= limit:
            break
        if entry not in chosen:
            chosen.append(entry)
    return chosen[:limit]


async def research(question: str, depth: str = "quick", category: Optional[str] = None,
                   time_range: Optional[str] = None) -> Dict[str, Any]:
    """Research a question on the web and answer it with cited sources (see the module description)."""
    from app.core.internet import fetch_url, web_search

    question = " ".join((question or "").split())
    if len(question) < 3:
        return {"ok": False, "reason": "Say what to research."}
    plan = DEPTHS.get(depth, DEPTHS["quick"])
    today = datetime.now(timezone.utc).date().isoformat()

    planned = await _complete(
        "You plan web searches for JAI, an AI operating system. Return only a JSON list of search queries.",
        f"Today is {today}. Question: {question}\nWrite {plan['queries'] - 1} search queries that together cover "
        f"it from different angles (facts, recent news or changes, official sources, comparisons, criticism). "
        f"Short, as a person types into a search engine; include the year where recency matters.",
        300)
    queries = _queries_from(planned, question, plan["queries"])
    searches = await asyncio.gather(*(web_search(q, 8, category, time_range) for q in queries))
    candidates = rank_sources(list(searches), plan["sources"] + 4)
    if not candidates:
        reasons = "; ".join(sorted({str(s.get("reason")) for s in searches if s.get("reason")}))
        return {"ok": False, "question": question, "queries": queries,
                "reason": f"The searches found nothing to read{': ' + reasons if reasons else ''}."}

    gate = asyncio.Semaphore(READ_AT_ONCE)

    async def read(entry):
        async with gate:
            page = await fetch_url(entry["url"])
        text = str(page.get("text") or "").strip()
        return {**entry, "text": text[:plan["chars"]], "title": page.get("title") or entry.get("title"),
                "rendered": bool(page.get("rendered")), "ok": bool(page.get("ok")) and len(text) > 200}

    pages = [p for p in await asyncio.gather(*(read(c) for c in candidates)) if p["ok"]][:plan["sources"]]
    if not pages:  # every page refused or empty: answer from the search snippets, and say so
        pages = [{**c, "text": c.get("snippet") or "", "snippet_only": True} for c in candidates[:plan["sources"]]]
    sources = [{"n": i + 1, "title": (p.get("title") or p["url"])[:160], "url": p["url"],
                "published": p.get("published"), "snippet_only": bool(p.get("snippet_only"))}
               for i, p in enumerate(pages)]
    excerpts = "\n\n".join(f"[{i + 1}] {p.get('title') or ''} ({p['url']})"
                           f"{' published ' + str(p['published']) if p.get('published') else ''}\n{p['text']}"
                           for i, p in enumerate(pages))
    report = await _complete(
        "You are JAI's research analyst writing for Richard Curley. Answer from the numbered sources only, never "
        "from memory. Cite every factual claim with its source number in square brackets, e.g. [2]. Lead with "
        "the direct answer, then the supporting detail, with numbers, dates and names. Say plainly where sources "
        "disagree, are old, or do not settle the question. British English. Plain prose paragraphs, no headings, "
        "no list of sources at the end (JAI adds it).",
        f"Today is {today}. Question: {question}\n\nSources:\n{excerpts}", plan["tokens"])
    return {"ok": True, "question": question, "depth": depth if depth in DEPTHS else "quick", "queries": queries,
            "report": report, "sources": sources,
            "searched_with": sorted({s.get("source") for s in searches if s.get("ok")} - {None}),
            "pages_read": sum(1 for p in pages if not p.get("snippet_only")),
            "rendered_pages": sum(1 for p in pages if p.get("rendered"))}


def research_card(result: Dict[str, Any]) -> Dict[str, Any]:
    """The research, as a card for Richard's screen: the answer, then the numbered sources."""
    paragraphs = [p.strip() for p in str(result.get("report") or "").split("\n") if p.strip()]
    return {"kind": "research", "title": str(result.get("question") or "Research")[:160],
            "subtitle": (f"{result.get('pages_read', 0)} sources read, searched with "
                         f"{', '.join(result.get('searched_with') or ['the web'])}"),
            "sections": [{"heading": "Answer", "items": paragraphs or ["No answer was written."]},
                         {"heading": "Sources", "items": [f"[{s['n']}] {s['title']} — {s['url']}"
                                                          for s in result.get("sources") or []]}]}
