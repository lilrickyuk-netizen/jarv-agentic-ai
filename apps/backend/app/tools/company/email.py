"""
JARV Backend - Email Tools

email_send, email_read and email_search on the real mailbox through the
mailer (app/core/business/mailer.py).

Setup: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM to send;
IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASSWORD (IMAP_FOLDER) to read. The
Settings page shows which are set and checks the connection.

- Sending always waits for approval: each message goes from Richard's account.
  Each recipient gets their own message; more than MAX_RECIPIENTS recipients
  is mass email, a hard boundary with no path here. Attachments must be files
  inside the workspace folder. Secrets are redacted from subject and body.
  Without SMTP the message is saved as a draft for Richard and nothing is sent.
- Reading and searching open the mailbox read-only (nothing is marked read,
  moved or deleted). The "drafts" folder is JARV's own saved drafts. Without
  IMAP only those drafts are available.
"""
from typing import Dict, Any, Type, List, Optional
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
import logging
import json
from uuid import UUID, uuid4
from sqlalchemy import select, or_

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.core.business import mailer
from app.core.security import redact_secrets
from app.tools.memory.storage import _memory_scope
from app.models.integrations import OutboundMessageDraft

logger = logging.getLogger(__name__)

MAX_RECIPIENTS = 10
_DRAFT_FOLDERS = ("draft", "drafts")


async def _attachment_paths(context: ToolContext, names: List[str]) -> List[Path]:
    """Resolve attachments inside the workspace folder; anything else is refused."""
    if not names:
        return []
    from app.core.workspaces import fs_inspector
    from app.models.workspace import Workspace

    ws = (await context.db_session.execute(select(Workspace).where(Workspace.id == context.workspace_id))).scalar_one()
    host = (ws.config or {}).get("root_path")
    root = fs_inspector.host_to_container(host) if host else None
    if root is None or not root.is_dir():
        raise ValueError("Attachments need a workspace folder; this workspace has none")
    root = root.resolve()
    paths: List[Path] = []
    for name in names:
        target = (root / name).resolve()
        if root != target and root not in target.parents:
            raise PermissionError(f"Attachment '{name}' is outside the workspace folder")
        if fs_inspector._is_banned(str(target)) or not target.is_file():
            raise LookupError(f"No file at '{name}' in the workspace")
        paths.append(target)
    return paths


def _draft_row(row: OutboundMessageDraft) -> Dict[str, Any]:
    return {"message_id": str(row.id), "from_addr": "local-draft", "subject": row.subject or "",
            "date": row.created_at.isoformat(), "preview": row.body[:160], "read": True,
            "has_attachments": bool((row.meta_data or {}).get("attachment_references"))}


def _mail_row(m: Dict[str, Any]) -> Dict[str, Any]:
    return {"message_id": m["message_id"], "from_addr": m["from_email"], "subject": m["subject"], "date": m["date"],
            "preview": redact_secrets(m["body"])[:400], "read": False, "has_attachments": m["has_attachments"]}


