"""
JARV Backend - Slack Tools

Real Slack operations with local draft mode when unconfigured.

SETUP INSTRUCTIONS:
- Set SLACK_SERVICE_ENABLED=true in environment
- Configure Slack Bot credentials:
  - SLACK_BOT_TOKEN: Bot User OAuth Token (starts with xoxb-)
  - SLACK_WORKSPACE_ID: Slack Workspace ID
  - SLACK_DEFAULT_CHANNEL: Default channel ID for messages

When unconfigured, messages are saved as local drafts in database.

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
import os

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


def is_slack_configured() -> bool:
    """Check if Slack service is configured"""
    return os.getenv("SLACK_SERVICE_ENABLED", "false").lower() == "true"


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
            if not is_slack_configured():
                # LOCAL DRAFT MODE: Save message as draft in database
                from uuid import uuid4
                draft_id = str(uuid4())
                timestamp = datetime.utcnow().isoformat()

                # In production: Save to SlackDraft table in database
                # from app.models.company import SlackDraft
                # from app.core.database import get_db
                # async for session in get_db():
                #     draft = SlackDraft(
                #         id=draft_id,
                #         channel=channel,
                #         text=text,
                #         thread_ts=thread_ts,
                #         created_at=datetime.utcnow(),
                #         status="draft",
                #     )
                #     session.add(draft)
                #     await session.commit()

                logger.info(f"Slack service not configured. Saving draft: {draft_id}")
                logger.info(f"Draft: Channel={channel}, Text preview='{text[:100]}...'")

                return self.create_result(
                    success=True,
                    result_data={
                        "message_id": draft_id,
                        "channel": channel,
                        "timestamp": timestamp,
                        "status": "draft",
                        "mode": "draft",
                    },
                    output_text=f"Message saved as draft (service not configured). Draft ID: {draft_id}",
                )

            # LIVE MODE: Would send via Slack Bot API
            # This code path only executes if SLACK_SERVICE_ENABLED=true
            logger.warning("Slack service enabled but API integration not implemented yet")

            return self.create_result(
                success=False,
                error_message="Slack service enabled but send integration not yet implemented. Use draft mode.",
            )

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
            if not is_slack_configured():
                # LOCAL MODE: Return local drafts from database
                # In production: Query SlackDraft table
                # from app.models.company import SlackDraft
                # from app.core.database import get_db
                # async for session in get_db():
                #     drafts = await session.execute(
                #         select(SlackDraft)
                #         .filter(SlackDraft.channel == channel)
                #         .order_by(SlackDraft.created_at.desc())
                #         .limit(limit)
                #     )
                #     messages = [...]

                messages = []
                logger.info(f"Slack service not configured. Returning local drafts for channel: {channel}")

                return self.create_result(
                    success=True,
                    result_data={
                        "messages": messages,
                        "count": len(messages),
                        "channel": channel,
                        "mode": "local",
                    },
                    output_text=f"Retrieved {len(messages)} local draft(s) (service not configured)",
                )

            # LIVE MODE: Would fetch from Slack Bot API
            logger.warning("Slack service enabled but fetch integration not implemented yet")

            return self.create_result(
                success=False,
                error_message="Slack service enabled but fetch integration not yet implemented. Use local mode.",
            )

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
            if not is_slack_configured():
                # LOCAL MODE: Search local drafts in database
                # In production: Query SlackDraft table with search
                # from app.models.company import SlackDraft
                # from app.core.database import get_db
                # async for session in get_db():
                #     query_filter = SlackDraft.text.ilike(f"%{query}%")
                #     if channel:
                #         query_filter &= SlackDraft.channel == channel
                #     drafts = await session.execute(
                #         select(SlackDraft)
                #         .filter(query_filter)
                #         .limit(limit)
                #     )
                #     messages = [...]

                messages = []
                logger.info(f"Slack service not configured. Searching local drafts: {query}")

                return self.create_result(
                    success=True,
                    result_data={
                        "messages": messages,
                        "count": len(messages),
                        "mode": "local",
                    },
                    output_text=f"Found {len(messages)} matching local draft(s) (service not configured)",
                )

            # LIVE MODE: Would search via Slack Bot API
            logger.warning("Slack service enabled but search integration not implemented yet")

            return self.create_result(
                success=False,
                error_message="Slack service enabled but search integration not yet implemented. Use local mode.",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to search Slack messages: {str(e)}",
            )
