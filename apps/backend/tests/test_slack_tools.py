"""Behavioral tests for authenticated Slack Web API operations."""
import asyncio
import json
from uuid import uuid4

import httpx

from app.core.agents.base import AuthorityLevel
from app.core.tools.base import ToolConfig, ToolContext
from app.tools.company.slack import SlackReadTool, SlackSearchTool, SlackSendTool


def _tool(tool_class):
    return tool_class(ToolConfig(authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS))


def test_slack_provider_tools_use_authenticated_web_api(monkeypatch):
    calls = []

    def handle_request(request):
        assert request.url.host == "slack.com"
        expected = "test-slack-user-token" if request.url.path == "/api/search.messages" else "test-slack-token"
        assert request.headers["Authorization"] == f"Bearer {expected}"  # search needs the user token
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))

        if request.url.path == "/api/chat.postMessage":
            return httpx.Response(200, json={"ok": True, "channel": "C123", "ts": "1710000000.000001"})
        if request.url.path == "/api/conversations.history":
            return httpx.Response(200, json={
                "ok": True, "channel": "C123",
                "messages": [{"user": "U1", "text": "status", "ts": "1710000000.000002",
                              "thread_ts": "1710000000.000000",
                              "reactions": [{"name": "white_check_mark"}] }],
            })
        if request.url.path == "/api/search.messages":
            return httpx.Response(200, json={
                "ok": True,
                "messages": {"total": 1, "matches": [{"user": "U1", "text": "status",
                    "ts": "1710000000.000002", "thread_ts": "1710000000.000000"}]},
            })
        raise AssertionError(f"Unexpected Slack API method: {request.url.path}")

    actual_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: actual_client(
        transport=httpx.MockTransport(handle_request), **kwargs
    ))
    monkeypatch.setenv("SLACK_BOT_TOKEN", "test-slack-token")
    monkeypatch.setenv("SLACK_USER_TOKEN", "test-slack-user-token")
    context = ToolContext(
        user_id=uuid4(), workspace_id=uuid4(), approval_granted=True,
        approved_tools=["slack_send"],
    )

    async def run_tools():
        sent = await _tool(SlackSendTool).run({
            "channel": "C123", "text": "Deploy complete", "thread_ts": "1710000000.000000",
        }, context)
        read = await _tool(SlackReadTool).run({
            "channel": "C123", "limit": 20, "oldest": "1710000000.000000",
        }, context)
        searched = await _tool(SlackSearchTool).run({
            "query": "status", "channel": "#general", "from_user": "U1",
            "limit": 20, "sort": "relevance",
        }, context)
        return sent, read, searched

    sent, read, searched = asyncio.run(run_tools())

    assert sent.success is True
    assert sent.result_data["sent"] is True and sent.result_data["mode"] == "live"
    assert read.success is True and read.result_data["messages"][0]["reactions"] == ["white_check_mark"]
    assert searched.success is True and searched.result_data["messages"][0]["user"] == "U1"
    assert calls == [
        ("/api/chat.postMessage", {
            "channel": "C123", "text": "Deploy complete", "thread_ts": "1710000000.000000",
        }),
        ("/api/conversations.history", {
            "channel": "C123", "limit": 20, "oldest": "1710000000.000000",
        }),
        ("/api/search.messages", {
            "query": "status in:general from:U1", "count": 20,
            "page": 1, "sort": "score",
        }),
    ]


def test_bot_token_search_uses_channel_history_and_needs_a_channel(monkeypatch):
    calls = []

    def handle_request(request):
        calls.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer test-slack-token"
        return httpx.Response(200, json={"ok": True, "messages": [
            {"user": "U1", "text": "Deploy finished OK", "ts": "1.1"}, {"user": "U2", "text": "lunch?", "ts": "1.2"}]})

    actual_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: actual_client(
        transport=httpx.MockTransport(handle_request), **kwargs))
    monkeypatch.setenv("SLACK_BOT_TOKEN", "test-slack-token")
    monkeypatch.delenv("SLACK_USER_TOKEN", raising=False)
    context = ToolContext(user_id=uuid4(), workspace_id=uuid4())

    async def run():
        found = await _tool(SlackSearchTool).run({"query": "deploy", "channel": "#ops", "limit": 20}, context)
        nowhere = await _tool(SlackSearchTool).run({"query": "deploy", "limit": 20}, context)
        return found, nowhere

    found, nowhere = asyncio.run(run())
    assert found.success and found.result_data["mode"] == "live_channel_history"
    assert [m["text"] for m in found.result_data["messages"]] == ["Deploy finished OK"]
    assert nowhere.success is False and "SLACK_USER_TOKEN" in nowhere.error_message
    assert calls == ["/api/conversations.history"]


def test_without_a_bot_token_nothing_reaches_slack(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no request")))
    from app.tools.company.slack import is_slack_configured

    assert is_slack_configured() is False
    context = ToolContext(user_id=uuid4(), workspace_id=uuid4(), approval_granted=True, approved_tools=["slack_send"])
    result = asyncio.run(_tool(SlackSendTool).run({"channel": "C123", "text": "Deploy complete"}, context))
    assert result.result_data.get("sent") is not True
