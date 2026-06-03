"""
JARV Backend - Customer Support System

Comprehensive customer support with tickets, knowledge base, and agent integration.
"""
from app.core.support.tickets import TicketManager, TicketPriority, TicketStatus
from app.core.support.knowledge_base import KnowledgeBase
from app.core.support.responses import ResponseTemplates

__all__ = [
    "TicketManager",
    "TicketPriority",
    "TicketStatus",
    "KnowledgeBase",
    "ResponseTemplates",
]
