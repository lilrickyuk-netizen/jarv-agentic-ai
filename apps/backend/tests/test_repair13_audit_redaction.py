"""Repair 13 tests for redaction across persisted audit fields."""
import asyncio
import json

import pytest

from app.core.audit import AuditLogger
from app.models.operations import AuditLog
from tests.conftest import AsyncTestingSessionLocal


@pytest.mark.integration
def test_tool_audit_redacts_secrets_from_all_persisted_fields():
    secret = "sk-REPAIR13SECRETKEY1234567890"

    async def run():
        async with AsyncTestingSessionLocal() as session:
            row = await AuditLogger.log_tool_use(
                session=session,
                agent_name="security",
                tool_name="deploy",
                tool_result=f"failed while handling {secret}",
                tool_input={"command": f"deploy --token {secret}"},
                tool_output={"stderr": f"authentication rejected: {secret}"},
            )
            return {
                "action": row.action,
                "description": row.description,
                "target_description": row.target_description,
                "error_message": row.error_message,
                "before_state": row.before_state,
                "after_state": row.after_state,
                "changes": row.changes,
                "meta_data": row.meta_data,
                "user_agent": row.user_agent,
            }

    persisted = asyncio.run(run())
    assert secret not in json.dumps(persisted, default=str)


@pytest.mark.integration
def test_direct_audit_model_writes_are_redacted():
    secret = "sk-REPAIR13DIRECTSECRET1234567890"

    async def run():
        async with AsyncTestingSessionLocal() as session:
            row = AuditLog(
                actor_type="system",
                action=f"operation {secret}",
                action_category="system",
                description=f"received {secret}",
                error_message=f"rejected {secret}",
                after_state={"output": secret},
                meta_data={"details": {"credential": secret}},
                success=False,
            )
            session.add(row)
            await session.commit()
            return row.action, row.description, row.error_message, row.after_state, row.meta_data

    persisted = asyncio.run(run())
    assert secret not in json.dumps(persisted, default=str)


@pytest.mark.integration
def test_system_event_audit_persists_redacted_event():
    secret = "sk-REPAIR13EVENTSECRET1234567890"

    async def run():
        async with AsyncTestingSessionLocal() as session:
            row = await AuditLogger.log_system_event(
                session=session,
                action=f"credential rejected {secret}",
                result=f"failure containing {secret}",
                resource_type="credential_check",
                details={"response": secret},
            )
            return row.action, row.description, row.target_type, row.target_id, row.meta_data

    persisted = asyncio.run(run())
    assert secret not in json.dumps(persisted, default=str)