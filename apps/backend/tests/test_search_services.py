"""
JAI's web search asks search services with a free monthly allowance first (Richard, 10 November: every engine his
SearXNG asked had blocked his home connection, Bing searched only the first word, and two list missions came back
nearly empty). Exa, then Tavily, then SearXNG and DuckDuckGo; a service that has used its allowance, had its key
turned down or is limiting requests is skipped for a while. Real: the internet module and Redis. Outgoing HTTP goes
to an httpx MockTransport; nothing reaches a search service and no allowance is spent.
"""
import asyncio
import json

import httpx
import pytest

from app.core import internet
from app.core.config import settings
from tests.test_web_research import searx_payload, web  # noqa: F401


def _run(coro):
    return asyncio.run(coro)


EXA = {"results": [{"title": "Top UK fitness YouTubers", "url": "https://lists.example.co.uk/uk-fitness",
                    "publishedDate": "2026-09-01T00:00:00.000Z", "author": "Jo"},
                   {"title": "Not a page", "url": "mailto:x@y"}]}
TAVILY = {"results": [{"title": "Write for us", "url": "https://blog.example.com/write-for-us",
                       "content": "We accept free guest posts on habits.", "published_date": "2026-10-01"}],
          "answer": "Several blogs accept guest posts."}


@pytest.fixture
def services(web, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "EXA_API_KEY", "exa-test-key")
    monkeypatch.setattr(settings, "TAVILY_API_KEY", "tavily-test-key")
    monkeypatch.setattr(settings, "SEARCH_ORDER", "exa,tavily,searxng")

    async def wake():
        from app.core.redis import get_redis

        redis = await get_redis()
        for name in ("exa", "tavily"):
            await redis.delete(internet._RESTING + name)

    _run(wake())
    web["routes"]["https://api.exa.ai/search"] = lambda r: httpx.Response(200, json=EXA)
    web["routes"]["https://api.tavily.com/search"] = lambda r: httpx.Response(200, json=TAVILY)
    web["routes"]["http://searxng:8080/search"] = lambda r: httpx.Response(200, json=searx_payload("gov"))
    return web


def _sent(web, prefix):
    return [r for r in web["requests"] if str(r.url).startswith(prefix)]


def test_exa_answers_first_with_its_key_and_says_so(services):
    found = _run(internet.web_search("UK fitness YouTubers", 5, None, "month"))
    assert found["ok"] and found["source"] == "exa"
    assert [r["url"] for r in found["results"]] == ["https://lists.example.co.uk/uk-fitness"]
    assert found["results"][0]["engines"] == ["exa"] and found["results"][0]["published"].startswith("2026-09-01")
    request = _sent(services, "https://api.exa.ai")[0]
    body = json.loads(request.content)
    assert request.headers["x-api-key"] == "exa-test-key" and body["numResults"] == 5
    assert body["query"] == "UK fitness YouTubers" and "startPublishedDate" in body and "contents" not in body
    assert not _sent(services, "https://api.tavily.com") and not _sent(services, "http://searxng")


def test_a_used_allowance_moves_to_tavily_and_exa_rests(services):
    services["routes"]["https://api.exa.ai/search"] = lambda r: httpx.Response(
        402, json={"error": "You have exceeded your credits limit"})
    found = _run(internet.web_search("productivity blogs write for us", 5, "news"))
    assert found["source"] == "tavily" and found["results"][0]["url"] == "https://blog.example.com/write-for-us"
    assert found["answers"] == ["Several blogs accept guest posts."] and "exa" in found["skipped"]
    body = json.loads(_sent(services, "https://api.tavily.com")[0].content)
    assert body["search_depth"] == "basic" and body["topic"] == "news"
    assert _sent(services, "https://api.tavily.com")[0].headers["authorization"] == "Bearer tavily-test-key"
    # The next search does not pay a failed request to Exa.
    asked_exa = len(_sent(services, "https://api.exa.ai"))
    again = _run(internet.web_search("habit app partner programme", 5))
    assert again["source"] == "tavily" and len(_sent(services, "https://api.exa.ai")) == asked_exa
    assert "resting" in again["skipped"]["exa"]


def test_when_both_are_out_searxng_still_answers(services):
    services["routes"]["https://api.exa.ai/search"] = lambda r: httpx.Response(401, text="invalid api key")
    services["routes"]["https://api.tavily.com/search"] = lambda r: httpx.Response(429, text="slow down")
    found = _run(internet.web_search("UK fitness YouTubers", 5))
    assert found["source"] == "searxng" and set(found["skipped"]) == {"exa", "tavily"}


def test_a_service_with_no_key_is_never_asked(services, monkeypatch):
    monkeypatch.setattr(settings, "EXA_API_KEY", "")
    found = _run(internet.web_search("UK fitness YouTubers", 5))
    assert found["source"] == "tavily" and not _sent(services, "https://api.exa.ai")
    assert "skipped" not in found
