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
        assert request.headers["Authorization"] == "Bearer test-slack-token"
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
    monkeypatch.setenv("SLACK_SERVICE_ENABLED", "true")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "test-slack-token")
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


def test_slack_enabled_without_token_fails_explicitly(monkeypatch):
    monkeypatch.setenv("SLACK_SERVICE_ENABLED", "true")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    context = ToolContext(
        user_id=uuid4(), workspace_id=uuid4(), approval_granted=True,
        approved_tools=["slack_send"],
    )

    result = asyncio.run(_tool(SlackSendTool).run({
        "channel": "C123", "text": "Deploy complete",
    }, context))

    assert result.success is False
    assert "SLACK_BOT_TOKEN is required" in result.error_message
    assert result.result_data.get("sent") is not True