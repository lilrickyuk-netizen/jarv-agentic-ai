"""
JARV Backend - Support Ticket System

Complete ticket management for customer support operations.
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import uuid
import logging

logger = logging.getLogger(__name__)


class TicketPriority(str, Enum):
    """Ticket priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class TicketStatus(str, Enum):
    """Ticket status"""
    NEW = "new"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_CUSTOMER = "waiting_customer"
    WAITING_INTERNAL = "waiting_internal"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketCategory(str, Enum):
    """Ticket categories"""
    BUG = "bug"
    FEATURE_REQUEST = "feature_request"
    QUESTION = "question"
    ACCOUNT = "account"
    BILLING = "billing"
    TECHNICAL = "technical"
    OTHER = "other"


@dataclass
class TicketMessage:
    """A message in a ticket conversation"""
    message_id: str
    ticket_id: str
    sender: str  # user_id or "system" or "agent"
    sender_type: str  # "customer", "agent", "system"
    content: str
    created_at: datetime
    attachments: List[str] = field(default_factory=list)
    is_internal: bool = False  # Internal notes not visible to customer


@dataclass
class TicketMetrics:
    """Metrics for a ticket"""
    first_response_time: Optional[float] = None  # seconds
    resolution_time: Optional[float] = None  # seconds
    customer_satisfaction: Optional[float] = None  # 1-5 rating
    response_count: int = 0
    reopened_count: int = 0


@dataclass
class Ticket:
    """Support ticket"""
    ticket_id: str
    ticket_number: int  # Human-readable sequential number
    subject: str
    description: str
    customer_id: str
    customer_email: str
    customer_name: str
    status: TicketStatus
    priority: TicketPriority
    category: TicketCategory
    assigned_to: Optional[str] = None  # agent_id
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    messages: List[TicketMessage] = field(default_factory=list)
    metrics: TicketMetrics = field(default_factory=TicketMetrics)
    sla_due_at: Optional[datetime] = None
    custom_fields: Dict[str, Any] = field(default_factory=dict)


