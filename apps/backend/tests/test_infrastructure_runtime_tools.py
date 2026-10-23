"""Behavioral checks for local infrastructure telemetry."""
import asyncio
from uuid import uuid4

import psutil
import pytest
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.tools.base import ToolConfig, ToolContext
from app.models.agent import Agent
from app.models.operations import InfrastructureResource
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.infrastructure.monitoring import ResourceMetricsTool
from app.tools.infrastructure.resources import ResourceHealthCheckTool, ResourceProvisionTool
from app.tools.infrastructure.cost import CostEstimateTool
from app.tools.infrastructure.backup import BackupCreateTool, BackupRestoreTool
from app.tools.infrastructure.deployment import ServiceDeployTool, DeploymentRollbackTool
from tests.conftest import AsyncTestingSessionLocal


@pytest.mark.integration
def test_resource_metrics_uses_real_local_host_snapshot(tmp_path):
    async def run():
        async with AsyncTestingSessionLocal() as session:
            user_id, workspace_id, agent_id, resource_id = uuid4(), uuid4(), uuid4(), uuid4()
            session.add(User(
                id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="test", is_active=True, is_admin=False,
            ))
            session.add(Workspace(
                id=workspace_id, owner_id=user_id, name="Infra", slug=f"infra-{workspace_id.hex[:8]}",
                description="", workspace_type="test", authority_level=3, is_active=True,
            ))
            session.add(Agent(
                id=agent_id, name="monitor", agent_type="monitoring", workspace_id=workspace_id,
                is_active=True, authority_level=3, allowed_tools=[], blocked_tools=[], config={},
                model_provider="test", model_name="test",
            ))
            session.add(InfrastructureResource(
                id=resource_id, workspace_id=workspace_id, resource_name="local-host",
                resource_type="host", resource_id="local-host", provider="local",
                description="local test target", config={"metrics_path": str(tmp_path)},
                tags_list=[], status="running", health="unknown", is_active=True,
                currency="USD",
            ))
            await session.commit()
            tool = ResourceMetricsTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_2_FILE_OPERATIONS))
            result = await tool.run({"resource_id": str(resource_id)}, ToolContext(
                user_id=user_id, workspace_id=workspace_id, agent_id=agent_id, db_session=session))
            health = await ResourceHealthCheckTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_2_FILE_OPERATIONS)).run({
                    "resource_id": str(resource_id), "include_metrics": True,
                }, ToolContext(user_id=user_id, workspace_id=workspace_id,
                               agent_id=agent_id, db_session=session))
            return result, health

    result, health = asyncio.run(run())
    assert result.success is True
    assert result.result_data["data_source"] == "host_snapshot"
    assert 0 <= result.result_data["metrics"]["cpu"]["current"] <= 100
    assert 0 <= result.result_data["metrics"]["memory"]["current"] <= 100
    assert result.result_data["metrics"]["disk"]["path"] == str(tmp_path)
    assert health.success is True
    assert health.result_data["checks"]["host_snapshot"] is True
    assert 0 <= health.result_data["metrics"]["cpu_usage"] <= 100


@pytest.mark.integration
def test_cloud_resource_metrics_fail_without_provider_adapter():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            user_id, workspace_id, agent_id, resource_id = uuid4(), uuid4(), uuid4(), uuid4()
            session.add(User(
                id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="test", is_active=True, is_admin=False,
            ))
            session.add(Workspace(
                id=workspace_id, owner_id=user_id, name="Cloud", slug=f"cloud-{workspace_id.hex[:8]}",
                description="", workspace_type="test", authority_level=3, is_active=True,
            ))
            session.add(Agent(
                id=agent_id, name="monitor", agent_type="monitoring", workspace_id=workspace_id,
                is_active=True, authority_level=3, allowed_tools=[], blocked_tools=[], config={},
                model_provider="test", model_name="test",
            ))
            session.add(InfrastructureResource(
                id=resource_id, workspace_id=workspace_id, resource_name="cloud-vm",
                resource_type="vm", resource_id="vm-1", provider="aws",
                description="cloud test target", config={}, tags_list=[], status="running",
                health="unknown", is_active=True, currency="USD",
            ))
            await session.commit()
            tool = ResourceMetricsTool(ToolConfig(
                authority_level=AuthorityLevel.LEVEL_2_FILE_OPERATIONS))
            return await tool.run({"resource_id": str(resource_id)}, ToolContext(
                user_id=user_id, workspace_id=workspace_id, agent_id=agent_id, db_session=session))

    result = asyncio.run(run())
    assert result.success is False
    assert "provider adapter" in result.error_message.lower()


