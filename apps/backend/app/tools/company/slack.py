"""
JARV Backend - Slack Tools

Real Slack operations with local draft mode when unconfigured.

SETUP INSTRUCTIONS:
- SLACK_BOT_TOKEN: Bot User OAuth Token (starts with xoxb-). Setting it switches Slack on.
- SLACK_USER_TOKEN (optional, starts with xoxp-): Slack only allows message search with a user
  token. Without it, slack_search searches the recent history of a named channel with the bot.

Sending always waits for Richard's approval. Without a bot token, messages are saved as local
drafts in the database and nothing is sent. The Settings page checks the token (auth.test).

Slack Bot Setup:
1. Go to https://api.slack.com/apps
2. Create a new app or select existing
3. Enable Bot Token Scopes: chat:write, channels:read, channels:history, users:read
4. Install app to workspace
5. Copy Bot User OAuth Token to SLACK_BOT_TOKEN
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import logging
from uuid import UUID, uuid4
from sqlalchemy import or_, select
import httpx

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.core.security import redact_secrets
from app.tools.memory.storage import _memory_scope
from app.models.integrations import OutboundMessageDraft

logger = logging.getLogger(__name__)


def _token(name: str) -> Optional[str]:
    from app.core.ops.connections import value

    return value(name)


def is_slack_configured() -> bool:
    """Slack is on when a bot token is set."""
    return bool(_token("SLACK_BOT_TOKEN"))


async def _slack_api_request(method: str, payload: Dict[str, Any], *, token: Optional[str] = None) -> Dict[str, Any]:
    """Call a Slack Web API method with the bot token (or the given token)."""
    token = token or _token("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set SLACK_BOT_TOKEN to use Slack")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"https://slack.com/api/{method}",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        result = response.json()

    if not isinstance(result, dict) or result.get("ok") is not True:
        error_code = result.get("error", "invalid_response") if isinstance(result, dict) else "invalid_response"
        raise RuntimeError(f"Slack API {method} failed: {error_code}")
    return result


# ===== SLACK SEND TOOL =====

class SlackSendInput(BaseModel):
    """Input schema for Slack send tool"""
    channel: str = Field(..., min_length=1, description="Channel ID or name (e.g., #general, C1234567890)")
    text: str = Field(..., min_length=1, max_length=40000, description="Message text (supports Slack markdown)")
    thread_ts: Optional[str] = Field(None, description="Thread timestamp to reply to")
    attachments: Optional[List[Dict[str, Any]]] = Field(None, description="Message attachments")
    blocks: Optional[List[Dict[str, Any]]] = Field(None, description="Message blocks (rich formatting)")


class SlackSendOutput(BaseModel):
    """Output schema for Slack send tool"""
    message_id: str = Field(..., description="Message ID or draft ID")
    channel: str = Field(..., description="Channel ID")
    timestamp: str = Field(..., description="Message timestamp")
    status: str = Field(..., description="Status: sent, draft, failed")
    mode: str = Field(..., description="Mode: live, draft")


class SlackSendTool(ToolBase):
    """Tool for sending Slack messages (or saving as drafts when unconfigured)"""

    @property
    def name(self) -> str:
        return "slack_send"

    @property
    def description(self) -> str:
        return "Send Slack message to channel. Saves as draft when Slack service not configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return SlackSendInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return SlackSendOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True  # Sending Slack messages requires approval

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute Slack send or save as draft"""
        channel = input_data["channel"]
        text = input_data["text"]
        thread_ts = input_data.get("thread_ts")

        try:
            if is_slack_configured():
                response = await _slack_api_request("chat.postMessage", {
                    "channel": channel,
                    "text": redact_secrets(text),
                    **({"thread_ts": thread_ts} if thread_ts else {}),
                    **({"attachments": input_data["attachments"]} if input_data.get("attachments") else {}),
                    **({"blocks": input_data["blocks"]} if input_data.get("blocks") else {}),
                })
                return self.create_result(
                    success=True,
                    result_data={
                        "message_id": response.get("ts", ""),
                        "channel": response.get("channel", channel),
                        "timestamp": response.get("ts", ""),
                        "status": "sent", "mode": "live", "sent": True,
                    },
                    output_text=f"Slack accepted message {response.get('ts', '')} in {response.get('channel', channel)}",
                )
            if not self._has_approval(context):
                return self.create_result(success=False, requires_approval=True,
                    error_message="Slack draft creation requires an explicit approved execution context.")
            db, agent_id = await _memory_scope(context)
            draft = OutboundMessageDraft(
                id=uuid4(), owner_id=UUID(str(context.user_id)),
                workspace_id=UUID(str(context.workspace_id)), agent_id=agent_id,
                channel_type="slack", destination=channel,
                body=redact_secrets(text), thread_reference=thread_ts,
                meta_data={
                    "attachments": redact_secrets(input_data.get("attachments") or []),
                    "blocks": redact_secrets(input_data.get("blocks") or []),
                },
                status="draft",
            )
            db.add(draft)
            await db.flush()
            timestamp = draft.created_at.isoformat()
            return self.create_result(
                success=True,
                result_data={
                    "message_id": str(draft.id), "channel": channel,
                    "timestamp": timestamp, "status": "draft", "mode": "draft",
                    "sent": False, "setup": "Set SLACK_BOT_TOKEN to send to Slack.",
                    "limitations": ["Slack is not set up; this record is only a saved draft."],
                },
                output_text=f"Saved Slack draft {draft.id}; no message was sent.",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to process Slack message: {str(e)}",
            )