class TicketManager:
    """
    Comprehensive ticket management system.

    Handles creation, assignment, tracking, and resolution of customer support tickets.
    """

    # SLA times by priority (in hours)
    SLA_TIMES = {
        TicketPriority.CRITICAL: 1,
        TicketPriority.URGENT: 4,
        TicketPriority.HIGH: 8,
        TicketPriority.MEDIUM: 24,
        TicketPriority.LOW: 48,
    }

    def __init__(self):
        """Initialize ticket manager"""
        self.logger = logging.getLogger(__name__)

        # In-memory storage (in production: use database)
        self.tickets: Dict[str, Ticket] = {}
        self.ticket_counter = 1000  # Start at 1000 for ticket numbers

    def create_ticket(
        self,
        subject: str,
        description: str,
        customer_id: str,
        customer_email: str,
        customer_name: str,
        priority: TicketPriority = TicketPriority.MEDIUM,
        category: TicketCategory = TicketCategory.QUESTION,
        tags: List[str] = None,
        custom_fields: Dict[str, Any] = None,
    ) -> Ticket:
        """
        Create a new support ticket.

        Args:
            subject: Ticket subject
            description: Detailed description
            customer_id: Customer user ID
            customer_email: Customer email
            customer_name: Customer name
            priority: Ticket priority
            category: Ticket category
            tags: List of tags
            custom_fields: Custom metadata

        Returns:
            Created ticket
        """
        ticket_id = str(uuid.uuid4())
        ticket_number = self.ticket_counter
        self.ticket_counter += 1

        now = datetime.utcnow()

        # Calculate SLA due time
        sla_hours = self.SLA_TIMES.get(priority, 24)
        sla_due_at = now + timedelta(hours=sla_hours)

        # Create initial message
        initial_message = TicketMessage(
            message_id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            sender=customer_id,
            sender_type="customer",
            content=description,
            created_at=now,
        )

        ticket = Ticket(
            ticket_id=ticket_id,
            ticket_number=ticket_number,
            subject=subject,
            description=description,
            customer_id=customer_id,
            customer_email=customer_email,
            customer_name=customer_name,
            status=TicketStatus.NEW,
            priority=priority,
            category=category,
            created_at=now,
            updated_at=now,
            tags=tags or [],
            messages=[initial_message],
            sla_due_at=sla_due_at,
            custom_fields=custom_fields or {},
        )

        self.tickets[ticket_id] = ticket
        self.logger.info(f"Created ticket #{ticket_number}: {subject}")

        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        """Get ticket by ID"""
        return self.tickets.get(ticket_id)

    def get_ticket_by_number(self, ticket_number: int) -> Optional[Ticket]:
        """Get ticket by human-readable number"""
        for ticket in self.tickets.values():
            if ticket.ticket_number == ticket_number:
                return ticket
        return None

    def add_message(
        self,
        ticket_id: str,
        sender: str,
        sender_type: str,
        content: str,
        attachments: List[str] = None,
        is_internal: bool = False,
    ) -> Optional[TicketMessage]:
        """
        Add a message to a ticket.

        Args:
            ticket_id: Ticket ID
            sender: Sender ID (user_id, agent_id, or "system")
            sender_type: "customer", "agent", or "system"
            content: Message content
            attachments: List of attachment URLs/IDs
            is_internal: Whether message is internal note

        Returns:
            Created message or None if ticket not found
        """
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            return None

        message = TicketMessage(
            message_id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            sender=sender,
            sender_type=sender_type,
            content=content,
            created_at=datetime.utcnow(),
            attachments=attachments or [],
            is_internal=is_internal,
        )

        ticket.messages.append(message)
        ticket.updated_at = datetime.utcnow()
        ticket.metrics.response_count += 1

        # Calculate first response time if this is first agent response
        if sender_type == "agent" and ticket.metrics.first_response_time is None:
            time_since_creation = (datetime.utcnow() - ticket.created_at).total_seconds()
            ticket.metrics.first_response_time = time_since_creation

        self.logger.info(f"Added message to ticket #{ticket.ticket_number} from {sender_type}")

        return message

    def update_ticket(
        self,
        ticket_id: str,
        status: Optional[TicketStatus] = None,
        priority: Optional[TicketPriority] = None,
        assigned_to: Optional[str] = None,
        tags: Optional[List[str]] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> Optional[Ticket]:
        """
        Update ticket properties.

        Args:
            ticket_id: Ticket ID
            status: New status
            priority: New priority
            assigned_to: Agent to assign to
            tags: New tags
            custom_fields: Custom fields to update

        Returns:
            Updated ticket or None if not found
        """
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            return None

        now = datetime.utcnow()
        changes = []

        if status is not None and status != ticket.status:
            old_status = ticket.status
            ticket.status = status
            changes.append(f"status: {old_status.value} -> {status.value}")

            # Track resolution/closure times
            if status == TicketStatus.RESOLVED:
                ticket.resolved_at = now
                resolution_time = (now - ticket.created_at).total_seconds()
                ticket.metrics.resolution_time = resolution_time
            elif status == TicketStatus.CLOSED:
                ticket.closed_at = now

            # Track reopens
            if old_status in [TicketStatus.RESOLVED, TicketStatus.CLOSED] and status not in [TicketStatus.RESOLVED, TicketStatus.CLOSED]:
                ticket.metrics.reopened_count += 1

        if priority is not None and priority != ticket.priority:
            ticket.priority = priority
            changes.append(f"priority: {priority.value}")

            # Recalculate SLA
            sla_hours = self.SLA_TIMES.get(priority, 24)
            ticket.sla_due_at = ticket.created_at + timedelta(hours=sla_hours)

        if assigned_to is not None:
            ticket.assigned_to = assigned_to
            changes.append(f"assigned to: {assigned_to}")

        if tags is not None:
            ticket.tags = tags
            changes.append("tags updated")

        if custom_fields is not None:
            ticket.custom_fields.update(custom_fields)
            changes.append("custom fields updated")

        ticket.updated_at = now

        self.logger.info(f"Updated ticket #{ticket.ticket_number}: {', '.join(changes)}")

        return ticket

    def search_tickets(
        self,
        customer_id: Optional[str] = None,
        assigned_to: Optional[str] = None,
        status: Optional[TicketStatus] = None,
        priority: Optional[TicketPriority] = None,
        category: Optional[TicketCategory] = None,
        tags: Optional[List[str]] = None,
        search_text: Optional[str] = None,
        sla_breached: Optional[bool] = None,
    ) -> List[Ticket]:
        """
        Search tickets with various filters.

        Args:
            customer_id: Filter by customer
            assigned_to: Filter by assigned agent
            status: Filter by status
            priority: Filter by priority
            category: Filter by category
            tags: Filter by tags
            search_text: Search in subject/description
            sla_breached: Filter by SLA breach status

        Returns:
            List of matching tickets
        """
        results = list(self.tickets.values())

        if customer_id:
            results = [t for t in results if t.customer_id == customer_id]

        if assigned_to:
            results = [t for t in results if t.assigned_to == assigned_to]

        if status:
            results = [t for t in results if t.status == status]

        if priority:
            results = [t for t in results if t.priority == priority]

        if category:
            results = [t for t in results if t.category == category]

        if tags:
            results = [
                t for t in results
                if any(tag in t.tags for tag in tags)
            ]

        if search_text:
            search_lower = search_text.lower()
            results = [
                t for t in results
                if search_lower in t.subject.lower()
                or search_lower in t.description.lower()
            ]

        if sla_breached is not None:
            now = datetime.utcnow()
            if sla_breached:
                results = [
                    t for t in results
                    if t.sla_due_at and now > t.sla_due_at and t.status not in [TicketStatus.RESOLVED, TicketStatus.CLOSED]
                ]
            else:
                results = [
                    t for t in results
                    if not t.sla_due_at or now <= t.sla_due_at or t.status in [TicketStatus.RESOLVED, TicketStatus.CLOSED]
                ]

        # Sort by created_at descending (newest first)
        results.sort(key=lambda t: t.created_at, reverse=True)

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get ticket system statistics"""
        tickets = list(self.tickets.values())

        status_counts = {}
        for status in TicketStatus:
            count = sum(1 for t in tickets if t.status == status)
            if count > 0:
                status_counts[status.value] = count

        priority_counts = {}
        for priority in TicketPriority:
            count = sum(1 for t in tickets if t.priority == priority)
            if count > 0:
                priority_counts[priority.value] = count

        category_counts = {}
        for category in TicketCategory:
            count = sum(1 for t in tickets if t.category == category)
            if count > 0:
                category_counts[category.value] = count

        # Calculate average metrics
        resolved_tickets = [t for t in tickets if t.metrics.resolution_time is not None]
        avg_resolution_time = (
            sum(t.metrics.resolution_time for t in resolved_tickets) / len(resolved_tickets)
            if resolved_tickets else 0
        )

        response_tickets = [t for t in tickets if t.metrics.first_response_time is not None]
        avg_first_response = (
            sum(t.metrics.first_response_time for t in response_tickets) / len(response_tickets)
            if response_tickets else 0
        )

        # SLA breach count
        now = datetime.utcnow()
        sla_breached = sum(
            1 for t in tickets
            if t.sla_due_at and now > t.sla_due_at and t.status not in [TicketStatus.RESOLVED, TicketStatus.CLOSED]
        )

        return {
            "total_tickets": len(tickets),
            "by_status": status_counts,
            "by_priority": priority_counts,
            "by_category": category_counts,
            "avg_resolution_time_seconds": round(avg_resolution_time, 2),
            "avg_resolution_time_hours": round(avg_resolution_time / 3600, 2),
            "avg_first_response_seconds": round(avg_first_response, 2),
            "avg_first_response_minutes": round(avg_first_response / 60, 2),
            "sla_breached_count": sla_breached,
            "total_messages": sum(len(t.messages) for t in tickets),
        }


# Global ticket manager instance
_ticket_manager: Optional[TicketManager] = None


def get_ticket_manager() -> TicketManager:
    """Get global ticket manager instance"""
    global _ticket_manager
    if _ticket_manager is None:
        _ticket_manager = TicketManager()
    return _ticket_manager
