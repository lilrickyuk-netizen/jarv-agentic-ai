"""
JARV Backend - Company Operation Tools

Tools for company operations: email, calendar, CRM, Slack.
"""
from app.tools.company.email import EmailSendTool, EmailReadTool, EmailSearchTool
from app.tools.company.calendar import (
    CalendarCreateEventTool,
    CalendarListEventsTool,
    CalendarUpdateEventTool,
    CalendarDeleteEventTool,
)
from app.tools.company.crm import (
    CrmCreateContactTool,
    CrmUpdateContactTool,
    CrmSearchContactsTool,
    CrmCreateDealTool,
    CrmUpdateDealTool,
)
from app.tools.company.slack import SlackSendTool, SlackReadTool, SlackSearchTool

__all__ = [
    # Email tools
    "EmailSendTool",
    "EmailReadTool",
    "EmailSearchTool",
    # Calendar tools
    "CalendarCreateEventTool",
    "CalendarListEventsTool",
    "CalendarUpdateEventTool",
    "CalendarDeleteEventTool",
    # CRM tools
    "CrmCreateContactTool",
    "CrmUpdateContactTool",
    "CrmSearchContactsTool",
    "CrmCreateDealTool",
    "CrmUpdateDealTool",
    # Slack tools
    "SlackSendTool",
    "SlackReadTool",
    "SlackSearchTool",
]
