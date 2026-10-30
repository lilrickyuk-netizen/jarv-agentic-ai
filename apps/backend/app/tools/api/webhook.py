"""
JARV Backend - Webhook Tools

Tools for registering and managing webhook endpoints.

Webhooks allow external services to notify JARV of events.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field, HttpUrl
import logging
from datetime import datetime
from uuid import UUID, uuid4
import hashlib
from sqlalchemy import select

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.tools.memory.storage import _memory_scope
from app.models.integrations import WebhookEndpoint

logger = logging.getLogger(__name__)


# ===== WEBHOOK REGISTER TOOL =====

class WebhookRegisterInput(BaseModel):
    """Input schema for webhook registration"""
    url: str = Field(..., description="Webhook callback URL")
    events: List[str] = Field(..., min_items=1, description="Events to subscribe to")
    description: Optional[str] = Field(None, max_length=500, description="Webhook description")
    secret: Optional[str] = Field(None, description="Webhook secret for signature verification")
    headers: Optional[Dict[str, str]] = Field(None, description="Custom headers to include")
    active: bool = Field(default=True, description="Whether webhook is active")


class WebhookRegisterOutput(BaseModel):
    """Output schema for webhook registration"""
    webhook_id: str
    url: str
    events: List[str]
    secret_provided: bool
    active: bool
    created_at: str


class WebhookRegisterTool(ToolBase):
    """Tool for registering webhook endpoints"""

    @property
    def name(self) -> str:
        return "webhook_register"

    @property
    def description(self) -> str:
        return "Register webhook endpoint to receive event notifications."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WebhookRegisterInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WebhookRegisterOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return True  # Registering webhooks can expose data

    @property
    def category(self) -> str:
        return "api"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Register webhook in database"""
        url = input_data["url"]
        events = input_data["events"]
        description = input_data.get("description")
        secret = input_data.get("secret")
        headers = input_data.get("headers")
        active = input_data.get("active", True)

        try:
            if not self._has_approval(context):
                return self.create_result(
                    success=False, requires_approval=True,
                    error_message="Webhook registration requires an explicit approved execution context.",
                )
            db, agent_id = await _memory_scope(context)
            if not url.startswith("https://"):
                return self.create_result(success=False, error_message="Webhook URLs must use HTTPS")
            record = WebhookEndpoint(
                id=uuid4(), owner_id=UUID(str(context.user_id)),
                workspace_id=UUID(str(context.workspace_id)), agent_id=agent_id,
                url=url, events=events, description=description,
                secret_hash=hashlib.sha256(secret.encode()).hexdigest() if secret else None,
                is_active=active,
            )
            db.add(record)
            await db.flush()
            webhook_id = str(record.id)
            created_at = record.created_at.isoformat()
            logger.info(f"Registered webhook {webhook_id} for {len(events)} events; secret omitted")

            return self.create_result(
                success=True,
                result_data={
                    "webhook_id": webhook_id,
                    "url": url,
                    "events": events,
                    "secret_provided": secret is not None,
                    "active": active,
                    "created_at": created_at,
                    "custom_headers_stored": False,
                    "delivery_enabled": False,
                    "limitations": ["Registration is persisted; outbound delivery adapter is not configured."],
                },
                output_text=f"Registered webhook {webhook_id} for {len(events)} events",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to register webhook: {str(e)}",
            )


# ===== WEBHOOK UNREGISTER TOOL =====

class WebhookUnregisterInput(BaseModel):
    """Input schema for webhook unregistration"""
    webhook_id: str = Field(..., description="Webhook ID to unregister")


class WebhookUnregisterOutput(BaseModel):
    """Output schema for webhook unregistration"""
    webhook_id: str
    unregistered: bool


class WebhookUnregisterTool(ToolBase):
    """Tool for unregistering webhook endpoints"""

    @property
    def name(self) -> str:
        return "webhook_unregister"

    @property
    def description(self) -> str:
        return "Unregister webhook endpoint to stop receiving notifications."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WebhookUnregisterInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WebhookUnregisterOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def requires_approval(self) -> bool:
        return False  # Unregistering is safe

    @property
    def category(self) -> str:
        return "api"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Unregister webhook from database"""
        webhook_id = input_data["webhook_id"]

        try:
            db, agent_id = await _memory_scope(context)
            record = (await db.execute(select(WebhookEndpoint).where(
                WebhookEndpoint.id == UUID(webhook_id),
                WebhookEndpoint.owner_id == UUID(str(context.user_id)),
                WebhookEndpoint.workspace_id == UUID(str(context.workspace_id)),
                WebhookEndpoint.agent_id == agent_id,
            ))).scalar_one_or_none()
            if record is None:
                return self.create_result(success=False, error_message="Webhook not found in this scope")
            record.is_active = False
            await db.flush()
            logger.info(f"Unregistered webhook: {webhook_id}")

            return self.create_result(
                success=True,
                result_data={
                    "webhook_id": webhook_id,
                    "unregistered": True,
                },
                output_text=f"Unregistered webhook {webhook_id}",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to unregister webhook: {str(e)}",
            )


# ===== WEBHOOK LIST TOOL =====

class WebhookListInput(BaseModel):
    """Input schema for listing webhooks"""
    active_only: bool = Field(default=True, description="Only list active webhooks")
    event_filter: Optional[str] = Field(None, description="Filter by event type")


class WebhookInfo(BaseModel):
    """Webhook information"""
    webhook_id: str
    url: str
    events: List[str]
    description: Optional[str]
    active: bool
    created_at: str
    last_triggered_at: Optional[str]
    success_count: int
    failure_count: int


class WebhookListOutput(BaseModel):
    """Output schema for listing webhooks"""
    webhooks: List[WebhookInfo]
    count: int


class WebhookListTool(ToolBase):
    """Tool for listing registered webhooks"""

    @property
    def name(self) -> str:
        return "webhook_list"

    @property
    def description(self) -> str:
        return "List registered webhook endpoints."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WebhookListInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WebhookListOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "api"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """List webhooks from database"""
        active_only = input_data.get("active_only", True)
        event_filter = input_data.get("event_filter")

        try:
            db, agent_id = await _memory_scope(context)
            stmt = select(WebhookEndpoint).where(
                WebhookEndpoint.owner_id == UUID(str(context.user_id)),
                WebhookEndpoint.workspace_id == UUID(str(context.workspace_id)),
                WebhookEndpoint.agent_id == agent_id,
            )
            if active_only:
                stmt = stmt.where(WebhookEndpoint.is_active.is_(True))
            rows = (await db.execute(stmt.order_by(WebhookEndpoint.created_at.desc()))).scalars().all()
            if event_filter:
                rows = [row for row in rows if event_filter in row.events]
            webhooks = [{
                "webhook_id": str(row.id), "url": row.url, "events": row.events,
                "description": row.description, "active": row.is_active,
                "created_at": row.created_at.isoformat(),
                "last_triggered_at": row.last_triggered_at.isoformat() if row.last_triggered_at else None,
                "success_count": row.success_count, "failure_count": row.failure_count,
            } for row in rows]

            logger.info(f"Listed {len(webhooks)} webhooks")

            return self.create_result(
                success=True,
                result_data={
                    "webhooks": webhooks,
                    "count": len(webhooks),
                },
                output_text=f"Found {len(webhooks)} webhooks",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to list webhooks: {str(e)}",
            )
