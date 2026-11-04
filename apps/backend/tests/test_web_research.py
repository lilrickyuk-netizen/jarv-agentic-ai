"""
Wave 3, research: JAI searches with its own SearXNG (many engines at once), falling back to DuckDuckGo; reads
pages with Crawl4AI's browser when a plain read comes back thin or refused; and researches a question the way
GPT Researcher does (plan searches, merge and rank sources, read them, write a cited answer) on JAI's own metered
router. Every agent has these tools; the voice can look things up and put the answer on screen.
Real: the internet module, the research pipeline, the toolbox and runtime, the database. Outgoing HTTP goes to
an httpx MockTransport and the model to scripted replies; nothing reaches the internet or a provider.
"""
import asyncio
import json
from typing import Any, Dict, List

import httpx
import pytest

from app.core import internet
from app.core.config import settings
from app.core.internet import research as research_module
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12c_agent_tools import _agent, _ctx, _seed  # noqa: F401
from app.core.agents.specialists.documentation import DocumentationAgent
from app.core.agents.toolbox import AgentToolbox, WEB_TOOLS
from app.core.agents.base import AuthorityLevel

LONG = "JAI reads the whole article. " * 60


def _run(coro):
    return asyncio.run(coro)


def searx_payload(prefix: str, n: int = 3) -> Dict[str, Any]:
    return {"results": [{"title": f"{prefix} {i}", "url": f"https://site{i}.example.org/{prefix}",
                         "content": f"snippet {i}", "engines": ["google", "bing"] if i == 0 else ["brave"],
                         "publishedDate": "2026-10-30T09:00:00"} for i in range(n)],
            "answers": ["42"], "suggestions": ["more"], "unresponsive_engines": [["qwant", "timeout"]]}


@pytest.fixture
def web(monkeypatch):
    """SearXNG and Crawl4AI configured; every request recorded and answered by `routes`."""
    monkeypatch.setattr(settings, "SEARXNG_URL", "http://searxng:8080")
    monkeypatch.setattr(settings, "CRAWL4AI_URL", "http://crawl4ai:11235")
    monkeypatch.setattr(settings, "CRAWL4AI_TOKEN", "c4a-test-token")
    monkeypatch.setattr(internet, "_ssrf_ok", lambda url: (False, "private address") if "127.0.0.1" in url
                        else (True, None))
    requests: List[httpx.Request] = []
    routes: Dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        for prefix, respond in routes.items():
            if str(request.url).startswith(prefix):
                return respond(request)
        return httpx.Response(404, text="no route")

    real = httpx.AsyncClient
    monkeypatch.setattr(internet.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler),
                                                                           **{k: v for k, v in kw.items()
                                                                              if k != "transport"}))
    return {"requests": requests, "routes": routes}


def test_searxng_results_are_merged_with_their_engines_and_dates():
    results = internet.parse_searxng({"results": [
        {"title": "A", "url": "https://a.example/x", "content": "a", "engines": ["google", "bing"],
         "publishedDate": "2026-11-01"},
        {"title": "A again", "url": "https://a.example/x", "content": "dupe"},
        {"title": "Not a page", "url": "javascript:alert(1)"},
        {"title": "B", "url": "https://b.example/", "content": "b", "engine": "brave"}]}, 10)
    assert [r["url"] for r in results] == ["https://a.example/x", "https://b.example/"]
    assert results[0]["engines"] == ["google", "bing"] and results[0]["published"] == "2026-11-01"
    assert results[1]["engines"] == ["brave"]


def test_search_goes_to_searxng_and_falls_back_to_duckduckgo(web):
    web["routes"]["http://searxng:8080/search"] = lambda r: httpx.Response(200, json=searx_payload("news"))
    found = _run(internet.web_search("rust 2026 release", 5, "news", "week"))
    sent = web["requests"][-1]
    assert found["ok"] and found["source"] == "searxng" and len(found["results"]) == 3
    assert found["answers"] == ["42"] and found["engines_unresponsive"] == ["qwant"]
    assert sent.url.params["format"] == "json" and sent.url.params["categories"] == "news"
    assert sent.url.params["time_range"] == "week" and sent.url.params["language"] == "en-GB"

    web["routes"]["http://searxng:8080/search"] = lambda r: httpx.Response(502, text="down")
    web["routes"]["https://html.duckduckgo.com"] = lambda r: httpx.Response(200, text=(
        '<div class="result"><a class="result__a" href="https://ddg.example/page">DDG page</a>'
        '<a class="result__snippet">from duckduckgo</a></div>'))
    fallback = _run(internet.web_search("rust 2026 release", 5))
    assert fallback["ok"] and fallback["source"] == "duckduckgo" and "502" in fallback["searxng"]
    assert fallback["results"][0]["url"] == "https://ddg.example/page"


