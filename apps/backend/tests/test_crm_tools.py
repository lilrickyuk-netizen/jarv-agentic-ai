"""Behavioral tests for workspace-scoped local CRM tools."""
import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.tools.base import ToolConfig, ToolContext
from app.models.agent import Agent
from app.models.company_crm import CRMContact, CRMDeal
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.company.crm import (
    CrmCreateContactTool,
    CrmCreateDealTool,
    CrmSearchContactsTool,
    CrmUpdateContactTool,
)
from tests.conftest import AsyncTestingSessionLocal


def _tool(tool_class, level=AuthorityLevel.LEVEL_6_DATABASE_WRITE):
    return tool_class(ToolConfig(authority_level=level))


async def _seed_crm_scope(session):
    user_id, workspace_id, agent_id = uuid4(), uuid4(), uuid4()
    session.add(User(
        id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
        password_hash="test", is_active=True, is_admin=False,
    ))
    session.add(Workspace(
        id=workspace_id, owner_id=user_id, name="CRM scope", slug=f"crm-{workspace_id.hex[:8]}",
        description="", workspace_type="test", authority_level=8, is_active=True,
    ))
    session.add(Agent(
        id=agent_id, name="crm-agent", agent_type="sales", workspace_id=workspace_id,
        is_active=True, authority_level=8, allowed_tools=[], blocked_tools=[], config={},
        model_provider="test", model_name="test",
    ))
    await session.commit()
    return ToolContext(user_id=user_id, workspace_id=workspace_id, agent_id=agent_id,
                       db_session=session, approval_granted=True,
                       approved_tools=["crm_create_deal", "crm_update_deal"])


@pytest.mark.integration
def test_local_crm_contacts_and_deals_persist_with_scope():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            context = await _seed_crm_scope(session)
            contact = await _tool(CrmCreateContactTool).run({
                "name": "Ada Curie", "email": "ada@example.test", "company": "MYCO",
                "phone": "+1-555-0100", "title": "Engineer", "notes": "Local contact",
            }, context)
            contact_id = contact.result_data["contact_id"]
            searched = await _tool(CrmSearchContactsTool).run({
                "query": "Ada", "limit": 20,
            }, context)
            updated = await _tool(CrmUpdateContactTool).run({
                "contact_id": contact_id, "title": "Lead Engineer",
            }, context)
            deal = await _tool(CrmCreateDealTool, AuthorityLevel.LEVEL_8_FINANCIAL).run({
                "title": "MYCO pilot", "contact_id": contact_id,
                "value": 1200.0, "stage": "qualification",
            }, context)
            contact_row = (await session.execute(
                select(CRMContact).where(CRMContact.id == UUID(contact_id))
            )).scalar_one()
            deal_row = (await session.execute(
                select(CRMDeal).where(CRMDeal.id == UUID(deal.result_data["deal_id"]))
            )).scalar_one()
            return contact, searched, updated, deal, contact_row, deal_row

    contact, searched, updated, deal, contact_row, deal_row = asyncio.run(run())
    assert contact.success is True
    assert searched.success is True and searched.result_data["count"] == 1
    assert updated.success is True
    assert contact_row.title == "Lead Engineer"
    assert deal.success is True
    assert deal_row.title == "MYCO pilot" and deal_row.value == 1200.0
    assert deal_row.contact_id == contact_row.id
