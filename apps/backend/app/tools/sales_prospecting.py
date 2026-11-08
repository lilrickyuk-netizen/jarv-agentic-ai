"""
JAI Backend - The Sales agent's prospecting tools (Upgrade 6)

Registered in JAI's tool registry under the sales group, so the Sales agent has them with its other tools, every
call checked by the authority checker and recorded (ToolRun, audit). The workflow is app.core.business.prospecting:
find companies, read their buying signals, find who decides, check the address, draft, approve, send, handle
replies, report. Sending is gated: each batch is a hard boundary that waits for Richard's approval.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.agents.base import AuthorityLevel
from app.core.business.prospecting import prospecting_service
from app.tools._scoped import ScopedTool


class _SalesTool(ScopedTool):
    _category = "sales"
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS


class _Discover(BaseModel):
    category: str = Field(..., min_length=2, description="Customer type (dentist, roofer, gym...) or an OSM tag like craft=roofer")
    area: str = Field(..., min_length=2, description="Town, city or region, e.g. 'Leeds, UK'")
    limit: int = Field(25, ge=1, le=100)


class DiscoverProspectCompaniesTool(_SalesTool):
    _name = "discover_prospect_companies"
    _description = ("Find businesses of a customer type in an area from OpenStreetMap (free open data), each with its "
                    "website, saved to this workspace's prospect list.")
    _input = _Discover
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    async def act(self, db, context, owner, data):
        found = await prospecting_service.discover(db, context.workspace_id, category=data["category"],
                                                   area=data["area"], limit=data["limit"])
        return found, f"{found['found']} {data['category']} business(es) found in {data['area']}"


class _Signal(BaseModel):
    name: str = Field(..., min_length=2, description="What the signal means, e.g. 'no online booking'")
    look_for: List[str] = Field(..., min_length=1, description="Words or phrases to look for on their site")
    want: str = Field("present", pattern="^(present|absent)$", description="present: a fit when found; absent: a fit when missing")


class _Signals(BaseModel):
    company_ids: List[str] = Field(..., min_length=1, max_length=50)
    signals: List[_Signal] = Field(..., min_length=1, max_length=10)


class ReadBuyingSignalsTool(_SalesTool):
    _name = "read_buying_signals"
    _description = ("Read each company's own website for the buying signals Richard confirmed (no model call); scores "
                    "the fit and keeps the evidence.")
    _input = _Signals
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    async def act(self, db, context, owner, data):
        rows = await prospecting_service.read_signals(db, context.workspace_id, data["company_ids"], data["signals"])
        fits = sum(1 for r in rows if r["status"] == "qualified")
        return {"companies": rows}, f"{fits} of {len(rows)} company(ies) fit"


class _Company(BaseModel):
    company_id: str


class FindDecisionMakersTool(_SalesTool):
    _name = "find_decision_makers"
    _description = ("Find the owner or manager named on the company's own pages (two people at most); a name not on "
                    "the page is never kept.")
    _input = _Company
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    async def act(self, db, context, owner, data):
        found = await prospecting_service.find_people(db, context.workspace_id, data["company_id"])
        return found, f"{len(found['people'])} decision maker(s) at {found['company']['name']}"


class _ProspectRef(BaseModel):
    prospect_id: str


class VerifyProspectEmailTool(_SalesTool):
    _name = "verify_prospect_email"
    _description = ("Check a prospect's address: verified (published on their site), risky (from the site's own "
                    "pattern), guess, or invalid (no mail server, personal mailbox, opted out). Only verified are sent to.")
    _input = _ProspectRef
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    async def act(self, db, context, owner, data):
        prospect = await prospecting_service.verify(db, context.workspace_id, data["prospect_id"])
        return prospect, f"{prospect['name']}: {prospect['email'] or 'no address'} ({prospect['email_status']})"


class _Sequence(BaseModel):
    prospect_id: str
    steps: int = Field(2, ge=1, le=3)
    offer: Optional[str] = Field(None, description="What is offered (a trial, a call, a discount)")


class DraftOutreachSequenceTool(_SalesTool):
    _name = "draft_outreach_sequence"
    _description = ("Draft a short personal email sequence from the prospect's own signals and the product's real "
                    "facts, with the sender's identity, postal address and opt-out added, edited by No AI Slop. Drafts only.")
    _input = _Sequence

    async def act(self, db, context, owner, data):
        drafted = await prospecting_service.draft_sequence(db, context.workspace_id, data["prospect_id"],
                                                           steps=data["steps"], offer=data.get("offer") or "")
        return drafted, f"{len(drafted['messages'])} email(s) drafted for {drafted['prospect']['name']}"


class _Approve(BaseModel):
    message_ids: List[str] = Field(..., min_length=1, max_length=100)


class ApproveAndSendOutreachTool(_SalesTool):
    _name = "approve_and_send_outreach"
    _description = ("Approve a batch of drafted sales emails and send those that are due (daily limit, weekday office "
                    "hours, verified addresses, never to opt-outs). Sending from Richard's mailbox waits for his approval.")
    _input = _Approve
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS
    _gated = True

    async def act(self, db, context, owner, data):
        result = await prospecting_service.approve(db, context.workspace_id, data["message_ids"],
                                                   approved=data["_approved"])
        return result, f"{result['approved']} approved, {len(result['sent_now'])} sent now, {result['waiting']} waiting"


class _Outbox(BaseModel):
    status: Optional[str] = Field(None, pattern="^(draft|approved|sent|failed|cancelled)$")
    limit: int = Field(50, ge=1, le=200)


class ReadSalesOutboxTool(_SalesTool):
    _name = "read_sales_outbox"
    _description = "List this workspace's sales emails by status (drafts waiting for approval, approved, sent, failed)."
    _input = _Outbox
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        rows = await prospecting_service.outbox(db, context.workspace_id, data.get("status"), data["limit"])
        return {"messages": rows}, f"{len(rows)} message(s)"


class ProcessSalesRepliesTool(_SalesTool):
    _name = "process_sales_replies"
    _description = ("Read replies from the inbox: honour opt-outs at once, set bounces and auto-replies aside, "
                    "classify the rest, stop the sequence, draft an answer for approval and move the CRM deal.")
    _input = BaseModel
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    async def act(self, db, context, owner, data):
        result = await prospecting_service.process_replies(db, context.workspace_id, owner)
        return result, f"{len(result['handled'])} reply(ies) handled, {result['answers_drafted']} answer(s) drafted"


class _Suppress(BaseModel):
    value: str = Field(..., min_length=3, description="An email address or a whole domain")
    reason: str = Field("asked not to be contacted", max_length=200)


class SuppressOutreachContactTool(_SalesTool):
    _name = "suppress_outreach_contact"
    _description = "Never email this address or domain again; stops any sequence to it at once."
    _input = _Suppress

    async def act(self, db, context, owner, data):
        row = await prospecting_service.suppress(db, context.workspace_id, data["value"], data["reason"])
        return row, f"{row['value']} will not be emailed again"


class SalesCampaignReportTool(_SalesTool):
    _name = "sales_campaign_report"
    _description = "The outreach funnel: prospects by stage, reply and positive rates, results by signal, what to change."
    _input = BaseModel
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        report = await prospecting_service.report(db, context.workspace_id)
        return report, (f"{report['contacted']} contacted, {report['reply_rate']:.0%} replied, "
                        f"{report['positive_rate']:.0%} positive")


PROSPECTING_TOOLS = [
    DiscoverProspectCompaniesTool, ReadBuyingSignalsTool, FindDecisionMakersTool, VerifyProspectEmailTool,
    DraftOutreachSequenceTool, ApproveAndSendOutreachTool, ReadSalesOutboxTool, ProcessSalesRepliesTool,
    SuppressOutreachContactTool, SalesCampaignReportTool,
]