def test_a_thin_page_is_read_again_through_the_browser_and_private_addresses_never_are(web):
    web["routes"]["https://app.example.com/"] = lambda r: httpx.Response(
        200, headers={"content-type": "text/html"}, text="<html><title>App</title><body><div id=root></div></body></html>")
    web["routes"]["http://crawl4ai:11235/md"] = lambda r: httpx.Response(200, json={
        "markdown": "# Pricing\n\n" + LONG, "success": True})
    page = _run(internet.fetch_url("https://app.example.com/"))
    rendered_request = web["requests"][-1]
    assert page["ok"] and page["rendered"] is True and page["title"] == "Pricing" and "whole article" in page["text"]
    assert json.loads(rendered_request.content) == {"url": "https://app.example.com/", "f": "fit", "c": "0"}
    assert rendered_request.headers["authorization"] == "Bearer c4a-test-token"  # the browser's access token

    web["routes"]["https://blog.example.com/"] = lambda r: httpx.Response(
        200, headers={"content-type": "text/plain"}, text=LONG)
    count = len(web["requests"])
    plain = _run(internet.fetch_url("https://blog.example.com/"))
    assert plain["ok"] and not plain.get("rendered") and len(web["requests"]) == count + 1  # full page: no browser

    blocked = _run(internet.fetch_url("http://127.0.0.1:8000/api/health", render=True))
    assert blocked["blocked"] is True and not any("127.0.0.1" in str(r.url) for r in web["requests"])


def test_sources_found_by_more_searches_rank_first_one_per_site_first():
    searches = [{"results": [{"url": "https://a.org/1", "engines": ["google", "bing"]},
                             {"url": "https://a.org/2"}, {"url": "https://b.org/1"}]},
                {"results": [{"url": "https://b.org/1"}, {"url": "https://c.org/1"}]}]
    ranked = [s["url"] for s in research_module.rank_sources(searches, 4)]
    assert ranked[0] == "https://b.org/1"                       # found by both searches
    assert ranked[:3] == ["https://b.org/1", "https://a.org/1", "https://c.org/1"]  # one per site first
    assert ranked[3] == "https://a.org/2"


def test_a_question_is_researched_from_cited_sources(web, monkeypatch):
    calls: List[Dict[str, Any]] = []

    async def model(system, user, max_tokens):
        calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if len(calls) == 1:
            return '["postgres 18 release date", "postgres 18 new features 2026"]'
        return "PostgreSQL 18 was released in September 2025 [1] and adds asynchronous I/O [2]."

    monkeypatch.setattr(research_module, "_complete", model)
    web["routes"]["http://searxng:8080/search"] = lambda r: httpx.Response(
        200, json=searx_payload(r.url.params["q"].split()[-1]))
    web["routes"]["https://site"] = lambda r: httpx.Response(200, headers={"content-type": "text/plain"},
                                                             text=f"{r.url} " + LONG)
    found = _run(research_module.research("When was PostgreSQL 18 released and what is new?"))

    assert found["ok"] and found["queries"][0] == "When was PostgreSQL 18 released and what is new?"
    assert len(found["queries"]) == 3 and found["searched_with"] == ["searxng"]
    assert found["pages_read"] == len(found["sources"]) >= 3 and found["sources"][0]["n"] == 1
    assert "[1]" in found["report"]
    writing = calls[1]
    assert "Cite every factual claim" in writing["system"] and "never from memory" in writing["system"]
    assert "[1] " in writing["user"] and "whole article" in writing["user"]
    card = research_module.research_card(found)
    assert card["kind"] == "research" and card["sections"][1]["items"][0].startswith("[1] ")


