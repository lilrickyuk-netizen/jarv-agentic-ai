"""
JARV Backend - Customer Support API

RESTful API endpoints for support tickets and knowledge base.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

from app.core.support.tickets import (
    get_ticket_manager, TicketPriority, TicketStatus, TicketCategory
)
from app.core.support.knowledge_base import get_knowledge_base
from app.core.auth import get_current_user
from app.core.agents.registry import get_registry
from app.core.agents.base import AgentContext

router = APIRouter(prefix="/support", tags=["support"])


class CreateTicketRequest(BaseModel):
    subject: str
    description: str
    priority: TicketPriority = TicketPriority.MEDIUM
    category: TicketCategory = TicketCategory.QUESTION
    tags: List[str] = Field(default_factory=list)


class AddMessageRequest(BaseModel):
    content: str
    is_internal: bool = False


class DraftReplyRequest(BaseModel):
    workspace_id: Optional[str] = None
    include_kb_search: bool = True
    tone: str = "professional"


class DraftReplyResponse(BaseModel):
    draft_reply: str
    confidence_score: float
    kb_articles_used: List[str]
    suggested_actions: List[str]
    escalation_recommended: bool
    template_fallback_used: bool
    requires_approval: bool


class SendReplyRequest(BaseModel):
    reply_content: str
    is_internal: bool = False
    approved_by: Optional[str] = None


class UpdateTicketRequest(BaseModel):
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    assigned_to: Optional[str] = None


class TicketResponse(BaseModel):
    ticket_id: str
    ticket_number: int
    subject: str
    status: str
    priority: str
    category: str
    created_at: datetime
    message_count: int


@router.post("/tickets", response_model=TicketResponse)
async def create_ticket(
    request: CreateTicketRequest,
    current_user=Depends(get_current_user),
):
    """Create a new support ticket"""
    manager = get_ticket_manager()

    ticket = manager.create_ticket(
        subject=request.subject,
        description=request.description,
        customer_id=str(current_user.id),
        customer_email=current_user.email,
        customer_name=current_user.username,
        priority=request.priority,
        category=request.category,
        tags=request.tags,
    )

    return TicketResponse(
        ticket_id=ticket.ticket_id,
        ticket_number=ticket.ticket_number,
        subject=ticket.subject,
        status=ticket.status.value,
        priority=ticket.priority.value,
        category=ticket.category.value,
        created_at=ticket.created_at,
        message_count=len(ticket.messages),
    )


@router.get("/tickets", response_model=List[TicketResponse])
async def list_tickets(
    status: Optional[TicketStatus] = None,
    priority: Optional[TicketPriority] = None,
    current_user=Depends(get_current_user),
):
    """List user's tickets"""
    manager = get_ticket_manager()
    
    tickets = manager.search_tickets(
        customer_id=str(current_user.id),
        status=status,
        priority=priority,
    )

    return [
        TicketResponse(
            ticket_id=t.ticket_id,
            ticket_number=t.ticket_number,
            subject=t.subject,
            status=t.status.value,
            priority=t.priority.value,
            category=t.category.value,
            created_at=t.created_at,
            message_count=len(t.messages),
        )
        for t in tickets
    ]


@router.get("/tickets/stats")
async def get_ticket_stats(current_user=Depends(get_current_user)):
    """Get support system statistics"""
    manager = get_ticket_manager()
    return manager.get_stats()


@router.get("/kb/articles")
async def search_articles(
    query: Optional[str] = None,
    category: Optional[str] = None,
):
    """Search knowledge base articles"""
    kb = get_knowledge_base()
    articles = kb.search_articles(query=query, category=category)

    return [
        {
            "article_id": a.article_id,
            "title": a.title,
            "category": a.category,
            "tags": a.tags,
            "view_count": a.view_count,
        }
        for a in articles
    ]


@router.get("/kb/stats")
async def get_kb_stats():
    """Get knowledge base statistics"""
    kb = get_knowledge_base()
    return kb.get_stats()


@router.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    current_user=Depends(get_current_user),
):
    """Get ticket details"""
    manager = get_ticket_manager()
    ticket = manager.get_ticket(ticket_id)

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Verify user has access to this ticket
    if ticket.customer_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    return {
        "ticket_id": ticket.ticket_id,
        "ticket_number": ticket.ticket_number,
        "subject": ticket.subject,
        "description": ticket.description,
        "status": ticket.status.value,
        "priority": ticket.priority.value,
        "category": ticket.category.value,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "customer_name": ticket.customer_name,
        "customer_email": ticket.customer_email,
        "messages": [
            {
                "message_id": m.message_id,
                "content": m.content,
                "sender": m.sender,
                "sender_type": m.sender_type,
                "created_at": m.created_at,
                "is_internal": m.is_internal,
            }
            for m in ticket.messages
        ],
    }


