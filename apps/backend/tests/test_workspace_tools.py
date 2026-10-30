"""Behavioral tests for persistent workspace tool operations."""
import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.tools.base import ToolConfig, ToolContext
from app.models.agent import Agent
from app.models.operations import BackupRecord
from app.models.session import AgentSession
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.workspace.management import (
    WorkspaceCreateTool,
    WorkspaceInfoTool,
    WorkspaceListTool,
    WorkspaceDeleteTool,
    WorkspaceSwitchTool,
    WorkspaceUpdateTool,
)
from app.tools.workspace.backup import WorkspaceBackupTool, WorkspaceRestoreTool
from app.tools.workspace.backup import WorkspaceExportTool, WorkspaceImportTool
from tests.conftest import AsyncTestingSessionLocal


def _tool(tool_class):
    return tool_class(ToolConfig(authority_level=AuthorityLevel.LEVEL_4_SYSTEM_CHANGES))


@pytest.mark.integration
def test_workspace_crud_tools_use_real_owned_database_rows():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            user_id = uuid4()
            session.add(User(
                id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="test", is_active=True, is_admin=False,
            ))
            await session.commit()
            context = ToolContext(user_id=user_id, db_session=session)

            created = await _tool(WorkspaceCreateTool).run({
                "name": "Repair Workspace",
                "description": "Persistent project workspace",
                "settings": {"stack": "python"},
            }, context)
            workspace_id = created.result_data["workspace_id"]
            listed = await _tool(WorkspaceListTool).run({"limit": 10}, context)
            info = await _tool(WorkspaceInfoTool).run({"workspace_id": workspace_id}, context)
            updated = await _tool(WorkspaceUpdateTool).run({
                "workspace_id": workspace_id,
                "name": "Updated Repair Workspace",
                "settings": {"stack": "python", "verified": True},
            }, context)
            row = (await session.execute(
                select(Workspace).where(Workspace.id == UUID(workspace_id))
            )).scalar_one()
            return created, listed, info, updated, row, user_id

    created, listed, info, updated, row, user_id = asyncio.run(run())
    assert created.success is True
    assert listed.success is True and listed.result_data["count"] == 1
    assert listed.result_data["workspaces"][0]["workspace_id"] == created.result_data["workspace_id"]
    assert info.success is True and info.result_data["settings"] == {"stack": "python"}
    assert updated.success is True
    assert row.owner_id == user_id
    assert row.name == "Updated Repair Workspace"
    assert row.config == {"stack": "python", "verified": True}


@pytest.mark.integration
def test_workspace_scope_and_destructive_approval_are_enforced():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            owner_id, other_id = uuid4(), uuid4()
            workspace_id, agent_id, session_id = uuid4(), uuid4(), uuid4()
            for user_id in (owner_id, other_id):
                session.add(User(
                    id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                    password_hash="test", is_active=True, is_admin=False,
                ))
            session.add(Workspace(
                id=workspace_id, owner_id=owner_id, name="Owned", slug=f"owned-{workspace_id.hex[:8]}",
                description="", workspace_type="project", authority_level=4, config={},
                is_active=True,
            ))
            session.add(Agent(
                id=agent_id, name="runner", agent_type="research", workspace_id=workspace_id,
                is_active=True, authority_level=4, allowed_tools=[], blocked_tools=[], config={},
                model_provider="test", model_name="test",
            ))
            session.add(AgentSession(
                id=session_id, user_id=owner_id, workspace_id=workspace_id, agent_id=agent_id,
                session_type="standard", status="active", started_at=__import__("datetime").datetime.utcnow(),
            ))
            await session.commit()
            owner_context = ToolContext(
                user_id=owner_id, session_id=session_id, db_session=session)
            attacker_context = ToolContext(user_id=other_id, db_session=session)

            hidden = await _tool(WorkspaceInfoTool).run(
                {"workspace_id": str(workspace_id)}, attacker_context)
            switched = await _tool(WorkspaceSwitchTool).run(
                {"workspace_id": str(workspace_id)}, owner_context)
            delete_tool = _tool(WorkspaceDeleteTool)
            blocked = await delete_tool.execute(
                {"workspace_id": str(workspace_id)}, owner_context)
            still_exists = (await session.execute(
                select(Workspace.id).where(Workspace.id == workspace_id)
            )).scalar_one_or_none()
            allowed_context = ToolContext(
                user_id=owner_id, db_session=session,
                approval_granted=True, approved_tools=["workspace_delete"],
            )
            deleted = await delete_tool.execute(
                {"workspace_id": str(workspace_id)}, allowed_context)
            absent = (await session.execute(
                select(Workspace.id).where(Workspace.id == workspace_id)
            )).scalar_one_or_none()
            return hidden, switched, blocked, still_exists, deleted, absent

    hidden, switched, blocked, still_exists, deleted, absent = asyncio.run(run())
    assert hidden.success is False
    assert switched.success is True
    assert blocked.success is False and blocked.requires_approval is True
    assert still_exists is not None
    assert deleted.success is True
    assert absent is None


