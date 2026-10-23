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
import json
from uuid import UUID, uuid4
from sqlalchemy import select, or_

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.core.security import redact_secrets
from app.tools.memory.storage import _memory_scope
from app.models.integrations import OutboundMessageDraft

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
            if is_email_configured():
                return self.create_result(success=False,
                    error_message="Email provider flag is enabled, but no provider adapter is installed; no message was sent.")
            if not self._has_approval(context):
                return self.create_result(success=False, requires_approval=True,
                    error_message="Email draft creation requires an approved execution context.")
            db, agent_id = await _memory_scope(context)
            draft = OutboundMessageDraft(
                id=uuid4(), owner_id=UUID(str(context.user_id)),
                workspace_id=UUID(str(context.workspace_id)), agent_id=agent_id,
                channel_type="email", destination=json.dumps({"to": to, "cc": cc, "bcc": bcc}),
                subject=redact_secrets(subject), body=redact_secrets(body),
                meta_data={"html": input_data.get("html", False),
                           "attachment_references": attachments,
                           "attachments_included": False},
                status="draft",
            )
            db.add(draft)
            await db.flush()
            draft_id = str(draft.id)
            return self.create_result(
                success=True,
                result_data={
                    "message_id": draft_id, "status": "draft", "mode": "draft",
                    "recipients": total_recipients, "sent": False,
                    "attachments_included": False,
                    "limitations": ["Email delivery is disabled; this record is only a saved draft."],
                },
                output_text=f"Saved email draft {draft_id}; no message was sent.",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
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
            if is_email_configured():
                return self.create_result(success=False, error_message="Email provider adapter is not installed; mailbox reads are unavailable.")
            if folder.lower() not in ("draft", "drafts") or unread_only:
                return self.create_result(success=False, error_message="Only locally saved drafts are available; inbox/unread reads require a provider.")
            db, agent_id = await _memory_scope(context)
            rows = (await db.execute(select(OutboundMessageDraft).where(
                OutboundMessageDraft.owner_id == UUID(str(context.user_id)),
                OutboundMessageDraft.workspace_id == UUID(str(context.workspace_id)),
                OutboundMessageDraft.agent_id == agent_id,
                OutboundMessageDraft.channel_type == "email",
                OutboundMessageDraft.status == "draft",
            ).order_by(OutboundMessageDraft.created_at.desc()).limit(limit))).scalars().all()
            emails = [{
                "message_id": str(row.id), "from_addr": "local-draft",
                "subject": row.subject or "", "date": row.created_at.isoformat(),
                "preview": row.body[:160], "read": True,
                "has_attachments": bool((row.meta_data or {}).get("attachment_references")),
            } for row in rows]
            return self.create_result(
                success=True, result_data={"emails": emails, "count": len(emails), "mode": "local_drafts"},
                output_text=f"Retrieved {len(emails)} saved email draft(s); no mailbox was queried.",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
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
            if is_email_configured():
                return self.create_result(success=False, error_message="Email provider adapter is not installed; mailbox search is unavailable.")
            db, agent_id = await _memory_scope(context)
            stmt = select(OutboundMessageDraft).where(
                OutboundMessageDraft.owner_id == UUID(str(context.user_id)),
                OutboundMessageDraft.workspace_id == UUID(str(context.workspace_id)),
                OutboundMessageDraft.agent_id == agent_id,
                OutboundMessageDraft.channel_type == "email",
                OutboundMessageDraft.status == "draft",
                or_(OutboundMessageDraft.subject.ilike(f"%{query}%"),
                    OutboundMessageDraft.body.ilike(f"%{query}%")),
            )
            if folder not in (None, "draft", "drafts"):
                return self.create_result(success=False, error_message="Only locally saved drafts can be searched without a provider.")
            rows = (await db.execute(stmt.order_by(OutboundMessageDraft.created_at.desc()).limit(limit))).scalars().all()
            emails = [{
                "message_id": str(row.id), "from_addr": "local-draft",
                "subject": row.subject or "", "date": row.created_at.isoformat(),
                "preview": row.body[:160], "read": True,
                "has_attachments": bool((row.meta_data or {}).get("attachment_references")),
            } for row in rows]
            if input_data.get("from_addr"):
                emails = [row for row in emails if row["from_addr"] == input_data["from_addr"]]
            if input_data.get("has_attachments") is not None:
                emails = [row for row in emails if row["has_attachments"] == input_data["has_attachments"]]
            return self.create_result(
                success=True, result_data={"emails": emails, "count": len(emails), "mode": "local_drafts"},
                output_text=f"Found {len(emails)} matching saved drafts; no mailbox was queried.",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to search emails: {str(e)}",
            )
