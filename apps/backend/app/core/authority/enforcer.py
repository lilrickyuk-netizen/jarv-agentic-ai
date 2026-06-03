"""
JARV Backend - Authority Enforcer

Core authority enforcement logic for validating and checking authority levels.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
import logging

from app.core.agents.base import AuthorityLevel, AgentAuthorizationError

logger = logging.getLogger(__name__)


class AuthorityCheck(BaseModel):
    """Result of authority check"""
    allowed: bool
    current_level: int
    required_level: int
    reason: Optional[str] = None
    requires_escalation: bool = False
    escalation_reason: Optional[str] = None


class AuthorityEnforcer:
    """
    Enforces authority levels across the system.

    This is the core authority enforcement mechanism that validates whether
    an entity (user, agent, tool) has sufficient authority to perform an action.
    """

    def __init__(self):
        """Initialize authority enforcer"""
        self.logger = logging.getLogger("authority.enforcer")

    def check_authority(
        self,
        current_level: AuthorityLevel,
        required_level: AuthorityLevel,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AuthorityCheck:
        """
        Check if current authority level is sufficient for required level.

        Args:
            current_level: Current authority level
            required_level: Required authority level
            action: Description of action being attempted
            context: Additional context for the check

        Returns:
            AuthorityCheck result indicating if allowed
        """
        context = context or {}

        # Check if authority is sufficient
        if current_level >= required_level:
            self.logger.debug(
                f"Authority check passed: {action}",
                extra={
                    "current_level": current_level.value,
                    "required_level": required_level.value,
                    "action": action,
                }
            )
            return AuthorityCheck(
                allowed=True,
                current_level=current_level.value,
                required_level=required_level.value,
            )

        # Authority insufficient
        self.logger.warning(
            f"Authority check failed: {action}",
            extra={
                "current_level": current_level.value,
                "required_level": required_level.value,
                "action": action,
                "context": context,
            }
        )

        # Check if escalation is possible
        requires_escalation = (
            required_level.value - current_level.value <= 2 and
            required_level.value <= AuthorityLevel.LEVEL_7_DEPLOYMENT.value
        )

        escalation_reason = None
        if requires_escalation:
            escalation_reason = (
                f"Action '{action}' requires authority level {required_level.value} "
                f"but current level is {current_level.value}. "
                f"Escalation request can be submitted for approval."
            )

        return AuthorityCheck(
            allowed=False,
            current_level=current_level.value,
            required_level=required_level.value,
            reason=f"Insufficient authority: requires level {required_level.value}, has level {current_level.value}",
            requires_escalation=requires_escalation,
            escalation_reason=escalation_reason,
        )

    def require_authority(
        self,
        current_level: AuthorityLevel,
        required_level: AuthorityLevel,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Require authority level or raise exception.

        Args:
            current_level: Current authority level
            required_level: Required authority level
            action: Description of action being attempted
            context: Additional context for the check

        Raises:
            AgentAuthorizationError: If authority insufficient
        """
        check = self.check_authority(current_level, required_level, action, context)

        if not check.allowed:
            raise AgentAuthorizationError(
                message=check.reason or f"Insufficient authority for: {action}",
                agent_name="AuthorityEnforcer",
                details={
                    "current_level": check.current_level,
                    "required_level": check.required_level,
                    "action": action,
                    "requires_escalation": check.requires_escalation,
                    "escalation_reason": check.escalation_reason,
                    "context": context or {},
                }
            )

    def check_tool_authority(
        self,
        tool_name: str,
        tool_required_level: AuthorityLevel,
        user_level: AuthorityLevel,
        agent_level: Optional[AuthorityLevel] = None,
    ) -> AuthorityCheck:
        """
        Check if tool can be used with given authority levels.

        The effective authority level is the minimum of user and agent levels.

        Args:
            tool_name: Name of tool being checked
            tool_required_level: Tool's required authority level
            user_level: User's authority level
            agent_level: Agent's authority level (optional)

        Returns:
            AuthorityCheck result
        """
        # Effective authority is minimum of user and agent
        effective_level = user_level
        if agent_level is not None:
            effective_level = min(user_level, agent_level, key=lambda x: x.value)

        return self.check_authority(
            current_level=effective_level,
            required_level=tool_required_level,
            action=f"use tool '{tool_name}'",
            context={
                "tool_name": tool_name,
                "user_level": user_level.value,
                "agent_level": agent_level.value if agent_level else None,
                "effective_level": effective_level.value,
            }
        )

    def check_agent_spawn_authority(
        self,
        parent_level: AuthorityLevel,
        child_required_level: AuthorityLevel,
        child_agent_name: str,
    ) -> AuthorityCheck:
        """
        Check if parent agent can spawn child agent.

        Parent must have authority >= child's required level.

        Args:
            parent_level: Parent agent's authority level
            child_required_level: Child agent's required authority level
            child_agent_name: Name of child agent to spawn

        Returns:
            AuthorityCheck result
        """
        return self.check_authority(
            current_level=parent_level,
            required_level=child_required_level,
            action=f"spawn agent '{child_agent_name}'",
            context={
                "parent_level": parent_level.value,
                "child_required_level": child_required_level.value,
                "child_agent_name": child_agent_name,
            }
        )

    def get_allowed_tools(
        self,
        user_level: AuthorityLevel,
        agent_level: Optional[AuthorityLevel],
        all_tools: Dict[str, AuthorityLevel],
    ) -> List[str]:
        """
        Get list of tools allowed for given authority levels.

        Args:
            user_level: User's authority level
            agent_level: Agent's authority level (optional)
            all_tools: Dict mapping tool names to required authority levels

        Returns:
            List of allowed tool names
        """
        effective_level = user_level
        if agent_level is not None:
            effective_level = min(user_level, agent_level, key=lambda x: x.value)

        allowed = []
        for tool_name, required_level in all_tools.items():
            if effective_level >= required_level:
                allowed.append(tool_name)

        self.logger.debug(
            f"Calculated allowed tools for level {effective_level.value}",
            extra={
                "effective_level": effective_level.value,
                "total_tools": len(all_tools),
                "allowed_tools": len(allowed),
            }
        )

        return allowed


# Global enforcer instance
_enforcer = AuthorityEnforcer()


def check_authority(
    current_level: AuthorityLevel,
    required_level: AuthorityLevel,
    action: str,
    context: Optional[Dict[str, Any]] = None,
) -> AuthorityCheck:
    """
    Global function to check authority.

    Args:
        current_level: Current authority level
        required_level: Required authority level
        action: Description of action
        context: Additional context

    Returns:
        AuthorityCheck result
    """
    return _enforcer.check_authority(current_level, required_level, action, context)


def require_authority(
    current_level: AuthorityLevel,
    required_level: AuthorityLevel,
    action: str,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Global function to require authority or raise exception.

    Args:
        current_level: Current authority level
        required_level: Required authority level
        action: Description of action
        context: Additional context

    Raises:
        AgentAuthorizationError: If authority insufficient
    """
    _enforcer.require_authority(current_level, required_level, action, context)
