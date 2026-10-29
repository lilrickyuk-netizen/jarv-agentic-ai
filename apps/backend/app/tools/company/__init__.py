"""
JARV Backend - Company Operation Tools

Tools for company operations: email, calendar, CRM, Slack, and the company
operating layer (plans, loops, standups, KPIs, risks, decisions, feed).
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
from app.tools.company.operations import COMPANY_TOOLS

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
    # Company operating layer
    "COMPANY_TOOLS",
]