def test_research_that_finds_nothing_says_why(web, monkeypatch):
    async def model(system, user, max_tokens):
        return "[]"

    monkeypatch.setattr(research_module, "_complete", model)
    web["routes"]["http://searxng:8080/search"] = lambda r: httpx.Response(200, json={"results": []})
    web["routes"]["https://html.duckduckgo.com"] = lambda r: httpx.Response(200, text="<html></html>")
    found = _run(research_module.research("something nobody has written about"))
    assert found["ok"] is False and "found nothing" in found["reason"]


def test_every_agent_can_search_and_research_the_web_and_it_is_recorded(web, monkeypatch):
    web["routes"]["http://searxng:8080/search"] = lambda r: httpx.Response(200, json=searx_payload("docs"))

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, None)
            agent = _agent(DocumentationAgent, ws_id, user_id, AuthorityLevel.LEVEL_1_BASIC_TOOLS)
            box = await AgentToolbox(agent, _ctx(db, ws_id, user_id)).prepare()
            searched = await box.call("web_search", {"query": "fastapi lifespan events", "category": "it"})
            return box.available, searched, list(box.runtime.records) if hasattr(box.runtime, "records") else None

    available, searched, _ = _run(run())
    assert set(WEB_TOOLS) <= set(available)
    assert searched["success"] is True and searched["source"] == "searxng" and len(searched["results"]) == 3
    assert web["requests"][-1].url.params["categories"] == "it"


def test_the_voice_looks_things_up_and_puts_the_answer_on_screen(monkeypatch):
    from app.core.voice import live

    async def fake_research(question, depth="quick", category=None, time_range=None):
        return {"ok": True, "question": question, "report": "Brent crude is about 70 dollars [1].",
                "sources": [{"n": 1, "title": "Reuters", "url": "https://reuters.example/oil"}],
                "searched_with": ["searxng"], "pages_read": 1}

    monkeypatch.setattr(research_module, "research", fake_research)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, _ = await _seed(db, None)
            return await live.run_tool(db, user_id, "research_web", {"question": "What is the oil price?"})

    output = _run(run())
    assert output["answer"].startswith("Brent crude") and output["sources"] == ["[1] Reuters (https://reuters.example/oil)"]
    assert output["card"]["kind"] == "research" and "on his screen" in output["note"]
    assert "research_web" in {t["name"] for t in live.VOICE_TOOLS}
    assert "never answer from memory" in live.instructions([])


def test_github_release_pages_are_read_from_githubs_own_records_stable_first(web):
    releases = [{"tag_name": "v16.5.0-canary.12", "prerelease": True, "published_at": "2026-11-03T10:00:00Z"},
                {"tag_name": "v16.5.0-canary.11", "prerelease": True, "published_at": "2026-11-02T10:00:00Z"},
                {"tag_name": "v16.4.5", "name": "v16.4.5", "prerelease": False, "published_at": "2026-11-02T18:00:00Z",
                 "body": "Fixes a cache bug."},
                {"tag_name": "draft", "draft": True},
                {"tag_name": "v16.4.4", "prerelease": False, "published_at": "2026-10-30T18:00:00Z"}]
    web["routes"]["https://api.github.com/repos/vercel/next.js/releases"] = lambda r: httpx.Response(200, json=releases)
    page = _run(internet.fetch_url("https://github.com/vercel/next.js/releases"))
    assert page["ok"] and page["source"] == "github_api"
    assert "Latest stable release: v16.4.5 (v16.4.5), published 2026-11-02." in page["text"]
    assert "- v16.5.0-canary.12: pre-release, published 2026-11-03" in page["text"]
    assert "draft" not in page["text"] and "Fixes a cache bug." in page["text"]
    assert web["requests"][-1].headers["accept"] == "application/vnd.github+json"
    # Any other GitHub page, or GitHub not answering, is read the ordinary way.
    assert internet._GITHUB_RELEASES.match("https://github.com/vercel/next.js/issues") is None


def test_official_sources_outrank_aggregators():
    searches = [{"results": [{"url": "https://endoflife.date/nextjs"}, {"url": "https://github.com/vercel/next.js/releases"}]}]
    assert research_module.rank_sources(searches, 2)[0]["url"] == "https://github.com/vercel/next.js/releases"


