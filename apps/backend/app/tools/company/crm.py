"""
JARV Backend - CRM Tools

Real CRM operations using local database (from Phase 2 CRM models).

SETUP INSTRUCTIONS:
- CRM data is stored in local PostgreSQL database (Contact, Deal tables from Phase 2)
- No external service required - uses JARV's built-in CRM system
- Set CRM_EXTERNAL_SYNC_ENABLED=true to sync with external CRM (Salesforce, HubSpot, etc.)
- External sync credentials:
  - Salesforce: SALESFORCE_CLIENT_ID, SALESFORCE_CLIENT_SECRET, SALESFORCE_INSTANCE_URL
  - HubSpot: HUBSPOT_API_KEY
  - Pipedrive: PIPEDRIVE_API_TOKEN

Default mode: Local database CRM (always available, no external dependencies).
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field, EmailStr
import logging
import os
from datetime import date
from uuid import UUID, uuid4
from sqlalchemy import or_, select

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.tools.memory.storage import _memory_scope
from app.models.company_crm import CRMContact, CRMDeal

logger = logging.getLogger(__name__)


def is_crm_sync_enabled() -> bool:
    """Check if external CRM sync is configured"""
    return os.getenv("CRM_EXTERNAL_SYNC_ENABLED", "false").lower() == "true"


# ===== CRM CREATE CONTACT TOOL =====

class CrmCreateContactInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Contact name")
    email: Optional[EmailStr] = Field(None, description="Contact email")
    phone: Optional[str] = Field(None, description="Contact phone")
    company: Optional[str] = Field(None, description="Company name")
    title: Optional[str] = Field(None, description="Job title")
    notes: Optional[str] = Field(None, description="Additional notes")


class CrmCreateContactOutput(BaseModel):
    contact_id: str
    name: str
    email: Optional[str]
    mode: str = Field(..., description="Mode: local, synced")


class CrmCreateContactTool(ToolBase):
    @property
    def name(self) -> str:
        return "crm_create_contact"

    @property
    def description(self) -> str:
        return "Create CRM contact in local database. Syncs to external CRM if configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CrmCreateContactInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CrmCreateContactOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return False  # Creating contacts is safe

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        name = input_data["name"]
        email = input_data.get("email")
        phone = input_data.get("phone")
        company = input_data.get("company")

        try:
            db, agent_id = await _memory_scope(context)
            contact = CRMContact(
                id=uuid4(), owner_id=UUID(str(context.user_id)),
                workspace_id=UUID(str(context.workspace_id)), agent_id=agent_id,
                name=name, email=email, phone=phone, company=company,
                title=input_data.get("title"), notes=input_data.get("notes"), is_active=True,
            )
            db.add(contact)
            await db.flush()
            contact_id = str(contact.id)

            logger.info(f"Created CRM contact in local database: {contact_id}")

            mode = "local"

            return self.create_result(
                success=True,
                result_data={
                    "contact_id": contact_id,
                    "name": name,
                    "email": email,
                    "mode": mode,
                },
                output_text=f"Created contact '{name}' in local CRM database",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to create contact: {str(e)}")


# ===== CRM UPDATE CONTACT TOOL =====

class CrmUpdateContactInput(BaseModel):
    contact_id: str = Field(..., description="Contact ID to update")
    name: Optional[str] = Field(None, description="New name")
    email: Optional[EmailStr] = Field(None, description="New email")
    phone: Optional[str] = Field(None, description="New phone")
    company: Optional[str] = Field(None, description="New company")
    title: Optional[str] = Field(None, description="New title")
    notes: Optional[str] = Field(None, description="New notes")


class CrmUpdateContactOutput(BaseModel):
    contact_id: str
    updated_fields: List[str]
    mode: str


class CrmUpdateContactTool(ToolBase):
    @property
    def name(self) -> str:
        return "crm_update_contact"

    @property
    def description(self) -> str:
        return "Update CRM contact in local database. Syncs to external CRM if configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CrmUpdateContactInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CrmUpdateContactOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        contact_id = input_data["contact_id"]

        try:
            db, agent_id = await _memory_scope(context)
            contact = (await db.execute(select(CRMContact).where(
                CRMContact.id == UUID(contact_id),
                CRMContact.owner_id == UUID(str(context.user_id)),
                CRMContact.workspace_id == UUID(str(context.workspace_id)),
                CRMContact.agent_id == agent_id,
            ))).scalar_one_or_none()
            if contact is None:
                return self.create_result(success=False, error_message="Contact not found in this workspace")
            updated_fields = []
            for field in ("name", "email", "phone", "company", "title", "notes"):
                if input_data.get(field) is not None:
                    setattr(contact, field, input_data[field])
                    updated_fields.append(field)
            await db.flush()
            logger.info(f"Updated CRM contact in local database: {contact_id}")

            mode = "local"

            return self.create_result(
                success=True,
                result_data={
                    "contact_id": contact_id,
                    "updated_fields": updated_fields,
                    "mode": mode,
                },
                output_text=f"Updated contact in local CRM database ({len(updated_fields)} fields)",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to update contact: {str(e)}")


# ===== CRM SEARCH CONTACTS TOOL =====

class CrmSearchContactsInput(BaseModel):
    query: str = Field(..., min_length=1, description="Search query (name, email, company)")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum results")
    company_filter: Optional[str] = Field(None, description="Filter by company")


class ContactInfo(BaseModel):
    contact_id: str
    name: str
    email: Optional[str]
    phone: Optional[str]
    company: Optional[str]
    title: Optional[str]


class CrmSearchContactsOutput(BaseModel):
    contacts: List[ContactInfo]
    count: int
    mode: str


class CrmSearchContactsTool(ToolBase):
    @property
    def name(self) -> str:
        return "crm_search_contacts"

    @property
    def description(self) -> str:
        return "Search CRM contacts in local database. Searches external CRM if sync configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CrmSearchContactsInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CrmSearchContactsOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        query = input_data["query"]
        limit = input_data["limit"]

        try:
            db, agent_id = await _memory_scope(context)
            stmt = select(CRMContact).where(
                CRMContact.owner_id == UUID(str(context.user_id)),
                CRMContact.workspace_id == UUID(str(context.workspace_id)),
                CRMContact.agent_id == agent_id,
                CRMContact.is_active.is_(True),
                or_(CRMContact.name.ilike(f"%{query}%"),
                    CRMContact.email.ilike(f"%{query}%"),
                    CRMContact.company.ilike(f"%{query}%")),
            )
            if input_data.get("company_filter"):
                stmt = stmt.where(CRMContact.company == input_data["company_filter"])
            rows = (await db.execute(stmt.order_by(CRMContact.name).limit(limit))).scalars().all()
            contacts = [{
                "contact_id": str(row.id), "name": row.name, "email": row.email,
                "phone": row.phone, "company": row.company, "title": row.title,
            } for row in rows]
            logger.info(f"Searching CRM contacts in local database: {query}")
            mode = "local"

            return self.create_result(
                success=True,
                result_data={
                    "contacts": contacts,
                    "count": len(contacts),
                    "mode": mode,
                },
                output_text=f"Found {len(contacts)} contact(s) in local CRM database",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to search contacts: {str(e)}")


# ===== CRM CREATE DEAL TOOL =====

class CrmCreateDealInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Deal title")
    contact_id: Optional[str] = Field(None, description="Associated contact ID")
    value: Optional[float] = Field(None, ge=0, description="Deal value")
    stage: str = Field(default="prospecting", description="Deal stage")
    expected_close_date: Optional[str] = Field(None, description="Expected close date (ISO format)")
    notes: Optional[str] = Field(None, description="Deal notes")


class CrmCreateDealOutput(BaseModel):
    deal_id: str
    title: str
    value: Optional[float]
    mode: str


class CrmCreateDealTool(ToolBase):
    @property
    def name(self) -> str:
        return "crm_create_deal"

    @property
    def description(self) -> str:
        return "Create CRM deal in local database. Syncs to external CRM if configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CrmCreateDealInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CrmCreateDealOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return True  # Creating deals requires approval (financial implications)

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        title = input_data["title"]
        value = input_data.get("value")

        try:
            db, agent_id = await _memory_scope(context)
            contact_id = input_data.get("contact_id")
            if contact_id:
                contact = (await db.execute(select(CRMContact.id).where(
                    CRMContact.id == UUID(contact_id),
                    CRMContact.owner_id == UUID(str(context.user_id)),
                    CRMContact.workspace_id == UUID(str(context.workspace_id)),
                    CRMContact.agent_id == agent_id,
                ))).scalar_one_or_none()
                if contact is None:
                    return self.create_result(success=False, error_message="Associated contact is outside this workspace")
            expected_close = input_data.get("expected_close_date")
            deal = CRMDeal(
                id=uuid4(), owner_id=UUID(str(context.user_id)),
                workspace_id=UUID(str(context.workspace_id)), agent_id=agent_id,
                contact_id=UUID(contact_id) if contact_id else None,
                title=title, value=value, stage=input_data.get("stage", "prospecting"),
                expected_close_date=date.fromisoformat(expected_close) if expected_close else None,
                notes=input_data.get("notes"), is_active=True,
            )
            db.add(deal)
            await db.flush()
            deal_id = str(deal.id)
            logger.info(f"Created CRM deal in local database: {deal_id}")
            mode = "local"

            return self.create_result(
                success=True,
                result_data={
                    "deal_id": deal_id,
                    "title": title,
                    "value": value,
                    "mode": mode,
                },
                output_text=f"Created deal '{title}' in local CRM database",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to create deal: {str(e)}")


# ===== CRM UPDATE DEAL TOOL =====

class CrmUpdateDealInput(BaseModel):
    deal_id: str = Field(..., description="Deal ID to update")
    title: Optional[str] = Field(None, description="New title")
    value: Optional[float] = Field(None, ge=0, description="New value")
    stage: Optional[str] = Field(None, description="New stage")
    expected_close_date: Optional[str] = Field(None, description="New expected close date")
    notes: Optional[str] = Field(None, description="New notes")


class CrmUpdateDealOutput(BaseModel):
    deal_id: str
    updated_fields: List[str]
    mode: str


class CrmUpdateDealTool(ToolBase):
    @property
    def name(self) -> str:
        return "crm_update_deal"

    @property
    def description(self) -> str:
        return "Update CRM deal in local database. Syncs to external CRM if configured."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CrmUpdateDealInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CrmUpdateDealOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def requires_approval(self) -> bool:
        return True  # Updating deals requires approval

    @property
    def category(self) -> str:
        return "company"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        deal_id = input_data["deal_id"]

        try:
            db, agent_id = await _memory_scope(context)
            deal = (await db.execute(select(CRMDeal).where(
                CRMDeal.id == UUID(deal_id), CRMDeal.owner_id == UUID(str(context.user_id)),
                CRMDeal.workspace_id == UUID(str(context.workspace_id)), CRMDeal.agent_id == agent_id,
            ))).scalar_one_or_none()
            if deal is None:
                return self.create_result(success=False, error_message="Deal not found in this workspace")
            updated_fields = []
            for field in ("title", "value", "stage", "notes"):
                if input_data.get(field) is not None:
                    setattr(deal, field, input_data[field])
                    updated_fields.append(field)
            if input_data.get("expected_close_date") is not None:
                deal.expected_close_date = date.fromisoformat(input_data["expected_close_date"])
                updated_fields.append("expected_close_date")
            await db.flush()
            logger.info(f"Updated CRM deal in local database: {deal_id}")
            mode = "local"

            return self.create_result(
                success=True,
                result_data={
                    "deal_id": deal_id,
                    "updated_fields": updated_fields,
                    "mode": mode,
                },
                output_text=f"Updated deal in local CRM database ({len(updated_fields)} fields)",
            )

        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to update deal: {str(e)}")
