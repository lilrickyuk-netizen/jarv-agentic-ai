"""Behavioral tests for local calendar event persistence."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4, UUID

import pytest
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.tools.base import ToolConfig, ToolContext
from app.models.agent import Agent
from app.models.integrations import CalendarEvent
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.company.calendar import (
    CalendarCreateEventTool,
    CalendarDeleteEventTool,
    CalendarListEventsTool,
    CalendarUpdateEventTool,
)
from tests.conftest import AsyncTestingSessionLocal


def _calendar_tool(tool_class):
    return tool_class(ToolConfig(authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS))


@pytest.mark.integration
def test_calendar_create_list_update_delete_use_persisted_workspace_events():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            user_id, workspace_id, agent_id = uuid4(), uuid4(), uuid4()
            session.add(User(
                id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="test", is_active=True, is_admin=False,
            ))
            session.add(Workspace(
                id=workspace_id, owner_id=user_id, name="Calendar scope",
                slug=f"calendar-{workspace_id.hex[:8]}", description="",
                workspace_type="test", authority_level=5, is_active=True,
            ))
            session.add(Agent(
                id=agent_id, name="calendar-agent", agent_type="company_operator",
                workspace_id=workspace_id, is_active=True, authority_level=5,
                allowed_tools=[], blocked_tools=[], config={}, model_provider="test", model_name="test",
            ))
            await session.commit()
            context = ToolContext(
                user_id=user_id, workspace_id=workspace_id, agent_id=agent_id,
                db_session=session, approval_granted=True,
                approved_tools=["calendar_create_event", "calendar_update_event", "calendar_delete_event"],
            )
            created = await _calendar_tool(CalendarCreateEventTool).execute({
                "title": "Project review",
                "start_time": "2026-10-22T10:00:00+00:00",
                "end_time": "2026-10-22T11:00:00+00:00",
                "location": "Remote", "attendees": ["owner@example.test"],
            }, context)
            event_id = UUID(created.result_data["event_id"])
            listed = await _calendar_tool(CalendarListEventsTool).run({
                "start_date": "2026-10-22T00:00:00+00:00",
                "end_date": "2026-10-23T00:00:00+00:00",
                "limit": 10,
            }, context)
            updated = await _calendar_tool(CalendarUpdateEventTool).execute({
                "event_id": str(event_id), "title": "Project review updated",
            }, context)
            event = (await session.execute(
                select(CalendarEvent).where(CalendarEvent.id == event_id)
            )).scalar_one()
            deleted = await _calendar_tool(CalendarDeleteEventTool).execute({
                "event_id": str(event_id),
            }, context)
            await session.flush()
            return created, listed, updated, event, deleted

    created, listed, updated, event, deleted = asyncio.run(run())
    assert created.success is True and created.result_data["mode"] == "local"
    assert listed.success is True and listed.result_data["count"] == 1
    assert updated.success is True and event.title == "Project review updated"
    assert deleted.success is True and event.is_active is False