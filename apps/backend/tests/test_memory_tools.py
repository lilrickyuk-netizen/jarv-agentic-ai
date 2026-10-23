"""Behavioral tests for real persistent memory tools and workspace isolation."""
import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.tools.base import ToolConfig, ToolContext
from app.models.agent import Agent
from app.models.memory import Memory
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.memory.storage import (
    MemoryDeleteTool,
    MemoryRetrieveTool,
    MemorySearchTool,
    MemoryStoreTool,
    MemoryUpdateTool,
)
from app.tools.memory.management import (
    MemoryExportTool,
    MemoryImportTool,
    MemoryListTool,
    MemoryStatsTool,
    MemoryTagTool,
)
from tests.conftest import AsyncTestingSessionLocal


def _tool(tool_class):
    return tool_class(ToolConfig(authority_level=AuthorityLevel.LEVEL_6_DATABASE_WRITE))


async def _seed_memory_scope(session):
    user_id, workspace_id, agent_id = uuid4(), uuid4(), uuid4()
    session.add(User(
        id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
        password_hash="test", is_active=True, is_admin=False,
    ))
    session.add(Workspace(
        id=workspace_id, owner_id=user_id, name="Memory scope", slug=f"memory-{workspace_id.hex[:8]}",
        description="", workspace_type="test", authority_level=6, is_active=True,
    ))
    session.add(Agent(
        id=agent_id, name="memory-owner", agent_type="memory", workspace_id=workspace_id,
        is_active=True, authority_level=6, allowed_tools=[], blocked_tools=[], config={},
        model_provider="test", model_name="test",
    ))
    await session.commit()
    return user_id, workspace_id, agent_id


@pytest.mark.integration
def test_memory_crud_tools_persist_and_enforce_workspace_isolation():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            user_id, workspace_id, agent_id = await _seed_memory_scope(session)
            context = ToolContext(
                user_id=user_id, workspace_id=workspace_id, agent_id=agent_id,
                db_session=session,
            )
            stored = await _tool(MemoryStoreTool).run({
                "content": "Retry with exponential backoff and bounded attempts.",
                "memory_type": "verified_learning",
                "importance_score": 0.8,
                "is_permanent": True,
                "tags": ["retries"],
            }, context)
            memory_id = stored.result_data["memory_id"]
            found = await _tool(MemoryRetrieveTool).run({"memory_id": memory_id}, context)
            searched = await _tool(MemorySearchTool).run({
                "query": "exponential backoff", "tags": ["retries"],
            }, context)
            updated = await _tool(MemoryUpdateTool).run({
                "memory_id": memory_id,
                "content": "Retry with jittered exponential backoff and bounded attempts.",
                "add_tags": ["jitter"],
            }, context)

            other_user, other_workspace, other_agent = await _seed_memory_scope(session)
            other_context = ToolContext(
                user_id=other_user, workspace_id=other_workspace, agent_id=other_agent,
                db_session=session,
            )
            hidden = await _tool(MemoryRetrieveTool).run({"memory_id": memory_id}, other_context)
            other_search = await _tool(MemorySearchTool).run({
                "query": "exponential backoff",
            }, other_context)

            deleted = await _tool(MemoryDeleteTool).run({"memory_id": memory_id}, context)
            persisted = (await session.execute(
                select(Memory).where(Memory.id == UUID(memory_id))
            )).scalar_one_or_none()
            return stored, found, searched, updated, hidden, other_search, deleted, persisted

    stored, found, searched, updated, hidden, other_search, deleted, persisted = asyncio.run(run())
    assert stored.success is True
    assert found.success is True and "exponential backoff" in found.result_data["content"]
    assert searched.success is True and searched.result_data["count"] == 1
    assert updated.success is True and "tags" in updated.result_data["updated_fields"]
    assert hidden.success is False
    assert other_search.success is True and other_search.result_data["count"] == 0
    assert deleted.success is True and deleted.result_data["deleted"] is True
    assert persisted is None


@pytest.mark.integration
def test_memory_management_tools_read_and_mutate_real_rows():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            user_id, workspace_id, agent_id = await _seed_memory_scope(session)
            context = ToolContext(
                user_id=user_id, workspace_id=workspace_id, agent_id=agent_id,
                db_session=session,
            )
            await _tool(MemoryStoreTool).run({
                "content": "Verified retry outcome", "memory_type": "experience",
                "importance_score": 0.9, "is_permanent": True, "tags": ["retry"],
            }, context)
            listed = await _tool(MemoryListTool).run({"limit": 10}, context)
            memory_id = listed.result_data["memories"][0]["memory_id"]
            tagged = await _tool(MemoryTagTool).run({
                "memory_id": memory_id, "tags": ["verified"],
            }, context)
            exported = await _tool(MemoryExportTool).run({"format": "json"}, context)
            imported = await _tool(MemoryImportTool).run({
                "import_data": exported.result_data["export_data"],
                "merge_strategy": "create_new",
                "preserve_ids": False,
            }, context)
            stats = await _tool(MemoryStatsTool).run({}, context)
            return listed, tagged, exported, imported, stats

    listed, tagged, exported, imported, stats = asyncio.run(run())
    assert listed.success is True and listed.result_data["total"] == 1
    assert tagged.success is True and tagged.result_data["tagged_count"] == 1
    assert exported.success is True and exported.result_data["count"] == 1
    assert imported.success is True and imported.result_data["imported_count"] == 1
    assert stats.success is True and stats.result_data["total_memories"] == 2
    assert stats.result_data["by_type"]["experience"] == 2