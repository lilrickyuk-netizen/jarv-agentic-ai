"""
JARV Backend - Authority System

System for enforcing authority levels and permissions across agents and tools.
"""
from app.core.authority.enforcer import AuthorityEnforcer, check_authority, require_authority
from app.core.authority.manager import AuthorityManager
from app.core.authority.escalation import EscalationRequest, request_escalation

__all__ = [
    "AuthorityEnforcer",
    "check_authority",
    "require_authority",
    "AuthorityManager",
    "EscalationRequest",
    "request_escalation",
]
