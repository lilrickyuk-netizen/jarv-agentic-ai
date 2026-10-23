"""
JARV Backend - Calendar Tools

Real calendar operations with local event storage when unconfigured.

SETUP INSTRUCTIONS:
- Set CALENDAR_SERVICE_ENABLED=true in environment
- Configure calendar service credentials:
  - Google Calendar: GOOGLE_CALENDAR_API_KEY, GOOGLE_CALENDAR_ID
  - Microsoft Graph: MICROSOFT_GRAPH_CLIENT_ID, MICROSOFT_GRAPH_CLIENT_SECRET
  - CalDAV: CALDAV_URL, CALDAV_USERNAME, CALDAV_PASSWORD

When unconfigured, events are stored locally in database (CalendarEvent table).
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import logging
import os
from uuid import UUID, uuid4
from sqlalchemy import select

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.tools.memory.storage import _memory_scope
from app.models.integrations import CalendarEvent

logger = logging.getLogger(__name__)


def is_calendar_configured() -> bool:
    """Check if calendar service is configured"""
    return os.getenv("CALENDAR_SERVICE_ENABLED", "false").lower() == "true"


# ===== CALENDAR CREATE EVENT TOOL =====

class CalendarCreateEventInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="Event title")
    start_time: str = Field(..., description="Start time (ISO format)")
    end_time: str = Field(..., description="End time (ISO format)")
    description: Optional[str] = Field(None, description="Event description")
    location: Optional[str] = Field(None, description="Event location")
    attendees: Optional[List[str]] = Field(None, description="Attendee email addresses")
    reminders: Optional[List[int]] = Field(None, description="Reminder minutes before event")


class CalendarCreateEventOutput(BaseModel):
    event_id: str
    title: str
    start_time: str
    mode: str = Field(..., description="Mode: live, local")
    status: str


class CalendarCreateEventTool(ToolBase):
    @property
    def name(self) -> str:
        return "calendar_create_event"

    @property
    def description(self) -> str:
        return "Create calendar event. Stores locally when calendar service not configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CalendarCreateEventInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CalendarCreateEventOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True  # Creating calendar events requires approval

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        title = input_data["title"]
        start_time = input_data["start_time"]
        end_time = input_data["end_time"]

        try:
            start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            if end <= start:
                return self.create_result(success=False, error_message="Event end_time must be after start_time")
            if is_calendar_configured():
                return self.create_result(success=False, error_message="External calendar sync is enabled but no provider adapter is configured")
            db, agent_id = await _memory_scope(context)
            event = CalendarEvent(
                id=uuid4(), owner_id=UUID(str(context.user_id)),
                workspace_id=UUID(str(context.workspace_id)), agent_id=agent_id,
                title=title, description=input_data.get("description"),
                start_time=start, end_time=end, location=input_data.get("location"),
                attendees=input_data.get("attendees") or [],
                reminders=input_data.get("reminders") or [], is_active=True,
            )
            db.add(event)
            await db.flush()
            return self.create_result(
                success=True,
                result_data={
                    "event_id": str(event.id), "title": title,
                    "start_time": event.start_time.isoformat(), "mode": "local",
                    "status": "created_local",
                },
                output_text=f"Event persisted locally: {event.id}",
            )

        except ValueError as e:
            return self.create_result(
                success=False,
                error_message=f"Invalid datetime format: {str(e)}. Use ISO format (YYYY-MM-DDTHH:MM:SS)",
            )
        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to create event: {str(e)}")


# ===== CALENDAR LIST EVENTS TOOL =====

class CalendarListEventsInput(BaseModel):
    start_date: Optional[str] = Field(None, description="Start date filter (ISO format)")
    end_date: Optional[str] = Field(None, description="End date filter (ISO format)")
    limit: int = Field(default=100, ge=1, le=500, description="Maximum events")


class EventInfo(BaseModel):
    event_id: str
    title: str
    start_time: str
    end_time: str
    location: Optional[str]
    attendees: List[str]


class CalendarListEventsOutput(BaseModel):
    events: List[EventInfo]
    count: int
    mode: str


class CalendarListEventsTool(ToolBase):
    @property
    def name(self) -> str:
        return "calendar_list_events"

    @property
    def description(self) -> str:
        return "List calendar events. Returns local events when calendar service not configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CalendarListEventsInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CalendarListEventsOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        limit = input_data["limit"]

        try:
            if is_calendar_configured():
                return self.create_result(success=False, error_message="External calendar sync is enabled but no provider adapter is configured")
            db, agent_id = await _memory_scope(context)
            stmt = select(CalendarEvent).where(
                CalendarEvent.owner_id == UUID(str(context.user_id)),
                CalendarEvent.workspace_id == UUID(str(context.workspace_id)),
                CalendarEvent.agent_id == agent_id, CalendarEvent.is_active.is_(True),
            )
            if input_data.get("start_date"):
                start_filter = datetime.fromisoformat(input_data["start_date"].replace("Z", "+00:00"))
                stmt = stmt.where(CalendarEvent.start_time >= start_filter)
            if input_data.get("end_date"):
                end_filter = datetime.fromisoformat(input_data["end_date"].replace("Z", "+00:00"))
                stmt = stmt.where(CalendarEvent.start_time <= end_filter)
            rows = (await db.execute(stmt.order_by(CalendarEvent.start_time).limit(limit))).scalars().all()
            events = [{
                "event_id": str(event.id), "title": event.title,
                "start_time": event.start_time.isoformat(), "end_time": event.end_time.isoformat(),
                "location": event.location, "attendees": event.attendees,
            } for event in rows]
            return self.create_result(
                success=True,
                result_data={"events": events, "count": len(events), "mode": "local"},
                output_text=f"Retrieved {len(events)} persisted local event(s)",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to list events: {str(e)}")


# ===== CALENDAR UPDATE EVENT TOOL =====

class CalendarUpdateEventInput(BaseModel):
    event_id: str = Field(..., description="Event ID to update")
    title: Optional[str] = Field(None, description="New title")
    start_time: Optional[str] = Field(None, description="New start time")
    end_time: Optional[str] = Field(None, description="New end time")
    description: Optional[str] = Field(None, description="New description")


class CalendarUpdateEventOutput(BaseModel):
    event_id: str
    updated_fields: List[str]
    mode: str


class CalendarUpdateEventTool(ToolBase):
    @property
    def name(self) -> str:
        return "calendar_update_event"

    @property
    def description(self) -> str:
        return "Update calendar event. Updates local event when calendar service not configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CalendarUpdateEventInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CalendarUpdateEventOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        event_id = input_data["event_id"]

        try:
            if is_calendar_configured():
                return self.create_result(success=False, error_message="External calendar sync is enabled but no provider adapter is configured")
            db, agent_id = await _memory_scope(context)
            event = (await db.execute(select(CalendarEvent).where(
                CalendarEvent.id == UUID(event_id),
                CalendarEvent.owner_id == UUID(str(context.user_id)),
                CalendarEvent.workspace_id == UUID(str(context.workspace_id)),
                CalendarEvent.agent_id == agent_id, CalendarEvent.is_active.is_(True),
            ))).scalar_one_or_none()
            if event is None:
                return self.create_result(success=False, error_message="Event not found in this workspace")
            updated_fields = []
            for field in ("title", "description", "location", "attendees", "reminders"):
                if input_data.get(field) is not None:
                    setattr(event, field, input_data[field])
                    updated_fields.append(field)
            for field in ("start_time", "end_time"):
                if input_data.get(field) is not None:
                    setattr(event, field, datetime.fromisoformat(input_data[field].replace("Z", "+00:00")))
                    updated_fields.append(field)
            if event.end_time <= event.start_time:
                return self.create_result(success=False, error_message="Event end_time must be after start_time")
            await db.flush()
            return self.create_result(
                success=True,
                result_data={"event_id": event_id, "updated_fields": updated_fields, "mode": "local"},
                output_text=f"Updated persisted event ({len(updated_fields)} fields)",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to update event: {str(e)}")


# ===== CALENDAR DELETE EVENT TOOL =====

class CalendarDeleteEventInput(BaseModel):
    event_id: str = Field(..., description="Event ID to delete")


class CalendarDeleteEventOutput(BaseModel):
    event_id: str
    deleted: bool
    mode: str


class CalendarDeleteEventTool(ToolBase):
    @property
    def name(self) -> str:
        return "calendar_delete_event"

    @property
    def description(self) -> str:
        return "Delete calendar event. Deletes local event when calendar service not configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CalendarDeleteEventInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CalendarDeleteEventOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        event_id = input_data["event_id"]

        try:
            if is_calendar_configured():
                return self.create_result(success=False, error_message="External calendar sync is enabled but no provider adapter is configured")
            db, agent_id = await _memory_scope(context)
            event = (await db.execute(select(CalendarEvent).where(
                CalendarEvent.id == UUID(event_id),
                CalendarEvent.owner_id == UUID(str(context.user_id)),
                CalendarEvent.workspace_id == UUID(str(context.workspace_id)),
                CalendarEvent.agent_id == agent_id,
            ))).scalar_one_or_none()
            if event is None:
                return self.create_result(success=False, error_message="Event not found in this workspace")
            event.is_active = False
            await db.flush()
            return self.create_result(
                success=True,
                result_data={"event_id": event_id, "deleted": True, "mode": "local"},
                output_text=f"Deactivated persisted event {event_id}",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to delete event: {str(e)}")