async def _drafts(context: ToolContext, limit: int, query: Optional[str] = None):
    db, agent_id = await _memory_scope(context)
    stmt = select(OutboundMessageDraft).where(
        OutboundMessageDraft.owner_id == UUID(str(context.user_id)),
        OutboundMessageDraft.workspace_id == UUID(str(context.workspace_id)),
        OutboundMessageDraft.agent_id == agent_id,
        OutboundMessageDraft.channel_type == "email",
        OutboundMessageDraft.status == "draft",
    )
    if query:
        stmt = stmt.where(or_(OutboundMessageDraft.subject.ilike(f"%{query}%"),
                              OutboundMessageDraft.body.ilike(f"%{query}%")))
    rows = (await db.execute(stmt.order_by(OutboundMessageDraft.created_at.desc()).limit(limit))).scalars().all()
    return [_draft_row(r) for r in rows]


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
    """Approved email sending from Richard's account (drafts without SMTP)."""

    @property
    def name(self) -> str:
        return "email_send"

    @property
    def description(self) -> str:
        return ("Send an email from Richard's account (after approval), one message per recipient, attachments from the "
                "workspace folder. Saves a draft when sending is not set up.")

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
        """Send each recipient their own message after approval; save a draft when SMTP is not set up."""
        to = list(input_data["to"])
        cc = list(input_data.get("cc") or [])
        bcc = list(input_data.get("bcc") or [])
        attachments = list(input_data.get("attachments") or [])
        recipients = list(dict.fromkeys(str(r) for r in to + cc + bcc))
        subject = redact_secrets(input_data["subject"])
        body = redact_secrets(input_data["body"])
        html = bool(input_data.get("html", False))

        try:
            if len(recipients) > MAX_RECIPIENTS:
                return self._blocked_result(
                    f"{len(recipients)} recipients is mass email from Richard's account, a hard boundary: at most "
                    f"{MAX_RECIPIENTS} per message. Draft a campaign instead for Richard to send from his email "
                    "platform.", approvable=False)
            if not self._has_approval(context):
                return self.create_result(success=False, requires_approval=True,
                    error_message="Sending email from Richard's account waits for his approval.")
            db, agent_id = await _memory_scope(context)
            files = await _attachment_paths(context, attachments)
            live = mailer.smtp_configured()
            sent: List[Dict[str, Any]] = []
            failed: List[Dict[str, Any]] = []
            if live:
                for address in recipients:
                    try:
                        result = await mailer.send_email(address, subject, body, html=html, attachments=files)
                        sent.append({"to": result["to"], "message_id": result["message_id"]})
                    except (OSError, ValueError) as exc:
                        failed.append({"to": address, "error": redact_secrets(str(exc)) or type(exc).__name__})
            record = OutboundMessageDraft(
                id=uuid4(), owner_id=UUID(str(context.user_id)),
                workspace_id=UUID(str(context.workspace_id)), agent_id=agent_id,
                channel_type="email", destination=json.dumps({"to": to, "cc": cc, "bcc": bcc}),
                subject=subject, body=body,
                meta_data={"html": html, "attachment_references": attachments,
                           "attachments_included": bool(live and files), "sent": sent, "failed": failed},
                status=("sent" if sent and not failed else "partially_sent" if sent else
                        "failed" if live else "draft"),
            )
            db.add(record)
            await db.flush()
            if not live:
                return self.create_result(
                    success=True,
                    result_data={"message_id": str(record.id), "status": "draft", "mode": "draft",
                                 "recipients": len(recipients), "sent": False, "attachments_included": False,
                                 "setup": "Set " + ", ".join(mailer.status()["missing_for_sending"]) + " to send."},
                    output_text=f"Email sending is not set up; saved draft {record.id} for Richard. Nothing was sent.")
            return self.create_result(
                success=not failed,
                result_data={"message_id": str(record.id), "status": record.status, "mode": "live",
                             "recipients": len(recipients), "sent": bool(sent), "delivered": sent, "failed": failed,
                             "attachments_included": bool(files)},
                output_text=(f"Sent to {len(sent)} of {len(recipients)} recipient(s)." if sent else
                             "No message was sent."),
                error_message=None if not failed else f"{len(failed)} recipient(s) failed: "
                              + "; ".join(f"{f['to']}: {f['error']}" for f in failed),
            )
        except (PermissionError, LookupError, ValueError) as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to process email: {redact_secrets(str(e))}")


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
    """Read-only mailbox reader (saved drafts without IMAP)."""

    @property
    def name(self) -> str:
        return "email_read"

    @property
    def description(self) -> str:
        return "Read the mailbox read-only (folder, unread only), or folder 'drafts' for JARV's saved drafts."

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
        """Read the mailbox read-only, or JARV's saved drafts."""
        folder = input_data.get("folder") or "inbox"
        limit = int(input_data.get("limit") or 50)
        unread_only = bool(input_data.get("unread_only"))

        try:
            await _memory_scope(context)
            if folder.lower() in _DRAFT_FOLDERS:
                if unread_only:
                    return self.create_result(success=False, error_message="Saved drafts have no unread state.")
                emails, mode = await _drafts(context, limit), "local_drafts"
            elif mailer.imap_configured():
                imap_folder = None if folder.lower() == "inbox" else folder
                emails = [_mail_row(m) for m in await mailer.read_messages(imap_folder, unread_only, min(limit, 200))]
                mode = "live"
            else:
                return self.create_result(success=False, error_message=(
                    "Mailbox reading is not set up (set " + ", ".join(mailer.status()["missing_for_reading"])
                    + "); only folder 'drafts' (JARV's saved drafts) is available."))
            return self.create_result(
                success=True, result_data={"emails": emails, "count": len(emails), "mode": mode},
                output_text=(f"Read {len(emails)} message(s) from {folder} (read-only)." if mode == "live" else
                             f"Retrieved {len(emails)} saved email draft(s)."),
            )
        except (PermissionError, LookupError, ValueError, RuntimeError, OSError) as e:
            return self.create_result(success=False, error_message=redact_secrets(str(e)) or type(e).__name__)
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to read emails: {redact_secrets(str(e))}")


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
    """Read-only mailbox search (saved drafts without IMAP)."""

    @property
    def name(self) -> str:
        return "email_search"

    @property
    def description(self) -> str:
        return "Search the mailbox read-only by text and sender, or JARV's saved drafts."

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
        """Server-side search of the mailbox (read-only), or of JARV's saved drafts."""
        query = input_data["query"]
        folder = input_data.get("folder")
        limit = int(input_data.get("limit") or 50)
        from_addr = input_data.get("from_addr")

        try:
            await _memory_scope(context)
            if folder and folder.lower() in _DRAFT_FOLDERS or (folder is None and not mailer.imap_configured()):
                emails, mode = await _drafts(context, limit, query), "local_drafts"
                if from_addr:
                    emails = [row for row in emails if row["from_addr"] == from_addr]
            elif mailer.imap_configured():
                imap_folder = None if not folder or folder.lower() == "inbox" else folder
                emails = [_mail_row(m) for m in await mailer.search_messages(query, imap_folder, from_addr,
                                                                             min(limit, 200))]
                mode = "live"
            else:
                return self.create_result(success=False, error_message=(
                    "Mailbox search is not set up (set " + ", ".join(mailer.status()["missing_for_reading"])
                    + "); only folder 'drafts' (JARV's saved drafts) can be searched."))
            if input_data.get("has_attachments") is not None:
                emails = [row for row in emails if row["has_attachments"] == input_data["has_attachments"]]
            return self.create_result(
                success=True, result_data={"emails": emails, "count": len(emails), "mode": mode},
                output_text=(f"Found {len(emails)} matching message(s) in the mailbox (read-only)." if mode == "live"
                             else f"Found {len(emails)} matching saved draft(s)."),
            )
        except (PermissionError, LookupError, ValueError, RuntimeError, OSError) as e:
            return self.create_result(success=False, error_message=redact_secrets(str(e)) or type(e).__name__)
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to search emails: {redact_secrets(str(e))}")