@pytest.mark.integration
def test_cloud_provision_fails_without_provider_adapter_and_creates_no_resource():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            user_id, workspace_id, agent_id = uuid4(), uuid4(), uuid4()
            session.add(User(
                id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="test", is_active=True, is_admin=False,
            ))
            session.add(Workspace(
                id=workspace_id, owner_id=user_id, name="Provision", slug=f"prov-{workspace_id.hex[:8]}",
                description="", workspace_type="test", authority_level=7, is_active=True,
            ))
            session.add(Agent(
                id=agent_id, name="infra", agent_type="infrastructure", workspace_id=workspace_id,
                is_active=True, authority_level=7, allowed_tools=[], blocked_tools=[], config={},
                model_provider="test", model_name="test",
            ))
            await session.commit()
            context = ToolContext(user_id=user_id, workspace_id=workspace_id,
                                  agent_id=agent_id, db_session=session)
            tool = ResourceProvisionTool(ToolConfig(authority_level=AuthorityLevel.LEVEL_7_DEPLOYMENT))
            result = await tool.run({
                "resource_name": "not-created", "resource_type": "vm", "provider": "aws",
                "region": "us-east-1", "config": {"instance_size": "small"},
            }, context)
            resources = (await session.execute(
                select(InfrastructureResource).where(InfrastructureResource.workspace_id == workspace_id)
            )).scalars().all()
            return result, resources

    result, resources = asyncio.run(run())
    assert result.success is False
    assert "provider adapter" in result.error_message.lower()
    assert resources == []


@pytest.mark.unit
def test_backup_and_deployment_mutations_fail_without_adapters():
    context = ToolContext(workspace_id=uuid4(), user_id=uuid4(), agent_id=uuid4())
    backup = asyncio.run(BackupCreateTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_4_SYSTEM_CHANGES)).run({
            "backup_name": "claimed-backup", "backup_type": "full",
            "source_type": "database", "source_name": "db",
            "storage_location": "s3://not-configured", "storage_provider": "s3",
            "retention_days": 30,
        }, context))
    restore = asyncio.run(BackupRestoreTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_7_DEPLOYMENT)).run({
            "backup_id": str(uuid4()), "overwrite": False,
            "verify_before_restore": True,
        }, context))
    deploy = asyncio.run(ServiceDeployTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_7_DEPLOYMENT)).run({
            "deployment_name": "release", "deployment_type": "application",
            "environment": "staging", "version": "1.0.0",
        }, context))
    rollback = asyncio.run(DeploymentRollbackTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_7_DEPLOYMENT)).run({
            "deployment_id": str(uuid4()), "reason": "recovery test",
        }, context))

    for result in (backup, restore, deploy, rollback):
        assert result.success is False
        assert "adapter" in result.error_message.lower()


@pytest.mark.unit
def test_cost_estimate_labels_reference_pricing_and_rejects_unknown_provider():
    tool = CostEstimateTool(ToolConfig(authority_level=AuthorityLevel.LEVEL_2_FILE_OPERATIONS))
    context = ToolContext(workspace_id=uuid4(), user_id=uuid4())
    estimate = asyncio.run(tool.run({
        "resource_type": "vm", "provider": "aws",
        "config": {"instance_size": "small"}, "usage_hours": 10,
    }, context))
    unknown = asyncio.run(tool.run({
        "resource_type": "vm", "provider": "unlisted-provider",
    }, context))

    assert estimate.success is True
    assert estimate.result_data["live_pricing_used"] is False
    assert estimate.result_data["pricing_basis"] == "local_reference_rates"
    assert estimate.result_data["assumptions"]
    assert unknown.success is False
    assert "unsupported provider" in unknown.error_message.lower()


@pytest.mark.unit
def test_dns_tool_resolves_cname_mx_and_txt_records(monkeypatch):
    import dns.resolver

    records = {
        "CNAME": ["target.example.com."],
        "MX": ["10 mail.example.com."],
        "TXT": ['"v=spf1 include:example.com ~all"'],
    }

    def resolve(domain, record_type, lifetime=0):
        if record_type not in records:
            raise dns.resolver.NoAnswer
        return records[record_type]

    monkeypatch.setattr(dns.resolver, "resolve", resolve)
    from app.tools.infrastructure.monitoring import DNSVerifyTool

    result = asyncio.run(DNSVerifyTool(ToolConfig(
        authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS)).run({
            "domain": "www.example.com", "record_type": "CNAME",
            "expected_value": "target.example.com.",
            "check_mx_records": True, "check_txt_records": True,
        }, ToolContext()))

    assert result.success is True
    assert result.result_data["is_valid"] is True
    assert result.result_data["records"] == records["CNAME"]
    assert result.result_data["mx_records"] == records["MX"]
    assert result.result_data["txt_records"] == records["TXT"]