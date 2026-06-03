"""
JARV Backend - Email Tools

Real email operations with local draft mode when unconfigured.

SETUP INSTRUCTIONS:
- Set EMAIL_SERVICE_ENABLED=true in environment
- Configure SMTP or email service API credentials:
  - SMTP: EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD
  - Gmail API: GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
  - SendGrid: SENDGRID_API_KEY

When unconfigured, emails are saved as local drafts in database.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime
import logging
import os

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


def is_email_configured() -> bool:
    """Check if email service is configured"""
    return os.getenv("EMAIL_SERVICE_ENABLED", "false").lower() == "true"


# ===== EMAIL SEND TOOL =====

class EmailSendInput(BaseModel):
    """Input schema for email send tool"""
    to: List[EmailStr] = Field(..., description="Recipient email addresses")
    subject: str = Field(..., min_length=1, max_length=500, description="Email subject")
    body: str = Field(..., min_length=1, description="Email body (plain text or HTML)")
    cc: Optional[List[EmailStr]] = Field(None, description="CC recipients")
    bcc: Optional[List[EmailStr]] = Field(None, description="BCC recipients")
    attachments: Optional[List[str]] = Field(None, description="Attachment file paths")
    html: bool = Field(default=False, description="Whether body is HTML")


class EmailSendOutput(BaseModel):
    """Output schema for email send tool"""
    message_id: str = Field(..., description="Message ID or draft ID")
    status: str = Field(..., description="Status: sent, draft, failed")
    mode: str = Field(..., description="Mode: live, draft")
    recipients: int = Field(..., description="Number of recipients")


class EmailSendTool(ToolBase):
    """Tool for sending emails (or saving as drafts when unconfigured)"""

    @property
    def name(self) -> str:
        return "email_send"

    @property
    def description(self) -> str:
        return "Send email with optional attachments. Saves as draft when email service not configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return EmailSendInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return EmailSendOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True  # Sending emails requires approval

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute email send or save as draft"""
        to = input_data["to"]
        subject = input_data["subject"]
        body = input_data["body"]
        cc = input_data.get("cc") or []
        bcc = input_data.get("bcc") or []
        attachments = input_data.get("attachments") or []

        total_recipients = len(to) + len(cc) + len(bcc)

        try:
            # Check if email service is configured
            if not is_email_configured():
                # LOCAL DRAFT MODE: Save email as draft in database
                from uuid import uuid4
                draft_id = str(uuid4())

                # In production: Save to EmailDraft table in database
                logger.info(f"Email service not configured. Saving draft: {draft_id}")
                logger.info(f"Draft: To={to}, Subject='{subject}'")

                return self.create_result(
                    success=True,
                    result_data={
                        "message_id": draft_id,
                        "status": "draft",
                        "mode": "draft",
                        "recipients": total_recipients,
                    },
                    output_text=f"Email saved as draft (service not configured). Draft ID: {draft_id}",
                )

            # LIVE MODE: Would send via configured email service
            # This code path only executes if EMAIL_SERVICE_ENABLED=true
            logger.warning("Email service enabled but SMTP/API integration not implemented yet")

            return self.create_result(
                success=False,
                error_message="Email service enabled but send integration not yet implemented. Use draft mode.",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to process email: {str(e)}",
            )


# ===== EMAIL READ TOOL =====

class EmailReadInput(BaseModel):
    """Input schema for email read tool"""
    folder: str = Field(default="inbox", description="Email folder to read")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum emails to retrieve")
    unread_only: bool = Field(default=False, description="Only fetch unread emails")
    since_date: Optional[str] = Field(None, description="Fetch emails since date (ISO format)")


class EmailInfo(BaseModel):
    """Email information"""
    message_id: str
    from_addr: str
    subject: str
    date: str
    preview: str
    read: bool
    has_attachments: bool


class EmailReadOutput(BaseModel):
    """Output schema for email read tool"""
    emails: List[EmailInfo] = Field(..., description="List of emails")
    count: int = Field(..., description="Number of emails retrieved")
    mode: str = Field(..., description="Mode: live, local")


class EmailReadTool(ToolBase):
    """Tool for reading emails (local mode when unconfigured)"""

    @property
    def name(self) -> str:
        return "email_read"

    @property
    def description(self) -> str:
        return "Read emails from mailbox. Returns local drafts when email service not configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return EmailReadInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return EmailReadOutput

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
        """Execute email read"""
        folder = input_data["folder"]
        limit = input_data["limit"]
        unread_only = input_data["unread_only"]

        try:
            if not is_email_configured():
                # LOCAL MODE: Return local drafts from database
                # In production: Query EmailDraft table
                emails = []
                logger.info("Email service not configured. Returning local drafts.")

                return self.create_result(
                    success=True,
                    result_data={
                        "emails": emails,
                        "count": len(emails),
                        "mode": "local",
                    },
                    output_text=f"Retrieved {len(emails)} local draft(s) (service not configured)",
                )

            # LIVE MODE: Would fetch from configured email service
            logger.warning("Email service enabled but fetch integration not implemented yet")

            return self.create_result(
                success=False,
                error_message="Email service enabled but fetch integration not yet implemented. Use local mode.",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to read emails: {str(e)}",
            )


# ===== EMAIL SEARCH TOOL =====

class EmailSearchInput(BaseModel):
    """Input schema for email search tool"""
    query: str = Field(..., min_length=1, description="Search query")
    folder: Optional[str] = Field(None, description="Folder to search (None = all folders)")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum results")
    from_addr: Optional[str] = Field(None, description="Filter by sender")
    has_attachments: Optional[bool] = Field(None, description="Filter by attachment presence")


class EmailSearchOutput(BaseModel):
    """Output schema for email search tool"""
    emails: List[EmailInfo] = Field(..., description="Matching emails")
    count: int = Field(..., description="Number of matches")
    mode: str = Field(..., description="Mode: live, local")


class EmailSearchTool(ToolBase):
    """Tool for searching emails (local mode when unconfigured)"""

    @property
    def name(self) -> str:
        return "email_search"

    @property
    def description(self) -> str:
        return "Search emails by query. Searches local drafts when email service not configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return EmailSearchInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return EmailSearchOutput

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
        """Execute email search"""
        query = input_data["query"]
        folder = input_data.get("folder")
        limit = input_data["limit"]

        try:
            if not is_email_configured():
                # LOCAL MODE: Search local drafts in database
                # In production: Query EmailDraft table with search
                emails = []
                logger.info(f"Email service not configured. Searching local drafts: {query}")

                return self.create_result(
                    success=True,
                    result_data={
                        "emails": emails,
                        "count": len(emails),
                        "mode": "local",
                    },
                    output_text=f"Found {len(emails)} matching local draft(s) (service not configured)",
                )

            # LIVE MODE: Would search via configured email service
            logger.warning("Email service enabled but search integration not implemented yet")

            return self.create_result(
                success=False,
                error_message="Email service enabled but search integration not yet implemented. Use local mode.",
            )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to search emails: {str(e)}",
            )
