"""
JARV Backend - Agent System

Core agent infrastructure for the JARV multi-agent system.
"""
from app.core.agents.base import (
    AgentBase,
    AgentConfig,
    AgentContext,
    AgentResult,
    AgentError,
    AgentValidationError,
    AgentExecutionError,
    AgentAuthorizationError,
    AuthorityLevel,
)
from app.core.agents.registry import (
    AgentRegistry,
    AgentMetadata,
    get_registry,
    register_agent,
    create_agent,
    list_agents,
)

__all__ = [
    # Base classes
    "AgentBase",
    "AgentConfig",
    "AgentContext",
    "AgentResult",
    "AuthorityLevel",
    # Exceptions
    "AgentError",
    "AgentValidationError",
    "AgentExecutionError",
    "AgentAuthorizationError",
    # Registry
    "AgentRegistry",
    "AgentMetadata",
    "get_registry",
    "register_agent",
    "create_agent",
    "list_agents",
]