@pytest.mark.integration
def test_workspace_backup_and_restore_round_trip_persisted_settings():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            user_id, workspace_id = uuid4(), uuid4()
            session.add(User(
                id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="test", is_active=True, is_admin=False,
            ))
            session.add(Workspace(
                id=workspace_id, owner_id=user_id, name="Backup source",
                slug=f"backup-{workspace_id.hex[:8]}", description="snapshot description",
                workspace_type="project", authority_level=3,
                config={"stack": "python"}, is_active=True,
            ))
            await session.commit()
            context = ToolContext(user_id=user_id, db_session=session)
            backup = await _tool(WorkspaceBackupTool).run({
                "workspace_id": str(workspace_id), "include_files": True,
            }, context)
            record = (await session.execute(
                select(BackupRecord).where(BackupRecord.id == UUID(backup.result_data["backup_id"]))
            )).scalar_one()
            restored = await _tool(WorkspaceRestoreTool).run({
                "backup_id": backup.result_data["backup_id"],
            }, context)
            restored_id = UUID(restored.result_data["workspace_id"])
            row = (await session.execute(
                select(Workspace).where(Workspace.id == restored_id)
            )).scalar_one()
            return backup, record, restored, row

    backup, record, restored, row = asyncio.run(run())
    assert backup.success is True
    assert backup.result_data["files_included"] is False
    assert backup.result_data["limitations"]
    assert record.success is True and record.is_verified is True
    assert restored.success is True
    assert row.name == "Backup source"
    assert row.description == "snapshot description"
    assert row.config == {"stack": "python"}


@pytest.mark.integration
def test_workspace_export_import_round_trip_is_scoped(tmp_path):
    async def run():
        async with AsyncTestingSessionLocal() as session:
            user_id, workspace_id = uuid4(), uuid4()
            session.add(User(
                id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="test", is_active=True, is_admin=False,
            ))
            session.add(Workspace(
                id=workspace_id, owner_id=user_id, name="Export source",
                slug=f"export-{workspace_id.hex[:8]}", description="transfer metadata",
                workspace_type="project", authority_level=3,
                config={"workspace_path": str(tmp_path), "stack": "python"}, is_active=True,
            ))
            await session.commit()
            context = ToolContext(
                user_id=user_id, db_session=session, approved_folders=[str(tmp_path)])
            export_path = tmp_path / "workspace.json"
            exported = await _tool(WorkspaceExportTool).run({
                "workspace_id": str(workspace_id),
                "export_path": str(export_path),
                "format": "json",
            }, context)
            imported = await _tool(WorkspaceImportTool).run({
                "import_path": str(export_path),
                "workspace_name": "Imported workspace",
                "overwrite": False,
            }, context)
            imported_row = (await session.execute(select(Workspace).where(
                Workspace.id == UUID(imported.result_data["workspace_id"])
            ))).scalar_one()
            return exported, imported, imported_row, export_path

    exported, imported, imported_row, export_path = asyncio.run(run())
    assert exported.success is True and export_path.is_file()
    assert exported.result_data["file_size"] == export_path.stat().st_size
    assert exported.result_data["files_included"] is False
    assert imported.success is True
    assert imported_row.owner_id is not None
    assert imported_row.name == "Imported workspace"
    assert imported_row.config["stack"] == "python"