# ===== SLACK READ TOOL =====

class SlackReadInput(BaseModel):
    """Input schema for Slack read tool"""
    channel: str = Field(..., description="Channel ID or name to read from")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum messages to retrieve")
    oldest: Optional[str] = Field(None, description="Oldest timestamp to fetch (ISO format or Slack timestamp)")
    latest: Optional[str] = Field(None, description="Latest timestamp to fetch (ISO format or Slack timestamp)")


class SlackMessageInfo(BaseModel):
    """Slack message information"""
    message_id: str = Field(..., description="Message ID or timestamp")
    user: str = Field(..., description="User ID or name")
    text: str = Field(..., description="Message text")
    timestamp: str = Field(..., description="Message timestamp")
    thread_ts: Optional[str] = Field(None, description="Thread parent timestamp")
    reactions: List[str] = Field(default_factory=list, description="Reaction emojis")


class SlackReadOutput(BaseModel):
    """Output schema for Slack read tool"""
    messages: List[SlackMessageInfo] = Field(..., description="List of messages")
    count: int = Field(..., description="Number of messages retrieved")
    channel: str = Field(..., description="Channel ID")
    mode: str = Field(..., description="Mode: live, local")


class SlackReadTool(ToolBase):
    """Tool for reading Slack messages (local mode when unconfigured)"""

    @property
    def name(self) -> str:
        return "slack_read"

    @property
    def description(self) -> str:
        return "Read Slack messages from channel. Returns local drafts when Slack service not configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return SlackReadInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return SlackReadOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute Slack read"""
        channel = input_data["channel"]
        limit = input_data["limit"]

        try:
            if is_slack_configured():
                response = await _slack_api_request("conversations.history", {
                    "channel": channel,
                    "limit": limit,
                    **({"oldest": input_data["oldest"]} if input_data.get("oldest") else {}),
                    **({"latest": input_data["latest"]} if input_data.get("latest") else {}),
                })
                messages = [{
                    "message_id": item.get("ts", ""),
                    "user": item.get("user", "unknown"),
                    "text": item.get("text", ""),
                    "timestamp": item.get("ts", ""),
                    "thread_ts": item.get("thread_ts"),
                    "reactions": [reaction.get("name", "") for reaction in item.get("reactions", [])],
                } for item in response.get("messages", [])]
                return self.create_result(
                    success=True,
                    result_data={"messages": messages, "count": len(messages),
                                 "channel": response.get("channel", channel), "mode": "live"},
                    output_text=f"Retrieved {len(messages)} Slack message(s) from {channel}",
                )
            db, agent_id = await _memory_scope(context)
            rows = (await db.execute(select(OutboundMessageDraft).where(
                OutboundMessageDraft.owner_id == UUID(str(context.user_id)),
                OutboundMessageDraft.workspace_id == UUID(str(context.workspace_id)),
                OutboundMessageDraft.agent_id == agent_id,
                OutboundMessageDraft.channel_type == "slack",
                OutboundMessageDraft.destination == channel,
                OutboundMessageDraft.status == "draft",
            ).order_by(OutboundMessageDraft.created_at.desc()).limit(limit))).scalars().all()
            messages = [{
                "message_id": str(row.id), "user": "local-draft", "text": row.body,
                "timestamp": row.created_at.isoformat(), "thread_ts": row.thread_reference,
                "reactions": [],
            } for row in rows]
            return self.create_result(
                success=True,
                result_data={"messages": messages, "count": len(messages), "channel": channel, "mode": "local_drafts"},
                output_text=f"Retrieved {len(messages)} saved draft(s); no Slack channel was queried.",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to read Slack messages: {str(e)}",
            )


# ===== SLACK SEARCH TOOL =====

class SlackSearchInput(BaseModel):
    """Input schema for Slack search tool"""
    query: str = Field(..., min_length=1, description="Search query")
    channel: Optional[str] = Field(None, description="Filter by channel (None = all channels)")
    from_user: Optional[str] = Field(None, description="Filter by user ID")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results")
    sort: str = Field(default="timestamp", description="Sort by: timestamp, relevance")


