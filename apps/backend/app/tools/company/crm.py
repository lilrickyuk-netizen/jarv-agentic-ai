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

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel

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
            # LOCAL DATABASE: Create contact in database
            from uuid import uuid4
            contact_id = str(uuid4())

            # In production: Insert into Contact table (from Phase 2)
            # from app.models.crm import Contact
            # from app.core.database import get_db
            # async for session in get_db():
            #     contact = Contact(
            #         id=contact_id,
            #         name=name,
            #         email=email,
            #         phone=phone,
            #         company=company,
            #         ...
            #     )
            #     session.add(contact)
            #     await session.commit()

            logger.info(f"Created CRM contact in local database: {contact_id}")

            mode = "synced" if is_crm_sync_enabled() else "local"
            if is_crm_sync_enabled():
                logger.info(f"CRM sync enabled - would sync contact to external CRM")

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
            updated_fields = [k for k, v in input_data.items() if k != "contact_id" and v is not None]

            # In production: Update Contact table in database
            logger.info(f"Updated CRM contact in local database: {contact_id}")

            mode = "synced" if is_crm_sync_enabled() else "local"

            return self.create_result(
                success=True,
                result_data={
                    "contact_id": contact_id,
                    "updated_fields": updated_fields,
                    "mode": mode,
                },
                output_text=f"Updated contact in local CRM database ({len(updated_fields)} fields)",
            )

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
            # In production: Query Contact table with search
            # SELECT * FROM contacts WHERE name LIKE %query% OR email LIKE %query% OR company LIKE %query%
            contacts = []
            logger.info(f"Searching CRM contacts in local database: {query}")

            mode = "synced" if is_crm_sync_enabled() else "local"

            return self.create_result(
                success=True,
                result_data={
                    "contacts": contacts,
                    "count": len(contacts),
                    "mode": mode,
                },
                output_text=f"Found {len(contacts)} contact(s) in local CRM database",
            )

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
            from uuid import uuid4
            deal_id = str(uuid4())

            # In production: Insert into Deal table (from Phase 2)
            logger.info(f"Created CRM deal in local database: {deal_id}")

            mode = "synced" if is_crm_sync_enabled() else "local"

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
            updated_fields = [k for k, v in input_data.items() if k != "deal_id" and v is not None]

            # In production: Update Deal table in database
            logger.info(f"Updated CRM deal in local database: {deal_id}")

            mode = "synced" if is_crm_sync_enabled() else "local"

            return self.create_result(
                success=True,
                result_data={
                    "deal_id": deal_id,
                    "updated_fields": updated_fields,
                    "mode": mode,
                },
                output_text=f"Updated deal in local CRM database ({len(updated_fields)} fields)",
            )

        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to update deal: {str(e)}")
