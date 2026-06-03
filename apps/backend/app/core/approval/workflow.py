"""
JARV Backend - Approval Workflow

Workflow functions for approval operations.
"""
from typing import Optional, Dict, Any
from uuid import UUID
import logging

from app.core.approval.manager import ApprovalManager, ApprovalRequest, ApprovalResponse

logger = logging.getLogger(__name__)

# Global approval manager
_approval_manager = ApprovalManager()


async def request_approval(
    user_id: UUID,
    action_type: str,
    action_description: str,
    risk_level: str,
    justification: str,
    **kwargs
) -> ApprovalRequest:
    """
    Global function to request approval.

    Args:
        user_id: User requesting approval
        action_type: Type of action
        action_description: Description of action
        risk_level: Risk level (low, medium, high, critical)
        justification: Justification for action
        **kwargs: Additional parameters

    Returns:
        ApprovalRequest
    """
    return await _approval_manager.request_approval(
        user_id=user_id,
        action_type=action_type,
        action_description=action_description,
        risk_level=risk_level,
        justification=justification,
        **kwargs
    )


async def approve_action(
    request_id: UUID,
    approved_by: UUID,
    comment: Optional[str] = None,
    **kwargs
) -> ApprovalResponse:
    """
    Global function to approve an action.

    Args:
        request_id: Approval request ID
        approved_by: User approving
        comment: Optional comment
        **kwargs: Additional parameters

    Returns:
        ApprovalResponse
    """
    return await _approval_manager.approve(
        request_id=request_id,
        approved_by=approved_by,
        comment=comment,
        **kwargs
    )


async def deny_action(
    request_id: UUID,
    denied_by: UUID,
    comment: Optional[str] = None,
) -> ApprovalResponse:
    """
    Global function to deny an action.

    Args:
        request_id: Approval request ID
        denied_by: User denying
        comment: Optional comment

    Returns:
        ApprovalResponse
    """
    return await _approval_manager.deny(
        request_id=request_id,
        denied_by=denied_by,
        comment=comment,
    )


class ApprovalWorkflow:
    """
    High-level approval workflow orchestration.

    Provides convenience methods for common approval patterns.
    """

    def __init__(self):
        """Initialize approval workflow"""
        self.manager = _approval_manager
        self.logger = logging.getLogger("approval.workflow")

    async def auto_approve_if_safe(
        self,
        user_id: UUID,
        action_type: str,
        action_description: str,
        risk_level: str,
        **kwargs
    ) -> tuple[bool, Optional[ApprovalRequest]]:
        """
        Auto-approve if action is safe enough, otherwise request approval.

        Args:
            user_id: User requesting
            action_type: Action type
            action_description: Action description
            risk_level: Risk level
            **kwargs: Additional parameters

        Returns:
            Tuple of (auto_approved, request_if_not_approved)
        """
        # Auto-approve low risk actions
        if risk_level == "low":
            self.logger.info(
                f"Auto-approved low risk action: {action_description}",
                extra={"user_id": str(user_id), "action_type": action_type}
            )
            return True, None

        # Request approval for higher risk
        request = await self.manager.request_approval(
            user_id=user_id,
            action_type=action_type,
            action_description=action_description,
            risk_level=risk_level,
            justification=kwargs.get("justification", "Requested by user"),
            **kwargs
        )

        return False, request