def test_reading_the_same_page_twice_never_locks_or_breaks_the_mission(web, monkeypatch):
    """Two agents reading one page used to update the same memory row at once and deadlock, which rolled back the
    mission's whole transaction. A kept source record is now left untouched, and a failed write undoes only itself."""
    from sqlalchemy import select

    from app.core.command.tool_runtime import ToolRuntime
    from app.core.jarv_memory import memory_service
    from app.models.memory import Memory
    from app.models.workspace import Workspace

    web["routes"]["https://plexecute.example/"] = lambda r: httpx.Response(
        200, headers={"content-type": "text/plain"}, text=LONG)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, None)
            runtime = ToolRuntime(db, ws_id, None, operator="agent:research", authority_level=1, user_id=user_id)
            await runtime.fetch_url("https://plexecute.example/")
            await runtime.fetch_url("https://plexecute.example/")
            kept = (await db.execute(select(Memory).where(Memory.workspace_id == ws_id,
                                                          Memory.memory_type == "source"))).scalars().all()
            reinforced = [m.meta_data.get("reinforced") for m in kept]

            async def deadlock(*args, **kwargs):
                raise RuntimeError("deadlock detected")

            monkeypatch.setattr(memory_service, "add", deadlock)
            again = await runtime.fetch_url("https://plexecute.example/")
            still_usable = (await db.execute(select(Workspace).where(Workspace.id == ws_id))).scalar_one()
            await db.commit()
            return len(kept), reinforced, again, still_usable.id == ws_id

    count, reinforced, again, usable = _run(run())
    assert count == 1 and reinforced == [None]   # one record, never updated by the second read
    assert again["ok"] is True and usable        # the failed record write did not spoil the mission's session


def test_a_research_command_is_researched_not_answered_with_a_fixed_page():
    """'research ...' and 'look up ...' commands used to fetch nodejs.org's docs index whatever was asked."""
    from types import SimpleNamespace

    from app.core.command.service import CommandService

    asked = {}

    async def research_web(question, depth="quick", category=None, time_range=None):
        asked.update(question=question, depth=depth)
        return {"ok": True, "report": "Plexecute calls itself an AI Life Execution Platform [1].", "pages_read": 3,
                "sources": [{"n": 1, "title": "Plexecute", "url": "https://plexecute.co.uk/"}]}

    async def fetch_url(url, render=None):
        raise AssertionError("no fixed page is fetched for a question")

    runtime = SimpleNamespace(research_web=research_web, fetch_url=fetch_url, workspace_id=None, task_id=None)
    answer, _, _, extra = _run(CommandService()._handle_research(
        None, runtime, "Do thorough research on plexecute.co.uk's competitors"))
    assert asked["depth"] == "deep" and "competitors" in asked["question"]
    assert answer.startswith("Plexecute calls itself") and "[1] Plexecute — https://plexecute.co.uk/" in answer
    assert "nodejs" not in answer and extra["research"]["pages_read"] == 3


def test_a_mission_can_read_another_missions_whole_report(monkeypatch):
    """The analysis of the Plexecute review could not find the review's report; agents can now read it."""
    from app.core.command.tool_runtime import ToolRuntime
    from app.core.runtime import lifecycle
    from app.models.task import Task

    report = "## Plexecute: organic-marketing briefing\n" + "Finding with https://plexecute.co.uk/ evidence. " * 300

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, None)
            done = Task(workspace_id=ws_id, title="Plexecute research", description="research", task_type="command",
                        status=lifecycle.COMPLETED, priority=5, result={"response": report, "report": {"rows": 2}})
            now = Task(workspace_id=ws_id, title="Analyse it", description="analyse", task_type="command",
                       status=lifecycle.RUNNING, priority=5)
            db.add_all([done, now])
            await db.commit()
            runtime = ToolRuntime(db, ws_id, now.id, operator="agent:research", authority_level=1, user_id=user_id)
            latest = await runtime.read_mission_report()
            by_id = await runtime.read_mission_report(str(done.id)[:8].upper())
            missing = await runtime.read_mission_report("ffffffff")
            return latest, by_id, missing, str(done.id)

    latest, by_id, missing, done_id = _run(run())
    assert latest["success"] and latest["task_id"] == done_id and latest["report"] == report  # whole, not cut
    assert by_id["task_id"] == done_id and missing["success"] is False
