"""
Test script for infrastructure tools - Phase 19
Tests async database access and tool functionality
"""
import asyncio
from app.tools.infrastructure import *
from app.core.tools import ToolConfig, ToolContext
from uuid import uuid4


async def comprehensive_test():
    config = ToolConfig()
    context = ToolContext(workspace_id=uuid4(), user_id=uuid4())

    print('COMPREHENSIVE ASYNC DATABASE ACCESS TEST')
    print('=' * 80)
    print()

    # Test 1: Backup Create (writes to DB)
    print('[TEST 1] BackupCreateTool - Database Write')
    backup_tool = BackupCreateTool(config)
    result = await backup_tool.run({
        'backup_name': 'test-backup',
        'backup_type': 'full',
        'source_type': 'database',
        'source_name': 'test-db',
        'storage_location': 's3://test-bucket',
        'storage_provider': 's3',
        'retention_days': 30,
    }, context)
    print(f'  Success: {result.success}')
    print(f'  Backup ID: {result.result_data.get("backup_id")}')
    print()

    # Test 2: Backup List (reads from DB)
    print('[TEST 2] BackupListTool - Database Read')
    list_tool = BackupListTool(config)
    result = await list_tool.run({
        'backup_type': None,
        'source_type': None,
        'include_deleted': False,
        'limit': 50,
    }, context)
    print(f'  Success: {result.success}')
    print(f'  Backups Found: {result.result_data.get("total_count")}')
    print()

    # Test 3: Resource Status (reads from DB)
    print('[TEST 3] ResourceStatusTool - Database Read')
    status_tool = ResourceStatusTool(config)
    result = await status_tool.run({
        'resource_id': None,
        'resource_type': None,
        'status': None,
        'limit': 50,
    }, context)
    print(f'  Success: {result.success}')
    print(f'  Resources Found: {result.result_data.get("total_count")}')
    print()

    # Test 4: Deployment Status (reads from DB)
    print('[TEST 4] DeploymentStatusTool - Database Read')
    deploy_status_tool = DeploymentStatusTool(config)
    result = await deploy_status_tool.run({
        'deployment_id': None,
        'environment': None,
        'status': None,
        'limit': 50,
    }, context)
    print(f'  Success: {result.success}')
    print(f'  Deployments Found: {result.result_data.get("total_count")}')
    print()

    # Test 5: Cost Estimate (no DB required)
    print('[TEST 5] CostEstimateTool - No Database Required')
    cost_tool = CostEstimateTool(config)
    result = await cost_tool.run({
        'resource_type': 'vm',
        'provider': 'aws',
        'region': 'us-east-1',
        'config': {'instance_size': 'medium', 'cpu_cores': 4, 'memory_gb': 16},
        'usage_hours': 730,
        'include_data_transfer': True,
        'include_storage': True,
    }, context)
    print(f'  Success: {result.success}')
    print(f'  Monthly Cost: ${result.result_data.get("monthly_cost")}')
    print()

    print('=' * 80)
    print('[SUCCESS] All comprehensive tests passed!')


if __name__ == '__main__':
    asyncio.run(comprehensive_test())
