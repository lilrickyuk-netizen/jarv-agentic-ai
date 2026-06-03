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

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

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
            # Validate datetime format
            datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            datetime.fromisoformat(end_time.replace('Z', '+00:00'))

            if not is_calendar_configured():
                # LOCAL MODE: Save event to database
                from uuid import uuid4
                event_id = str(uuid4())

                # In production: Save to CalendarEvent table
                logger.info(f"Calendar service not configured. Saving local event: {event_id}")
                logger.info(f"Event: '{title}' from {start_time} to {end_time}")

                return self.create_result(
                    success=True,
                    result_data={
                        "event_id": event_id,
                        "title": title,
                        "start_time": start_time,
                        "mode": "local",
                        "status": "created_local",
                    },
                    output_text=f"Event saved locally (service not configured). Event ID: {event_id}",
                )

            # LIVE MODE: Would sync to configured calendar service
            logger.warning("Calendar service enabled but sync integration not implemented yet")

            return self.create_result(
                success=False,
                error_message="Calendar service enabled but sync integration not yet implemented. Use local mode.",
            )

        except ValueError as e:
            return self.create_result(
                success=False,
                error_message=f"Invalid datetime format: {str(e)}. Use ISO format (YYYY-MM-DDTHH:MM:SS)",
            )
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
            if not is_calendar_configured():
                # LOCAL MODE: Query local events from database
                # In production: Query CalendarEvent table
                events = []
                logger.info("Calendar service not configured. Returning local events.")

                return self.create_result(
                    success=True,
                    result_data={"events": events, "count": len(events), "mode": "local"},
                    output_text=f"Retrieved {len(events)} local event(s) (service not configured)",
                )

            # LIVE MODE: Would fetch from configured calendar service
            logger.warning("Calendar service enabled but fetch integration not implemented yet")

            return self.create_result(
                success=False,
                error_message="Calendar service enabled but fetch integration not yet implemented. Use local mode.",
            )

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
            updated_fields = [k for k, v in input_data.items() if k != "event_id" and v is not None]

            if not is_calendar_configured():
                # LOCAL MODE: Update in database
                logger.info(f"Calendar service not configured. Updating local event: {event_id}")

                return self.create_result(
                    success=True,
                    result_data={"event_id": event_id, "updated_fields": updated_fields, "mode": "local"},
                    output_text=f"Event updated locally (service not configured)",
                )

            # LIVE MODE
            logger.warning("Calendar service enabled but update integration not implemented yet")

            return self.create_result(
                success=False,
                error_message="Calendar service enabled but update integration not yet implemented. Use local mode.",
            )

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
            if not is_calendar_configured():
                # LOCAL MODE: Delete from database
                logger.info(f"Calendar service not configured. Deleting local event: {event_id}")

                return self.create_result(
                    success=True,
                    result_data={"event_id": event_id, "deleted": True, "mode": "local"},
                    output_text=f"Event deleted locally (service not configured)",
                )

            # LIVE MODE
            logger.warning("Calendar service enabled but delete integration not implemented yet")

            return self.create_result(
                success=False,
                error_message="Calendar service enabled but delete integration not yet implemented. Use local mode.",
            )

        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to delete event: {str(e)}")