class SlackSearchOutput(BaseModel):
    """Output schema for Slack search tool"""
    messages: List[SlackMessageInfo] = Field(..., description="Matching messages")
    count: int = Field(..., description="Number of matches")
    mode: str = Field(..., description="Mode: live, local")


class SlackSearchTool(ToolBase):
    """Tool for searching Slack messages (local mode when unconfigured)"""

    @property
    def name(self) -> str:
        return "slack_search"

    @property
    def description(self) -> str:
        return "Search Slack messages by query. Searches local drafts when Slack service not configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return SlackSearchInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return SlackSearchOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute Slack search"""
        query = input_data["query"]
        channel = input_data.get("channel")
        limit = input_data["limit"]

        try:
            user_token = _token("SLACK_USER_TOKEN")
            if is_slack_configured() and not user_token:
                if not channel:
                    return self.create_result(success=False, error_message=(
                        "Slack only allows workspace-wide search with a user token: set SLACK_USER_TOKEN, or name a "
                        "channel to search its recent history."))
                response = await _slack_api_request("conversations.history", {"channel": channel.lstrip("#"),
                                                                              "limit": 200})
                needle = query.lower()
                found = [item for item in response.get("messages", [])
                         if needle in (item.get("text") or "").lower()
                         and (not input_data.get("from_user") or item.get("user") == input_data["from_user"])]
                messages = [{
                    "message_id": item.get("ts", ""), "user": item.get("user", "unknown"),
                    "text": item.get("text", ""), "timestamp": item.get("ts", ""),
                    "thread_ts": item.get("thread_ts"),
                    "reactions": [reaction.get("name", "") for reaction in item.get("reactions", [])],
                } for item in found[:limit]]
                return self.create_result(
                    success=True,
                    result_data={"messages": messages, "count": len(messages), "mode": "live_channel_history"},
                    output_text=f"Found {len(messages)} message(s) in the last 200 of {channel}",
                )
            if is_slack_configured():
                search_query = query
                if channel:
                    search_query += f" in:{channel.lstrip('#')}"
                if input_data.get("from_user"):
                    search_query += f" from:{input_data['from_user']}"
                page_size = min(limit, 100)
                page = 1
                matches = []
                total = 0
                while len(matches) < limit:
                    response = await _slack_api_request("search.messages", {
                        "query": search_query,
                        "count": min(page_size, limit - len(matches)),
                        "page": page,
                        "sort": "timestamp" if input_data.get("sort") == "timestamp" else "score",
                    }, token=user_token)
                    result = response.get("messages", {})
                    page_matches = result.get("matches", [])
                    total = result.get("total", len(page_matches))
                    matches.extend(page_matches)
                    if not page_matches or len(matches) >= total or len(page_matches) < page_size:
                        break
                    page += 1
                messages = [{
                    "message_id": item.get("ts", ""),
                    "user": item.get("user", "unknown"),
                    "text": item.get("text", ""),
                    "timestamp": item.get("ts", ""),
                    "thread_ts": item.get("thread_ts"),
                    "reactions": [reaction.get("name", "") for reaction in item.get("reactions", [])],
                } for item in matches[:limit]]
                return self.create_result(
                    success=True,
                    result_data={"messages": messages, "count": len(messages), "mode": "live"},
                    output_text=f"Found {len(messages)} Slack message(s) for the query",
                )
            db, agent_id = await _memory_scope(context)
            stmt = select(OutboundMessageDraft).where(
                OutboundMessageDraft.owner_id == UUID(str(context.user_id)),
                OutboundMessageDraft.workspace_id == UUID(str(context.workspace_id)),
                OutboundMessageDraft.agent_id == agent_id,
                OutboundMessageDraft.channel_type == "slack",
                OutboundMessageDraft.status == "draft",
                OutboundMessageDraft.body.ilike(f"%{query}%"),
            )
            if channel:
                stmt = stmt.where(OutboundMessageDraft.destination == channel)
            rows = (await db.execute(stmt.order_by(OutboundMessageDraft.created_at.desc()).limit(limit))).scalars().all()
            messages = [{
                "message_id": str(row.id), "user": "local-draft", "text": row.body,
                "timestamp": row.created_at.isoformat(), "thread_ts": row.thread_reference,
                "reactions": [],
            } for row in rows]
            return self.create_result(
                success=True,
                result_data={"messages": messages, "count": len(messages), "mode": "local_drafts"},
                output_text=f"Found {len(messages)} saved draft(s); no Slack workspace was queried.",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to search Slack messages: {str(e)}",
            )
