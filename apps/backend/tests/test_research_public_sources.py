"""Tests for unauthenticated, read-only public-source research."""
import asyncio
import httpx

from app.core.research.public_search import search_public_sources


def test_public_search_fetches_posts_and_retains_cc_by_sa_attribution(monkeypatch):
    requests = []

    def respond(request):
        assert request.url.host == "api.stackexchange.com"
        assert request.url.path == "/2.3/search/advanced"
        requests.append(request)
        params = request.url.params
        assert params["site"] == "stackoverflow"
        assert params["filter"] == "withbody"
        return httpx.Response(200, json={"items": [{
            "title": "API authorization review",
            "link": "https://stackoverflow.com/questions/123/api-auth",
            "body": "<p>Check <b>object-level authorization</b> for each identifier.</p>",
            "content_license": "CC BY-SA 4.0",
            "owner": {"display_name": "Researcher", "link": "https://stackoverflow.com/users/5/researcher"},
            "score": 5,
            "answer_count": 2,
            "creation_date": 1792490400,
        }]})

    actual_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: actual_client(
        transport=httpx.MockTransport(respond), **kwargs,
    ))

    sources = asyncio.run(search_public_sources("API authorization", limit=2))

    assert len(sources) == 1
    assert sources[0]["title"] == "API authorization review"
    assert sources[0]["url"] == "https://stackoverflow.com/questions/123/api-auth"
    assert sources[0]["publisher"] == "Stack Overflow"
    assert sources[0]["license"] == "CC BY-SA 4.0"
    assert sources[0]["author"] == "Researcher"
    assert sources[0]["author_url"] == "https://stackoverflow.com/users/5/researcher"
    assert "object-level authorization" in sources[0]["content"]
    assert sources[0]["score"] == 5
    assert sources[0]["answer_count"] == 2
    assert sources[0]["page_created_at"]
    assert sources[0]["retrieved_at"]
    assert len(requests) == 1


def test_public_search_rejects_posts_without_attribution_license(monkeypatch):
    def handle(request):
        return httpx.Response(200, json={"items": [{
            "title": "Unlicensed result",
            "link": "https://stackoverflow.com/questions/123/unlicensed",
            "body": "Question excerpt",
            "content_license": "",
        }]})

    actual_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: actual_client(
        transport=httpx.MockTransport(handle), **kwargs,
    ))
    assert asyncio.run(search_public_sources("authorization")) == []


def test_public_search_broadens_specific_queries_when_exact_terms_miss(monkeypatch):
    queries = []

    def handle(request):
        query = request.url.params["q"]
        queries.append(query)
        if len(queries) == 1:
            return httpx.Response(200, json={"items": []})
        return httpx.Response(200, json={"items": [{
            "title": "API authorization",
            "link": "https://stackoverflow.com/questions/123/api-auth",
            "body": "A licensed excerpt.",
            "content_license": "CC BY-SA 4.0",
            "owner": {"display_name": "Researcher", "link": "https://stackoverflow.com/users/5/researcher"},
        }]})

    actual_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: actual_client(
        transport=httpx.MockTransport(handle), **kwargs,
    ))
    sources = asyncio.run(search_public_sources(
        "API object authorization and SSRF controls",
    ))

    assert queries == [
        "API object authorization and SSRF controls",
        "API object authorization SSRF",
    ]
    assert len(sources) == 1


def test_public_search_empty_query_does_not_issue_network_request(monkeypatch):
    def unexpected_client(**kwargs):
        raise AssertionError("empty queries must not issue requests")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected_client)
    assert asyncio.run(search_public_sources("   ")) == []
