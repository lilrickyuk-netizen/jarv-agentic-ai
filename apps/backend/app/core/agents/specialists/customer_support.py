"""
JARV Backend - CustomerSupportAgent

Works the workspace's support inbox through the support tools
(app.tools.business, backed by app.core.business.support): reads tickets,
categorises them (severe bugs go to the debugging agent), drafts replies from
the FAQ and the product's facts, keeps the FAQ current, and sends a reply only
when a workspace rule allows it or Richard approves it.

- With a model provider and a workspace, it works through those tools.
- Without one, it drafts the reply for the given ticket directly.
- With no database session there is no inbox to work from, and it says so.
"""
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentContext, AgentResult, AuthorityLevel

SUPPORT_TOOLS = ["read_support_messages", "create_ticket", "categorise_ticket", "draft_reply",
                 "send_standard_reply_with_rules", "update_faq", "summarise_feedback", "update_knowledge_base",
                 "create_help_article", "memory_search"]


class CustomerSupportAgentInput(BaseModel):
    """CustomerSupportAgent input"""
    ticket_id: str = Field(..., description="Ticket id or number to reply to")
    workspace_id: Optional[str] = Field(None, description="Workspace context")
    include_kb_search: bool = Field(default=True, description="Use the FAQ and knowledge base")
    tone: str = Field(default="friendly", description="Response tone")


class CustomerSupportAgentOutput(BaseModel):
    """CustomerSupportAgent output"""
    draft_reply: str = Field(default="", description="Drafted reply (not sent)")
    confidence_score: float = Field(default=0.0, description="How well the FAQ covers the question (0-1)")
    kb_articles_used: List[str] = Field(default_factory=list, description="FAQ/knowledge-base articles used")
    suggested_actions: List[str] = Field(default_factory=list, description="Suggested next steps")
    escalation_recommended: bool = Field(default=False, description="Whether engineering should look at it")
    template_fallback_used: bool = Field(default=False, description="Drafted without a model")
    ai_model_used: str = Field(default="", description="Model that wrote the draft, if any")


class CustomerSupportAgent(AgentBase):
    """Customer support on the persisted inbox."""

    @property
    def name(self) -> str:
        return "customer_support"

    @property
    def role(self) -> str:
        return "Answers customers from the support inbox, FAQ and product facts; escalates real bugs"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CustomerSupportAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CustomerSupportAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def default_tools(self) -> list[str]:
        return list(SUPPORT_TOOLS)

    async def run(self, input_data: Dict[str, Any], context: AgentContext) -> AgentResult:
        if context.db_session is None or context.workspace_id is None:
            return self.create_result(
                success=True,
                result_data={"draft_reply": "", "confidence_score": 0.0, "kb_articles_used": [],
                             "suggested_actions": ["Run this inside a workspace so the ticket can be read from its inbox"],
                             "escalation_recommended": False, "template_fallback_used": False, "ai_model_used": "",
                             "limitations": ["No database session: there is no support inbox to read the ticket from."]},
                output_text="No support inbox available in this run; no reply was drafted.")
        if self.tools_enabled(context):
            outcome = await self.use_tools(
                context, f"Ticket: {input_data.get('ticket_id')}\nTone: {input_data.get('tone') or 'friendly'}",
                instructions=_INSTRUCTIONS, max_steps=12)
            return self.result_from_tools(outcome, mode="tools")
        from app.core.business.support import support_service, view

        try:
            draft = await support_service.draft_reply(context.db_session, context.workspace_id,
                                                      input_data["ticket_id"], tone=input_data.get("tone") or "friendly")
            ticket = view(await support_service._ticket(context.db_session, context.workspace_id,
                                                        input_data["ticket_id"]))
        except LookupError:
            # Nothing to answer: report it plainly rather than drafting to no one.
            return self.create_result(
                success=True,
                result_data={"draft_reply": "", "confidence_score": 0.0, "kb_articles_used": [],
                             "suggested_actions": ["Create the ticket (create_ticket or POST /api/support/{workspace}/tickets) "
                                                   "and run this again"],
                             "escalation_recommended": False, "template_fallback_used": False, "ai_model_used": "",
                             "limitations": [f"No ticket '{input_data.get('ticket_id')}' in this workspace's inbox."]},
                output_text=f"No ticket '{input_data.get('ticket_id')}' in this workspace's inbox; nothing drafted.")
        except ValueError as exc:
            return self.create_result(success=False, result_data={}, error_message=str(exc))
        escalate = ticket["category"] == "bug" and ticket["severity"] in ("high", "critical")
        actions = []
        if escalate:
            actions.append(f"Engineering task {ticket['escalation_task_id']} is open for this bug")
        if draft["confidence"] < 0.6:
            actions.append("The FAQ does not answer this well: review the draft and add an FAQ entry")
        actions.append("Send with send_standard_reply_with_rules (a support_reply rule or Richard's approval)")
        model = draft["generated_by"][6:] if draft["generated_by"].startswith("model:") else ""
        return self.create_result(
            success=True,
            result_data={"draft_reply": draft["body"], "confidence_score": draft["confidence"],
                         "kb_articles_used": draft["faq_ids"], "suggested_actions": actions,
                         "escalation_recommended": escalate, "template_fallback_used": not model,
                         "ai_model_used": model, "ticket": ticket},
            output_text=f"Reply drafted for {ticket['number']} (confidence {draft['confidence']:.2f}); not sent.",
            tools_used=["draft_reply"], requires_approval=True)


_INSTRUCTIONS = (
    "Work this support ticket: read it with read_support_messages, check categorise_ticket, draft the reply with "
    "draft_reply. Answer only from the FAQ, knowledge base and product facts; never promise refunds, dates or "
    "features. If the answer is missing from the FAQ and you can state it from facts, add it with update_faq. Send "
    "only with send_standard_reply_with_rules (it pauses for Richard unless a rule allows it). Summarise what you did.")
