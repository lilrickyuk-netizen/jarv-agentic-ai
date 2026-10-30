"""
JARV Backend - API Key Management Tool

Tool for managing API keys used by agents.

API keys allow agents to authenticate with external services.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
import logging
from datetime import datetime, timedelta
import secrets
import hashlib
from uuid import UUID, uuid4
from sqlalchemy import select

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.tools.memory.storage import _memory_scope
from app.models.integrations import ApiCredential

logger = logging.getLogger(__name__)


# ===== API KEY MANAGE TOOL =====

class ApiKeyManageInput(BaseModel):
    """Input schema for API key management"""
    action: str = Field(..., description="Action: create, revoke, list, rotate")
    key_id: Optional[str] = Field(None, description="Key ID (for revoke/rotate)")
    service_name: Optional[str] = Field(None, description="Service name (for create)")
    description: Optional[str] = Field(None, description="Key description (for create)")
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650, description="Expiration days (for create)")
    scopes: Optional[List[str]] = Field(None, description="API scopes/permissions (for create)")


class ApiKeyInfo(BaseModel):
    """API key information"""
    key_id: str
    service_name: str
    description: Optional[str]
    key_prefix: str = Field(..., description="First 8 characters of key")
    scopes: List[str]
    created_at: str
    expires_at: Optional[str]
    last_used_at: Optional[str]
    is_active: bool


class ApiKeyManageOutput(BaseModel):
    """Output schema for API key management"""
    action: str
    key_id: Optional[str] = None
    key_value: Optional[str] = Field(None, description="Full key value (only on create/rotate)")
    keys: Optional[List[ApiKeyInfo]] = Field(None, description="List of keys (for list action)")
    count: Optional[int] = None


class ApiKeyManageTool(ToolBase):
    """Tool for managing API keys"""

    @property
    def name(self) -> str:
        return "api_key_manage"

    @property
    def description(self) -> str:
        return "Manage API keys: create, revoke, list, or rotate keys for external services."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ApiKeyManageInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ApiKeyManageOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_8_FINANCIAL  # API keys are sensitive

    @property
    def requires_approval(self) -> bool:
        return True  # API key operations require approval

    @property
    def category(self) -> str:
        return "api"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Manage API keys in database"""
        action = input_data["action"]

        try:
            if not self._has_approval(context):
                return self.create_result(
                    success=False, requires_approval=True,
                    error_message="API key operations require an explicit approved execution context.",
                )
            if action == "create":
                return await self._create_key(input_data, context)
            elif action == "revoke":
                return await self._revoke_key(input_data, context)
            elif action == "list":
                return await self._list_keys(input_data, context)
            elif action == "rotate":
                return await self._rotate_key(input_data, context)
            else:
                return self.create_result(
                    success=False,
                    error_message=f"Unknown action: {action}. Use: create, revoke, list, rotate",
                )

        except Exception as e:
            return self.create_result(
                success=False,
                error_message=f"Failed to manage API key: {str(e)}",
            )

    async def _create_key(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Create new API key"""
        service_name = input_data.get("service_name")
        if not service_name:
            return self.create_result(
                success=False,
                error_message="service_name required for create action",
            )

        description = input_data.get("description")
        expires_in_days = input_data.get("expires_in_days")
        scopes = input_data.get("scopes") or []

        db, agent_id = await _memory_scope(context)
        key_value = f"jarv_{secrets.token_urlsafe(32)}"
        key_id = uuid4()
        key_prefix = key_value[:8]

        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(days=expires_in_days) if expires_in_days else None

        db.add(ApiCredential(
            id=key_id, owner_id=UUID(str(context.user_id)),
            workspace_id=UUID(str(context.workspace_id)), agent_id=agent_id,
            service_name=service_name, description=description,
            key_hash=hashlib.sha256(key_value.encode()).hexdigest(),
            key_prefix=key_prefix, scopes=scopes, expires_at=expires_at, is_active=True,
        ))
        await db.flush()
        logger.info(f"Created API credential {key_id} for service={service_name}; secret omitted")

        return self.create_result(
            success=True,
            result_data={
                "action": "create",
                "key_id": str(key_id),
                "key_value": key_value,
                "keys": None,
                "count": None,
            },
            output_text=f"Created API key for {service_name}. SAVE THIS KEY: {key_value}",
        )

    async def _revoke_key(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Revoke API key"""
        key_id = input_data.get("key_id")
        if not key_id:
            return self.create_result(
                success=False,
                error_message="key_id required for revoke action",
            )

        db, agent_id = await _memory_scope(context)
        credential = (await db.execute(select(ApiCredential).where(
            ApiCredential.id == UUID(key_id),
            ApiCredential.owner_id == UUID(str(context.user_id)),
            ApiCredential.workspace_id == UUID(str(context.workspace_id)),
            ApiCredential.agent_id == agent_id,
        ))).scalar_one_or_none()
        if credential is None:
            return self.create_result(success=False, error_message="API credential not found in this scope")
        credential.is_active = False
        await db.flush()
        logger.info(f"Revoked API credential {credential.id}")

        return self.create_result(
            success=True,
            result_data={
                "action": "revoke",
                "key_id": key_id,
                "key_value": None,
                "keys": None,
                "count": None,
            },
            output_text=f"Revoked API key {key_id}",
        )

    async def _list_keys(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """List API keys"""
        db, agent_id = await _memory_scope(context)
        records = (await db.execute(select(ApiCredential).where(
            ApiCredential.owner_id == UUID(str(context.user_id)),
            ApiCredential.workspace_id == UUID(str(context.workspace_id)),
            ApiCredential.agent_id == agent_id,
        ).order_by(ApiCredential.created_at.desc()))).scalars().all()
        keys = [{
            "key_id": str(record.id), "service_name": record.service_name,
            "description": record.description, "key_prefix": record.key_prefix,
            "scopes": record.scopes, "created_at": record.created_at.isoformat(),
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
            "is_active": record.is_active,
        } for record in records]

        logger.info(f"Listed {len(keys)} API keys")

        return self.create_result(
            success=True,
            result_data={
                "action": "list",
                "key_id": None,
                "key_value": None,
                "keys": keys,
                "count": len(keys),
            },
            output_text=f"Found {len(keys)} active API keys",
        )

    async def _rotate_key(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Rotate API key (revoke old, create new)"""
        key_id = input_data.get("key_id")
        if not key_id:
            return self.create_result(
                success=False,
                error_message="key_id required for rotate action",
            )

        db, agent_id = await _memory_scope(context)
        old = (await db.execute(select(ApiCredential).where(
            ApiCredential.id == UUID(key_id),
            ApiCredential.owner_id == UUID(str(context.user_id)),
            ApiCredential.workspace_id == UUID(str(context.workspace_id)),
            ApiCredential.agent_id == agent_id,
            ApiCredential.is_active.is_(True),
        ))).scalar_one_or_none()
        if old is None:
            return self.create_result(success=False, error_message="Active API credential not found in this scope")
        old.is_active = False
        new_key_value = f"jarv_{secrets.token_urlsafe(32)}"
        new_key_id = uuid4()
        db.add(ApiCredential(
            id=new_key_id, owner_id=old.owner_id, workspace_id=old.workspace_id,
            agent_id=old.agent_id, service_name=old.service_name,
            description=old.description,
            key_hash=hashlib.sha256(new_key_value.encode()).hexdigest(),
            key_prefix=new_key_value[:8], scopes=old.scopes,
            expires_at=old.expires_at, is_active=True,
        ))
        await db.flush()
        logger.info(f"Rotated API credential {old.id}; raw key omitted")

        return self.create_result(
            success=True,
            result_data={
                "action": "rotate",
                "key_id": str(new_key_id),
                "key_value": new_key_value,
                "keys": None,
                "count": None,
            },
            output_text=f"Rotated API key. New key: {new_key_value}",
        )