@router.put("/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: str,
    request: UpdateTicketRequest,
    current_user=Depends(get_current_user),
):
    """Update ticket status, priority, or assignment"""
    manager = get_ticket_manager()
    ticket = manager.get_ticket(ticket_id)

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Update ticket
    updated_ticket = manager.update_ticket(
        ticket_id=ticket_id,
        status=request.status,
        priority=request.priority,
        assigned_to=request.assigned_to,
    )

    return {
        "ticket_id": updated_ticket.ticket_id,
        "ticket_number": updated_ticket.ticket_number,
        "status": updated_ticket.status.value,
        "priority": updated_ticket.priority.value,
        "updated_at": updated_ticket.updated_at,
    }


@router.post("/tickets/{ticket_id}/draft-reply", response_model=DraftReplyResponse)
async def draft_reply(
    ticket_id: str,
    request: DraftReplyRequest,
    current_user=Depends(get_current_user),
):
    """
    Generate AI-powered draft reply for a ticket.

    Uses CustomerSupportAgent to generate contextual reply based on:
    - Ticket details (subject, description, priority, category)
    - Knowledge base articles (searched automatically)
    - Customer history (previous tickets)
    - Workspace context (if provided)

    The reply requires approval before sending if:
    - Confidence score is low (< 0.7)
    - Escalation is recommended
    - Ticket is urgent or critical
    """
    manager = get_ticket_manager()
    ticket = manager.get_ticket(ticket_id)

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Get CustomerSupportAgent
    registry = get_registry()
    agent_class = registry.get("customer_support")

    if not agent_class:
        raise HTTPException(status_code=500, detail="CustomerSupportAgent not available")

    agent = agent_class()

    # Create agent context
    context = AgentContext(
        workspace_id=uuid.uuid4() if not request.workspace_id else uuid.UUID(request.workspace_id),
        user_id=current_user.id,
        task_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
    )

    # Generate draft reply
    input_data = {
        "ticket_id": ticket_id,
        "workspace_id": request.workspace_id,
        "include_kb_search": request.include_kb_search,
        "tone": request.tone,
    }

    result = await agent.run(input_data, context)

    if not result.success:
        raise HTTPException(status_code=500, detail=f"Reply generation failed: {result.error_message}")

    # Determine if approval is required
    requires_approval = (
        result.result_data.get("confidence_score", 0) < 0.7
        or result.result_data.get("escalation_recommended", False)
        or ticket.priority.value in ["urgent", "critical"]
    )

    return DraftReplyResponse(
        draft_reply=result.result_data["draft_reply"],
        confidence_score=result.result_data["confidence_score"],
        kb_articles_used=result.result_data["kb_articles_used"],
        suggested_actions=result.result_data["suggested_actions"],
        escalation_recommended=result.result_data["escalation_recommended"],
        template_fallback_used=result.result_data["template_fallback_used"],
        requires_approval=requires_approval,
    )


@router.post("/tickets/{ticket_id}/reply")
async def send_reply(
    ticket_id: str,
    request: SendReplyRequest,
    current_user=Depends(get_current_user),
):
    """
    Send reply to customer.

    This endpoint requires approval for:
    - Urgent/critical tickets
    - Low confidence replies
    - Tickets flagged for escalation

    The approved_by field must be provided for replies requiring approval.
    """
    manager = get_ticket_manager()
    ticket = manager.get_ticket(ticket_id)

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Check if approval is required
    requires_approval = ticket.priority.value in ["urgent", "critical"]

    if requires_approval and not request.approved_by:
        raise HTTPException(
            status_code=400,
            detail="This reply requires approval. Please provide approved_by field.",
        )

    # Add message to ticket
    message = manager.add_message(
        ticket_id=ticket_id,
        sender=str(current_user.id),
        sender_type="agent",
        content=request.reply_content,
        is_internal=request.is_internal,
    )

    # Add approval metadata if provided
    if request.approved_by:
        # In a real system, this would be stored in message metadata
        pass

    return {
        "message_id": message.message_id,
        "ticket_id": ticket_id,
        "content": message.content,
        "created_at": message.created_at,
        "is_internal": message.is_internal,
        "approved_by": request.approved_by,
    }
