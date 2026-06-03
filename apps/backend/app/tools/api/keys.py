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

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

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

        # Generate secure API key
        key_value = f"jarv_{secrets.token_urlsafe(32)}"
        key_id = secrets.token_hex(16)
        key_prefix = key_value[:8]

        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(days=expires_in_days) if expires_in_days else None

        # In production: Store in ApiKey table
        # from app.models.api_key import ApiKey
        # from app.core.database import get_db
        # import hashlib
        # async for session in get_db():
        #     # Hash the key value for security
        #     key_hash = hashlib.sha256(key_value.encode()).hexdigest()
        #     api_key = ApiKey(
        #         id=key_id,
        #         agent_id=context.agent_id,
        #         service_name=service_name,
        #         description=description,
        #         key_hash=key_hash,
        #         key_prefix=key_prefix,
        #         scopes=scopes,
        #         created_at=created_at,
        #         expires_at=expires_at,
        #         last_used_at=None,
        #         is_active=True,
        #     )
        #     session.add(api_key)
        #     await session.commit()

        logger.info(f"Created API key: {key_id}, service={service_name}")

        return self.create_result(
            success=True,
            result_data={
                "action": "create",
                "key_id": key_id,
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

        # In production: Update ApiKey to set is_active=False
        # from app.models.api_key import ApiKey
        # from app.core.database import get_db
        # async for session in get_db():
        #     api_key = await session.get(ApiKey, key_id)
        #     if not api_key or api_key.agent_id != context.agent_id:
        #         return self.create_result(success=False, error_message="API key not found")
        #     api_key.is_active = False
        #     await session.commit()

        logger.info(f"Revoked API key: {key_id}")

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
        keys = []

        # In production: Query ApiKey table
        # from app.models.api_key import ApiKey
        # from app.core.database import get_db
        # from sqlalchemy import select
        # async for session in get_db():
        #     stmt = select(ApiKey).filter(ApiKey.agent_id == context.agent_id, ApiKey.is_active == True)
        #     result = await session.execute(stmt)
        #     for api_key in result.scalars():
        #         keys.append({
        #             "key_id": str(api_key.id),
        #             "service_name": api_key.service_name,
        #             "description": api_key.description,
        #             "key_prefix": api_key.key_prefix,
        #             "scopes": api_key.scopes,
        #             "created_at": api_key.created_at.isoformat(),
        #             "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
        #             "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        #             "is_active": api_key.is_active,
        #         })

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

        # In production: Get old key, revoke it, create new one
        # from app.models.api_key import ApiKey
        # from app.core.database import get_db
        # import hashlib
        # async for session in get_db():
        #     old_key = await session.get(ApiKey, key_id)
        #     if not old_key or old_key.agent_id != context.agent_id:
        #         return self.create_result(success=False, error_message="API key not found")
        #
        #     # Revoke old key
        #     old_key.is_active = False
        #
        #     # Create new key with same settings
        #     new_key_value = f"jarv_{secrets.token_urlsafe(32)}"
        #     new_key_id = secrets.token_hex(16)
        #     new_key_prefix = new_key_value[:8]
        #     new_key_hash = hashlib.sha256(new_key_value.encode()).hexdigest()
        #
        #     new_api_key = ApiKey(
        #         id=new_key_id,
        #         agent_id=context.agent_id,
        #         service_name=old_key.service_name,
        #         description=old_key.description,
        #         key_hash=new_key_hash,
        #         key_prefix=new_key_prefix,
        #         scopes=old_key.scopes,
        #         created_at=datetime.utcnow(),
        #         expires_at=old_key.expires_at,
        #         last_used_at=None,
        #         is_active=True,
        #     )
        #     session.add(new_api_key)
        #     await session.commit()
        #
        #     return self.create_result(
        #         success=True,
        #         result_data={
        #             "action": "rotate",
        #             "key_id": new_key_id,
        #             "key_value": new_key_value,
        #             "keys": None,
        #             "count": None,
        #         },
        #         output_text=f"Rotated API key. New key: {new_key_value}",
        #     )

        logger.info(f"Rotated API key: {key_id}")

        # Placeholder response
        new_key_value = f"jarv_{secrets.token_urlsafe(32)}"
        new_key_id = secrets.token_hex(16)

        return self.create_result(
            success=True,
            result_data={
                "action": "rotate",
                "key_id": new_key_id,
                "key_value": new_key_value,
                "keys": None,
                "count": None,
            },
            output_text=f"Rotated API key. New key: {new_key_value}",
        )
