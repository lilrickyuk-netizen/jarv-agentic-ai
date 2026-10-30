"""Behavior tests for persisted API credentials and webhook subscriptions."""
import asyncio
import hashlib
from uuid import uuid4, UUID

import pytest
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.tools.base import ToolConfig, ToolContext
from app.models.agent import Agent
from app.models.integrations import ApiCredential, WebhookEndpoint
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.api.keys import ApiKeyManageTool
from app.tools.api.webhook import WebhookListTool, WebhookRegisterTool, WebhookUnregisterTool
from app.tools.company.email import EmailReadTool, EmailSearchTool, EmailSendTool
from app.tools.company.slack import SlackReadTool, SlackSearchTool, SlackSendTool
from tests.conftest import AsyncTestingSessionLocal


def _approved_key_tool():
    return ApiKeyManageTool(ToolConfig(authority_level=AuthorityLevel.LEVEL_8_FINANCIAL))


async def _seed_scope(session):
    user_id, workspace_id, agent_id = uuid4(), uuid4(), uuid4()
    session.add(User(
        id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
        password_hash="test", is_active=True, is_admin=False,
    ))
    session.add(Workspace(
        id=workspace_id, owner_id=user_id, name="Credential scope", slug=f"credential-{workspace_id.hex[:8]}",
        description="", workspace_type="test", authority_level=8, is_active=True,
    ))
    session.add(Agent(
        id=agent_id, name="integration-agent", agent_type="research", workspace_id=workspace_id,
        is_active=True, authority_level=8, allowed_tools=[], blocked_tools=[], config={},
        model_provider="test", model_name="test",
    ))
    await session.commit()
    return ToolContext(
        user_id=user_id, workspace_id=workspace_id, agent_id=agent_id,
        db_session=session, approval_granted=True,
        approved_tools=["api_key_manage", "webhook_register"],
    )


@pytest.mark.integration
def test_api_keys_persist_only_hash_and_rotate_revoke_with_approval():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            context = await _seed_scope(session)
            tool = _approved_key_tool()
            created = await tool.execute({
                "action": "create", "service_name": "example",
                "description": "test credential", "scopes": ["read"],
            }, context)
            first_id = UUID(created.result_data["key_id"])
            first_key = created.result_data["key_value"]
            first_row = (await session.execute(
                select(ApiCredential).where(ApiCredential.id == first_id)
            )).scalar_one()
            listed = await tool.execute({"action": "list"}, context)
            rotated = await tool.execute({"action": "rotate", "key_id": str(first_id)}, context)
            second_id = UUID(rotated.result_data["key_id"])
            second_key = rotated.result_data["key_value"]
            second_row = (await session.execute(
                select(ApiCredential).where(ApiCredential.id == second_id)
            )).scalar_one()
            revoked = await tool.execute({"action": "revoke", "key_id": str(second_id)}, context)
            await session.flush()
            return first_key, first_row, listed, second_key, first_row.is_active, second_row, revoked

    first_key, first_row, listed, second_key, first_active, second_row, revoked = asyncio.run(run())
    assert first_key and second_key and first_key != second_key
    assert first_row.key_hash == hashlib.sha256(first_key.encode()).hexdigest()
    assert first_key not in first_row.key_hash
    assert listed.success is True and listed.result_data["count"] == 1
    assert first_active is False and second_row.is_active is False
    assert second_row.key_hash == hashlib.sha256(second_key.encode()).hexdigest()
    assert revoked.success is True


@pytest.mark.integration
def test_webhooks_persist_hashed_secret_and_scope_management():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            context = await _seed_scope(session)
            tool = WebhookRegisterTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS))
            secret = "webhook-signing-secret-123456"
            created = await tool.execute({
                "url": "https://hooks.example.test/jarv",
                "events": ["task.completed"],
                "description": "Task completion hook",
                "secret": secret,
                "headers": {"Authorization": "Bearer private-header"},
            }, context)
            webhook_id = UUID(created.result_data["webhook_id"])
            record = (await session.execute(select(WebhookEndpoint).where(
                WebhookEndpoint.id == webhook_id
            ))).scalar_one()
            listing = await WebhookListTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS)).run(
                    {"active_only": True, "event_filter": "task.completed"}, context)
            removed = await WebhookUnregisterTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).run(
                    {"webhook_id": str(webhook_id)}, context)
            await session.flush()
            return created, secret, record, listing, removed

    created, secret, record, listing, removed = asyncio.run(run())
    assert created.success is True
    assert created.result_data["delivery_enabled"] is False
    assert created.result_data["custom_headers_stored"] is False
    assert record.secret_hash == hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in record.secret_hash
    assert listing.success is True and listing.result_data["count"] == 1
    assert removed.success is True
    assert record.is_active is False


@pytest.mark.integration
def test_email_and_slack_tools_persist_scoped_redacted_drafts_only():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            context = await _seed_scope(session)
            secret = "sk-DRAFTSECRET123456789012345678"
            email = await EmailSendTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).execute({
                    "to": ["recipient@example.com"], "subject": "Review",
                    "body": f"Please review {secret} before the meeting.",
                    "attachments": [], "html": False,
                }, context)
            email_read = await EmailReadTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).run({
                    "folder": "drafts", "limit": 20, "unread_only": False,
                }, context)
            email_search = await EmailSearchTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).run({
                    "query": "Review", "limit": 20,
                }, context)
            slack = await SlackSendTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).execute({
                    "channel": "#launch", "text": f"Check this key {secret}",
                    "attachments": [], "blocks": [],
                }, context)
            slack_read = await SlackReadTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).run({
                    "channel": "#launch", "limit": 20,
                }, context)
            slack_search = await SlackSearchTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).run({
                    "query": "key", "limit": 20,
                }, context)
            return secret, email, email_read, email_search, slack, slack_read, slack_search

    secret, email, email_read, email_search, slack, slack_read, slack_search = asyncio.run(run())
    assert email.success is True and email.result_data["sent"] is False
    assert email.result_data["status"] == "draft"
    assert email_read.success is True and email_read.result_data["count"] == 1
    assert email_search.success is True and email_search.result_data["count"] == 1
    assert secret not in str(email_read.result_data)
    assert slack.success is True and slack.result_data["sent"] is False
    assert slack.result_data["status"] == "draft"
    assert slack_read.success is True and slack_read.result_data["count"] == 1
    assert slack_search.success is True and slack_search.result_data["count"] == 1
    assert secret not in str(slack_read.result_data)
