"""
JARV Backend - Business tools (Repair 12e-4a)

Support, marketing, content, onboarding, community, partnership and sales
tools, all on persisted records in the calling workspace.

- 43 drafting tools (one per document kind in app.core.business.drafting):
  grounded in the workspace's real facts, saved as drafts, never published.
- Support: read_support_messages (local inbox, plus the email inbox when
  configured), create_ticket, categorise_ticket (escalates severe bugs to the
  debugging agent), draft_reply, send_standard_reply_with_rules (sends one
  reply when a workspace rule allows it, otherwise only with Richard's
  approval), update_faq, summarise_feedback.
- Community: read_community_messages, moderate_community_item_with_rules
  (approve / flag / hide, never delete), summarise_community_feedback.
- Partnerships and sales: create_partner_shortlist, update_partner_pipeline
  (an active agreement needs Richard), update_sales_pipeline (CRM deals).
- Onboarding and content: analyse_activation_friction, update_onboarding_copy,
  update_knowledge_base (versioned).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.business import drafting
from app.core.business.community import community_service, view as community_view
from app.core.business.onboarding import (
    analyse_activation_friction, flow_view, update_knowledge_base, update_onboarding_copy,
)
from app.core.business.pipelines import deal_view, partner_view, pipeline_service
from app.core.business.support import sentiment, support_service, terms, view as ticket_view
from app.tools._scoped import ScopedTool

GROUP_CATEGORY = {"marketing": "marketing", "content": "content", "onboarding": "onboarding",
                  "community": "community", "partnership": "partnership", "sales": "sales"}


class _BusinessTool(ScopedTool):
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS


# ----- drafting tools -----------------------------------------------------------------------

class DraftInput(BaseModel):
    topic: Optional[str] = Field(None, description="What to write about (the announcement, question, goal)")
    audience: Optional[str] = Field(None, description="Who it is for")
    title: Optional[str] = None
    tone: Optional[str] = Field(None, description="e.g. friendly, technical, formal")
    channels: List[str] = Field(default_factory=list, description="Campaign channels")
    count: Optional[int] = Field(None, ge=1, le=7, description="Emails in a sequence")
    since: Optional[str] = Field(None, description="Changelog/release notes: include changes since YYYY-MM-DD")
    message: Optional[str] = Field(None, description="The message being answered")
    reply_to: Optional[str] = Field(None, description="Community item id being answered")
    partner_id: Optional[str] = None
    partner_name: Optional[str] = None
    deal_id: Optional[str] = None
    prospect: Optional[str] = None
    campaign_type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    save_to_workspace: bool = Field(False, description="Also write the draft to docs/<group>/ in the workspace folder")


class _DraftTool(_BusinessTool):
    _input = DraftInput
    _kind = ""

    async def act(self, db, context, owner, data):
        if data.get("reply_to"):
            await community_service.item(db, context.workspace_id, data["reply_to"])
        result = await drafting.draft(db, context.workspace_id, self._kind, data, owner=owner)
        gaps = len(result["needs_confirmation"])
        return result, (f"{drafting.KINDS[self._kind].label.capitalize()} drafted ({result['generated_by']})"
                        + (f"; {gaps} item(s) for Richard to confirm" if gaps else ""))


def _draft_tool(kind: drafting.DraftKind) -> Type[_DraftTool]:
    name = "".join(part.title() for part in kind.tool.split("_")) + "Tool"
    return type(name, (_DraftTool,), {
        "_name": kind.tool, "_kind": kind.tool, "_category": GROUP_CATEGORY[kind.group],
        "_description": f"Draft a {kind.label} grounded in the workspace's real facts; saved as a draft, never published."})


DRAFT_TOOLS = [_draft_tool(kind) for kind in drafting.KINDS.values()]


# ----- support --------------------------------------------------------------------------------

class _ReadSupport(BaseModel):
    status: Optional[str] = Field(None, description="new, open, escalated, waiting_customer, resolved")
    category: Optional[str] = None
    limit: int = Field(25, ge=1, le=200)
    sync_inbox: bool = Field(False, description="First read new emails from the configured inbox into tickets")


class ReadSupportMessagesTool(_BusinessTool):
    _name = "read_support_messages"
    _category = "support"
    _description = "Read the support inbox (tickets with their conversation); optionally pull new emails first."
    _input = _ReadSupport

    async def act(self, db, context, owner, data):
        from app.core.business import mailer

        synced = None
        if data["sync_inbox"]:
            synced = await support_service.sync_inbox(db, context.workspace_id)
        rows = await support_service.list(db, context.workspace_id, status=data.get("status"),
                                          category=data.get("category"), limit=data["limit"])
        return ({"tickets": [ticket_view(t) for t in rows], "inbox_sync": synced, "email": mailer.status()},
                f"{len(rows)} ticket(s)" + (f"; {synced['read']} new email(s) read" if synced else ""))


class _CreateTicket(BaseModel):
    subject: str = Field(..., min_length=3)
    description: str = Field(..., min_length=3)
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None


class CreateTicketTool(_BusinessTool):
    _name = "create_ticket"
    _category = "support"
    _description = "Open a support ticket; it is categorised, prioritised and (for severe bugs) escalated."
    _input = _CreateTicket

    async def act(self, db, context, owner, data):
        ticket = await support_service.create_ticket(db, context.workspace_id, subject=data["subject"],
                                                     description=data["description"],
                                                     customer_email=data.get("customer_email"),
                                                     customer_name=data.get("customer_name"),
                                                     category=data.get("category"), priority=data.get("priority"),
                                                     source="tool")
        return ticket_view(ticket), f"Ticket {ticket.ticket_number} ({ticket.category}, {ticket.priority})"


class _TicketRef(BaseModel):
    ticket_id: str = Field(..., description="Ticket id or number")


class _Categorise(_TicketRef):
    category: Optional[str] = None
    priority: Optional[str] = None


class CategoriseTicketTool(_BusinessTool):
    _name = "categorise_ticket"
    _category = "support"
    _description = "Set or recompute a ticket's category, priority and severity; severe bugs go to the debugging agent."
    _input = _Categorise

    async def act(self, db, context, owner, data):
        ticket = await support_service.categorise(db, context.workspace_id, data["ticket_id"],
                                                  data.get("category"), data.get("priority"))
        return ticket_view(ticket), f"{ticket.ticket_number}: {ticket.category}, {ticket.priority}, {ticket.severity}"


class _DraftReply(_TicketRef):
    tone: str = "friendly"


class DraftReplyTool(_BusinessTool):
    _name = "draft_reply"
    _category = "support"
    _description = "Draft a reply to a ticket from the FAQ and the product's facts (saved on the ticket, not sent)."
    _input = _DraftReply

    async def act(self, db, context, owner, data):
        draft = await support_service.draft_reply(db, context.workspace_id, data["ticket_id"], tone=data["tone"])
        return draft, f"Reply drafted (confidence {draft['confidence']:.2f}, {draft['generated_by']})"


class _SendReply(_TicketRef):
    body: Optional[str] = Field(None, description="Send this text instead of the last draft (needs approval)")


class SendStandardReplyWithRulesTool(_BusinessTool):
    _name = "send_standard_reply_with_rules"
    _category = "support"
    _description = ("Email the drafted reply to the ticket's customer when the workspace's support_reply rule allows "
                    "the category at the draft's confidence; otherwise it waits for Richard's approval.")
    _input = _SendReply
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS
    _gated = True

    async def act(self, db, context, owner, data):
        sent = await support_service.send_reply(db, context.workspace_id, data["ticket_id"], approved=data["_approved"],
                                                body=data.get("body"))
        return sent, f"Reply sent to {sent['to']} (authorised by {sent['authorised_by']})"


class _Faq(BaseModel):
    question: str = Field(..., min_length=5)
    answer: str = Field(..., min_length=5)
    faq_id: Optional[str] = None


class UpdateFaqTool(_BusinessTool):
    _name = "update_faq"
    _category = "support"
    _description = "Add or edit an FAQ entry (previous versions kept); drafts and replies use the FAQ."
    _input = _Faq

    async def act(self, db, context, owner, data):
        row = await support_service.update_faq(db, context.workspace_id, question=data["question"],
                                               answer=data["answer"], faq_id=data.get("faq_id"), author=owner)
        return {"id": str(row.id), "question": row.title, "answer": row.content_body,
                "version": (row.meta_data or {}).get("version")}, f"FAQ v{(row.meta_data or {}).get('version')} saved"


class _Days(BaseModel):
    days: int = Field(30, ge=1, le=365)


class SummariseFeedbackTool(_BusinessTool):
    _name = "summarise_feedback"
    _category = "support"
    _description = "Summarise support tickets and community messages: categories, sentiment, themes, bugs, requests."
    _input = _Days
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        summary = await support_service.feedback_summary(db, context.workspace_id, data["days"])
        return summary, (f"{summary['tickets']} ticket(s), {summary['community_messages']} community message(s); "
                         f"{len(summary['bugs'])} bug(s), {len(summary['feature_requests'])} request(s)")


# ----- community ------------------------------------------------------------------------------

class _ReadCommunity(BaseModel):
    status: Optional[str] = Field(None, description="new, approved, flagged, hidden")
    channel: Optional[str] = None
    limit: int = Field(25, ge=1, le=200)


class ReadCommunityMessagesTool(_BusinessTool):
    _name = "read_community_messages"
    _category = "community"
    _description = "Read community messages received in this workspace (forum, GitHub, Discord, ...)."
    _input = _ReadCommunity
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        rows = await community_service.read(db, context.workspace_id, status=data.get("status"),
                                            channel=data.get("channel"), limit=data["limit"])
        return {"messages": [community_view(r) for r in rows]}, f"{len(rows)} community message(s)"


class _ItemRef(BaseModel):
    item_id: str


class ModerateCommunityItemWithRulesTool(_BusinessTool):
    _name = "moderate_community_item_with_rules"
    _category = "community"
    _description = ("Moderate a community message by the workspace's moderation rule and built-in spam/abuse signals: "
                    "approve, flag for Richard, or hide (never delete).")
    _input = _ItemRef

    async def act(self, db, context, owner, data):
        result = await community_service.moderate(db, context.workspace_id, data["item_id"], owner)
        return result, f"{result['decision']}: {', '.join(result['reasons']) or 'no rule matched'}"


class SummariseCommunityFeedbackTool(_BusinessTool):
    _name = "summarise_community_feedback"
    _category = "community"
    _description = "Summarise community messages: channels, sentiment, themes, requests and moderation."
    _input = _Days
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        from app.core.business.support import categorise_text
        from app.models.content import CommunityItem

        since = datetime.now(timezone.utc) - timedelta(days=data["days"])
        rows = (await db.execute(select(CommunityItem).where(
            CommunityItem.workspace_id == context.workspace_id, CommunityItem.item_type == "message",
            CommunityItem.created_at >= since))).scalars().all()
        texts = [f"{r.title} {r.content}" for r in rows]
        summary = {"period_days": data["days"], "messages": len(rows),
                   "by_channel": dict(Counter(r.category for r in rows)),
                   "by_status": dict(Counter(r.status for r in rows)),
                   "sentiment": dict(Counter(sentiment(t) for t in texts)), "top_terms": terms(texts),
                   "requests": [r.title for r in rows if categorise_text(r.title, r.content)["category"] == "feature_request"][:15],
                   "problems": [r.title for r in rows if categorise_text(r.title, r.content)["category"] == "bug"][:15]}
        return summary, f"{len(rows)} community message(s) in {data['days']} days"


# ----- partnerships and sales ------------------------------------------------------------------

class _Shortlist(BaseModel):
    partner_type: str = Field("technology", description="technology, distribution, reseller, affiliate, integration, ...")
    candidates: List[Dict[str, Any]] = Field(default_factory=list, description="[{name, type, notes, url, contact, email}]")
    criteria: Dict[str, float] = Field(default_factory=dict, description="{term: weight} the fit is scored on")


class CreatePartnerShortlistTool(_BusinessTool):
    _name = "create_partner_shortlist"
    _category = "partnership"
    _description = ("Score partner candidates against criteria and the product's stack and save them to the partner "
                    "pipeline as shortlisted (model-suggested candidates are marked unverified).")
    _input = _Shortlist

    async def act(self, db, context, owner, data):
        rows = await pipeline_service.shortlist(db, context.workspace_id, candidates=data["candidates"],
                                                criteria=data["criteria"], partner_type=data["partner_type"],
                                                owner=owner)
        return {"shortlist": [partner_view(r) for r in rows]}, f"{len(rows)} partner(s) shortlisted"


class _PartnerUpdate(BaseModel):
    partner_id: str
    status: Optional[str] = Field(None, description="shortlisted, contacted, in_discussion, proposal, negotiating, "
                                                    "active (needs Richard), paused, declined")
    notes: Optional[str] = None
    estimated_value: Optional[float] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None


class UpdatePartnerPipelineTool(_BusinessTool):
    _name = "update_partner_pipeline"
    _category = "partnership"
    _description = "Move a partner through the pipeline and record notes; an active agreement needs Richard's approval."
    _input = _PartnerUpdate
    _gated = True

    async def act(self, db, context, owner, data):
        row = await pipeline_service.update_partner(
            db, context.workspace_id, data["partner_id"], status=data.get("status"), notes=data.get("notes"),
            estimated_value=data.get("estimated_value"), contact_name=data.get("contact_name"),
            contact_email=data.get("contact_email"), approved=data["_approved"])
        return partner_view(row), f"{row.partner_name}: {row.status}"


class _DealUpdate(BaseModel):
    deal_id: Optional[str] = Field(None, description="Existing deal; omit to create one")
    title: Optional[str] = None
    stage: Optional[str] = Field(None, description="prospecting, qualified, proposal, negotiation, closed_won, closed_lost")
    value: Optional[float] = None
    notes: Optional[str] = None
    expected_close_date: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    company: Optional[str] = None


class UpdateSalesPipelineTool(_BusinessTool):
    _name = "update_sales_pipeline"
    _category = "sales"
    _description = "Create or move a CRM deal through the sales pipeline; returns the pipeline totals."
    _input = _DealUpdate

    async def act(self, db, context, owner, data):
        deal = await pipeline_service.update_deal(
            db, context.workspace_id, owner, deal_id=data.get("deal_id"), title=data.get("title"),
            stage=data.get("stage"), value=data.get("value"), notes=data.get("notes"),
            expected_close_date=data.get("expected_close_date"), contact_name=data.get("contact_name"),
            contact_email=data.get("contact_email"), company=data.get("company"))
        pipeline = await pipeline_service.pipeline(db, context.workspace_id)
        return ({"deal": deal_view(deal), "open_pipeline_value": pipeline["open_pipeline_value"],
                 "deals_by_stage": pipeline["deals_by_stage"], "win_rate": pipeline["win_rate"]},
                f"{deal.title}: {deal.stage}")


# ----- onboarding and content ------------------------------------------------------------------

class AnalyseActivationFrictionTool(_BusinessTool):
    _name = "analyse_activation_friction"
    _category = "onboarding"
    _description = ("Find where new users get stuck, from onboarding completion data, getting-started support tickets, "
                    "activation KPIs and open launch items.")
    _input = _Days
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        result = await analyse_activation_friction(db, context.workspace_id, data["days"])
        return result, f"{len(result['findings'])} friction finding(s)"


class _OnboardingCopy(BaseModel):
    flow_id: str
    step: Optional[int] = Field(None, ge=1)
    title: Optional[str] = None
    copy_text: Optional[str] = Field(None, description="The step's copy")
    description: Optional[str] = None


class UpdateOnboardingCopyTool(_BusinessTool):
    _name = "update_onboarding_copy"
    _category = "onboarding"
    _description = "Edit an onboarding flow's copy (a step's title/text or the description); each edit is a new version."
    _input = _OnboardingCopy

    async def act(self, db, context, owner, data):
        flow = await update_onboarding_copy(db, context.workspace_id, data["flow_id"], step=data.get("step"),
                                            title=data.get("title"), copy=data.get("copy_text"),
                                            description=data.get("description"))
        return flow_view(flow), f"'{flow.flow_name}' is now v{flow.version}"


class _Kb(BaseModel):
    title: str = Field(..., min_length=3)
    body: str = Field(..., min_length=10)
    article_id: Optional[str] = None


class UpdateKnowledgeBaseTool(_BusinessTool):
    _name = "update_knowledge_base"
    _category = "content"
    _description = "Add or revise a knowledge-base article (previous versions kept)."
    _input = _Kb

    async def act(self, db, context, owner, data):
        row = await update_knowledge_base(db, context.workspace_id, title=data["title"], body=data["body"],
                                          article_id=data.get("article_id"), author=owner)
        return {"id": str(row.id), "title": row.title, "version": (row.meta_data or {}).get("version"),
                "status": row.status}, f"Knowledge base article v{(row.meta_data or {}).get('version')} saved"


DATA_TOOLS = [
    ReadSupportMessagesTool, CreateTicketTool, CategoriseTicketTool, DraftReplyTool, SendStandardReplyWithRulesTool,
    UpdateFaqTool, SummariseFeedbackTool, ReadCommunityMessagesTool, ModerateCommunityItemWithRulesTool,
    SummariseCommunityFeedbackTool, CreatePartnerShortlistTool, UpdatePartnerPipelineTool, UpdateSalesPipelineTool,
    AnalyseActivationFrictionTool, UpdateOnboardingCopyTool, UpdateKnowledgeBaseTool,
]
BUSINESS_TOOLS = DRAFT_TOOLS + DATA_TOOLS

TOOLS_BY_GROUP: Dict[str, List[str]] = {}
for _tool in BUSINESS_TOOLS:
    TOOLS_BY_GROUP.setdefault(_tool._category, []).append(_tool._name)
