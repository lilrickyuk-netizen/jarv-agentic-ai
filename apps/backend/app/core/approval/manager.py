"""
JARV Backend - Approval Manager

Manages approval requests for risky operations.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ApprovalStatus(str, Enum):
    """Status of approval request"""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalRequest(BaseModel):
    """Request for approval of an action"""
    request_id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    workspace_id: Optional[UUID] = None
    agent_name: Optional[str] = None
    tool_name: Optional[str] = None
    action_type: str
    action_description: str
    risk_level: str = Field(..., description="low, medium, high, critical")
    estimated_impact: Optional[str] = None
    justification: str
    context: Dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(
        default_factory=lambda: datetime.utcnow() + timedelta(hours=24)
    )
    reviewed_by: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    review_comment: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApprovalResponse(BaseModel):
    """Response to approval request"""
    request_id: UUID
    status: ApprovalStatus
    approved: bool
    comment: Optional[str] = None
    expires_at: Optional[datetime] = None


class ApprovalManager:
    """
    Manages approval requests for risky operations.

    Handles creating, reviewing, and tracking approval requests.
    """

    def __init__(self):
        """Initialize approval manager"""
        self.logger = logging.getLogger("approval.manager")

    async def request_approval(
        self,
        user_id: UUID,
        action_type: str,
        action_description: str,
        risk_level: str,
        justification: str,
        workspace_id: Optional[UUID] = None,
        agent_name: Optional[str] = None,
        tool_name: Optional[str] = None,
        estimated_impact: Optional[str] = None,
        expires_hours: int = 24,
        context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        """
        Request approval for an action.

        In production: Store in BoundaryApproval table and notify approvers.

        Args:
            user_id: User requesting approval
            action_type: Type of action (e.g., "file_delete", "database_write")
            action_description: Description of action
            risk_level: Risk level (low, medium, high, critical)
            justification: Why this action is needed
            workspace_id: Optional workspace context
            agent_name: Agent requesting approval
            tool_name: Tool that will perform action
            estimated_impact: Estimated impact description
            expires_hours: Hours until request expires
            context: Additional context
            metadata: Additional metadata

        Returns:
            ApprovalRequest
        """
        try:
            request = ApprovalRequest(
                user_id=user_id,
                workspace_id=workspace_id,
                agent_name=agent_name,
                tool_name=tool_name,
                action_type=action_type,
                action_description=action_description,
                risk_level=risk_level,
                estimated_impact=estimated_impact,
                justification=justification,
                expires_at=datetime.utcnow() + timedelta(hours=expires_hours),
                context=context or {},
                metadata=metadata or {},
            )

            # In production: Store in database
            # from app.models.boundary import BoundaryApproval
            # from app.core.database import get_db
            # async with get_db() as db:
            #     approval = BoundaryApproval(
            #         id=request.request_id,
            #         user_id=request.user_id,
            #         workspace_id=request.workspace_id,
            #         agent_name=request.agent_name,
            #         tool_name=request.tool_name,
            #         action_type=request.action_type,
            #         action_description=request.action_description,
            #         risk_level=request.risk_level,
            #         status=request.status,
            #         justification=request.justification,
            #         context=request.context,
            #         metadata=request.metadata,
            #         expires_at=request.expires_at,
            #     )
            #     db.add(approval)
            #     await db.commit()
            #
            #     # Notify approvers based on risk level
            #     await notify_approvers(request)

            self.logger.info(
                f"Approval requested: {action_description}",
                extra={
                    "request_id": str(request.request_id),
                    "user_id": str(user_id),
                    "action_type": action_type,
                    "risk_level": risk_level,
                }
            )

            return request

        except Exception as e:
            self.logger.error(
                f"Failed to request approval: {e}",
                extra={"user_id": str(user_id), "action_type": action_type},
                exc_info=True
            )
            raise

    async def approve(
        self,
        request_id: UUID,
        approved_by: UUID,
        comment: Optional[str] = None,
        expires_hours: int = 1,
    ) -> ApprovalResponse:
        """
        Approve an action request.

        In production: Update BoundaryApproval table.

        Args:
            request_id: Approval request ID
            approved_by: User approving the request
            comment: Optional approval comment
            expires_hours: Hours until approval expires

        Returns:
            ApprovalResponse
        """
        try:
            # In production: Update database
            # from app.models.boundary import BoundaryApproval
            # from app.core.database import get_db
            # async with get_db() as db:
            #     approval = await db.get(BoundaryApproval, request_id)
            #     if not approval:
            #         raise ValueError(f"Approval request not found: {request_id}")
            #
            #     if approval.status != ApprovalStatus.PENDING:
            #         raise ValueError(f"Request already {approval.status}")
            #
            #     approval.status = ApprovalStatus.APPROVED
            #     approval.reviewed_by = approved_by
            #     approval.reviewed_at = datetime.utcnow()
            #     approval.review_comment = comment
            #     approval.metadata["approval_expires_at"] = (
            #         datetime.utcnow() + timedelta(hours=expires_hours)
            #     ).isoformat()
            #
            #     await db.commit()

            expires_at = datetime.utcnow() + timedelta(hours=expires_hours)

            response = ApprovalResponse(
                request_id=request_id,
                status=ApprovalStatus.APPROVED,
                approved=True,
                comment=comment,
                expires_at=expires_at,
            )

            self.logger.info(
                f"Approval granted",
                extra={
                    "request_id": str(request_id),
                    "approved_by": str(approved_by),
                    "expires_at": expires_at.isoformat(),
                }
            )

            return response

        except Exception as e:
            self.logger.error(
                f"Failed to approve request: {e}",
                extra={"request_id": str(request_id)},
                exc_info=True
            )
            raise

    async def deny(
        self,
        request_id: UUID,
        denied_by: UUID,
        comment: Optional[str] = None,
    ) -> ApprovalResponse:
        """
        Deny an action request.

        In production: Update BoundaryApproval table.

        Args:
            request_id: Approval request ID
            denied_by: User denying the request
            comment: Optional denial comment

        Returns:
            ApprovalResponse
        """
        try:
            # In production: Update database
            # from app.models.boundary import BoundaryApproval
            # from app.core.database import get_db
            # async with get_db() as db:
            #     approval = await db.get(BoundaryApproval, request_id)
            #     approval.status = ApprovalStatus.DENIED
            #     approval.reviewed_by = denied_by
            #     approval.reviewed_at = datetime.utcnow()
            #     approval.review_comment = comment
            #     await db.commit()

            response = ApprovalResponse(
                request_id=request_id,
                status=ApprovalStatus.DENIED,
                approved=False,
                comment=comment,
            )

            self.logger.info(
                f"Approval denied",
                extra={
                    "request_id": str(request_id),
                    "denied_by": str(denied_by),
                }
            )

            return response

        except Exception as e:
            self.logger.error(
                f"Failed to deny request: {e}",
                extra={"request_id": str(request_id)},
                exc_info=True
            )
            raise

    async def cancel(
        self,
        request_id: UUID,
        cancelled_by: UUID,
        reason: Optional[str] = None,
    ) -> ApprovalResponse:
        """
        Cancel an approval request.

        In production: Update BoundaryApproval table.

        Args:
            request_id: Approval request ID
            cancelled_by: User cancelling the request
            reason: Optional cancellation reason

        Returns:
            ApprovalResponse
        """
        try:
            # In production: Update database
            # from app.models.boundary import BoundaryApproval
            # from app.core.database import get_db
            # async with get_db() as db:
            #     approval = await db.get(BoundaryApproval, request_id)
            #     approval.status = ApprovalStatus.CANCELLED
            #     approval.metadata["cancelled_by"] = str(cancelled_by)
            #     approval.metadata["cancel_reason"] = reason
            #     approval.metadata["cancelled_at"] = datetime.utcnow().isoformat()
            #     await db.commit()

            response = ApprovalResponse(
                request_id=request_id,
                status=ApprovalStatus.CANCELLED,
                approved=False,
                comment=f"Cancelled: {reason}" if reason else "Cancelled",
            )

            self.logger.info(
                f"Approval cancelled",
                extra={
                    "request_id": str(request_id),
                    "cancelled_by": str(cancelled_by),
                }
            )

            return response

        except Exception as e:
            self.logger.error(
                f"Failed to cancel request: {e}",
                extra={"request_id": str(request_id)},
                exc_info=True
            )
            raise

    async def get_request(
        self,
        request_id: UUID,
    ) -> Optional[ApprovalRequest]:
        """
        Get approval request by ID.

        In production: Query BoundaryApproval table.

        Args:
            request_id: Request ID

        Returns:
            ApprovalRequest if found
        """
        try:
            # In production: Query database
            # from app.models.boundary import BoundaryApproval
            # from app.core.database import get_db
            # async with get_db() as db:
            #     approval = await db.get(BoundaryApproval, request_id)
            #     if approval:
            #         return ApprovalRequest.from_orm(approval)

            self.logger.debug(
                f"Retrieved approval request {request_id}",
                extra={"request_id": str(request_id)}
            )

            return None

        except Exception as e:
            self.logger.error(
                f"Failed to get request: {e}",
                extra={"request_id": str(request_id)},
                exc_info=True
            )
            return None

    async def get_pending_requests(
        self,
        user_id: Optional[UUID] = None,
        workspace_id: Optional[UUID] = None,
        risk_level: Optional[str] = None,
    ) -> List[ApprovalRequest]:
        """
        Get pending approval requests.

        In production: Query BoundaryApproval table.

        Args:
            user_id: Optional filter by user
            workspace_id: Optional filter by workspace
            risk_level: Optional filter by risk level

        Returns:
            List of pending requests
        """
        try:
            # In production: Query database
            # from app.models.boundary import BoundaryApproval
            # from app.core.database import get_db
            # async with get_db() as db:
            #     query = select(BoundaryApproval).where(
            #         BoundaryApproval.status == ApprovalStatus.PENDING
            #     ).where(
            #         BoundaryApproval.expires_at > datetime.utcnow()
            #     )
            #     if user_id:
            #         query = query.where(BoundaryApproval.user_id == user_id)
            #     if workspace_id:
            #         query = query.where(BoundaryApproval.workspace_id == workspace_id)
            #     if risk_level:
            #         query = query.where(BoundaryApproval.risk_level == risk_level)
            #
            #     results = await db.execute(query.order_by(BoundaryApproval.created_at.desc()))
            #     return [ApprovalRequest.from_orm(row) for row in results]

            self.logger.debug(
                "Retrieved pending approval requests",
                extra={
                    "user_id": str(user_id) if user_id else None,
                    "workspace_id": str(workspace_id) if workspace_id else None,
                    "risk_level": risk_level,
                }
            )

            return []

        except Exception as e:
            self.logger.error(
                f"Failed to get pending requests: {e}",
                exc_info=True
            )
            return []

    async def expire_old_requests(self) -> int:
        """
        Expire requests that have passed their expiration time.

        In production: Run as periodic task.

        Returns:
            Number of requests expired
        """
        try:
            # In production: Update database
            # from app.models.boundary import BoundaryApproval
            # from app.core.database import get_db
            # async with get_db() as db:
            #     expired = await db.execute(
            #         update(BoundaryApproval)
            #         .where(BoundaryApproval.status == ApprovalStatus.PENDING)
            #         .where(BoundaryApproval.expires_at < datetime.utcnow())
            #         .values(status=ApprovalStatus.EXPIRED)
            #     )
            #     await db.commit()
            #     return expired.rowcount

            self.logger.debug("Expired old approval requests")
            return 0

        except Exception as e:
            self.logger.error(
                f"Failed to expire requests: {e}",
                exc_info=True
            )
            return 0
