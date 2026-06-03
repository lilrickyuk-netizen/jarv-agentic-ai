"""
Comprehensive Phase 19 Test - All 18 Infrastructure Tools

Tests all infrastructure tools for Phase 19: Backup, Resources, Deployment, Monitoring, Cost
"""
import sys
from pathlib import Path
import uuid
import asyncio

sys.path.insert(0, str(Path(__file__).parent))

from app.core.tools import ToolContext, ToolConfig
from app.core.agents.base import AuthorityLevel
from app.tools.infrastructure import (
    # Backup & Restore
    BackupCreateTool,
    BackupRestoreTool,
    BackupListTool,
    BackupVerifyTool,
    BackupCleanupTool,
    # Resource Management
    ResourceProvisionTool,
    ResourceScaleTool,
    ResourceHealthCheckTool,
    ResourceStatusTool,
    ResourceTerminateTool,
    # Deployment
    ServiceDeployTool,
    DeploymentStatusTool,
    DeploymentRollbackTool,
    DeploymentLogsTool,
    # Monitoring
    SSLCheckTool,
    DNSVerifyTool,
    ResourceMetricsTool,
    # Cost
    CostEstimateTool,
)


def print_header(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def print_check(message, passed):
    status = "[OK]" if passed else "[FAIL]"
    print(f"{status} {message}")


async def test_all_infrastructure_tools():
    """Test all 18 infrastructure tools"""
    print_header("PHASE 19: ALL 18 INFRASTRUCTURE TOOLS TEST")

    # Use None for workspace_id to avoid foreign key constraints
    workspace_id = None
    user_id = uuid.uuid4()

    context = ToolContext(
        workspace_id=workspace_id,
        user_id=user_id,
    )

    # Create tool config with high authority for testing
    tool_config = ToolConfig(
        workspace_id=workspace_id,
        user_id=user_id,
        authority_level=AuthorityLevel.LEVEL_7_DEPLOYMENT,
    )

    results = {}
    tool_count = 0

    # ===== BACKUP & RESTORE TOOLS =====
    print("\n[BACKUP & RESTORE TOOLS]")

    # Test 1: Backup Create
    print("\n[TEST 1] BackupCreateTool")
    try:
        tool = BackupCreateTool(tool_config)
        result = await tool.run({
            "backup_name": "test-db-backup",
            "backup_type": "database",
            "source_type": "postgresql",
            "source_name": "main-database",
            "source_id": "main-db",
            "storage_location": "s3",
            "storage_provider": "s3",
            "retention_days": 30,
        }, context)
        print_check(f"  Tool executed", result.success)
        print_check(f"  Backup created", "backup_id" in result.result_data)
        results["BackupCreateTool"] = result.success
        tool_count += 1
    except Exception as e:
        print_check(f"  BackupCreateTool failed: {e}", False)
        results["BackupCreateTool"] = False

    # Test 2: Backup List
    print("\n[TEST 2] BackupListTool")
    try:
        tool = BackupListTool(tool_config)
        result = await tool.run({
            "backup_type": "database",
            "limit": 10,
            "include_expired": False,
        }, context)
        print_check(f"  Tool executed", result.success)
        print_check(f"  Backups listed", "backups" in result.result_data)
        results["BackupListTool"] = result.success
        tool_count += 1
    except Exception as e:
        print_check(f"  BackupListTool failed: {e}", False)
        results["BackupListTool"] = False

    # Test 3: Backup Verify
    print("\n[TEST 3] BackupVerifyTool")
    try:
        tool = BackupVerifyTool(tool_config)
        # Create a backup first to verify
        create_tool = BackupCreateTool(tool_config)
        create_result = await create_tool.run({
            "backup_name": "verify-test-backup",
            "backup_type": "database",
            "source_type": "postgresql",
            "source_name": "test-database",
            "source_id": "test-db",
            "storage_location": "local",
            "storage_provider": "local",
            "retention_days": 7,
        }, context)

        if create_result.success:
            backup_id = create_result.result_data["backup_id"]
            result = await tool.run({
                "backup_id": backup_id,
                "check_integrity": True,
                "check_restorability": True,
            }, context)
            print_check(f"  Tool executed", result.success)
            print_check(f"  Backup verified", "is_valid" in result.result_data)
            results["BackupVerifyTool"] = result.success
        else:
            results["BackupVerifyTool"] = False
        tool_count += 1
    except Exception as e:
        print_check(f"  BackupVerifyTool failed: {e}", False)
        results["BackupVerifyTool"] = False

    # Test 4: Backup Restore
    print("\n[TEST 4] BackupRestoreTool")
    try:
        tool = BackupRestoreTool(tool_config)
        # Use the backup created in test 3
        if "backup_id" in locals():
            result = await tool.run({
                "backup_id": backup_id,
                "verify_before_restore": False,  # Skip verification for test
            }, context)
            print_check(f"  Tool executed", result.success)
            print_check(f"  Backup restored", "restored_items" in result.result_data)
            results["BackupRestoreTool"] = result.success
        else:
            results["BackupRestoreTool"] = False
        tool_count += 1
    except Exception as e:
        print_check(f"  BackupRestoreTool failed: {e}", False)
        results["BackupRestoreTool"] = False

    # Test 5: Backup Cleanup
    print("\n[TEST 5] BackupCleanupTool")
    try:
        tool = BackupCleanupTool(tool_config)
        result = await tool.run({
            "older_than_days": 90,
            "dry_run": True,  # Dry run for test
        }, context)
        print_check(f"  Tool executed", result.success)
        print_check(f"  Cleanup performed", "deleted_count" in result.result_data)
        results["BackupCleanupTool"] = result.success
        tool_count += 1
    except Exception as e:
        print_check(f"  BackupCleanupTool failed: {e}", False)
        results["BackupCleanupTool"] = False

    # ===== RESOURCE MANAGEMENT TOOLS =====
    print("\n[RESOURCE MANAGEMENT TOOLS]")

    # Test 6: Resource Provision
    print("\n[TEST 6] ResourceProvisionTool")
    try:
        tool = ResourceProvisionTool(tool_config)
        result = await tool.run({
            "resource_name": "test-server",
            "resource_type": "server",
            "provider": "aws",
            "region": "us-east-1",
            "capacity": {"cpu": 4, "memory": 16, "storage": 100},
            "tags": {"env": "test", "project": "jarv"},
        }, context)
        print_check(f"  Tool executed", result.success)
        print_check(f"  Resource provisioned", "resource_id" in result.result_data)
        resource_id = result.result_data.get("resource_id") if result.success else None
        results["ResourceProvisionTool"] = result.success
        tool_count += 1
    except Exception as e:
        print_check(f"  ResourceProvisionTool failed: {e}", False)
        results["ResourceProvisionTool"] = False

    # Test 7: Resource Status
    print("\n[TEST 7] ResourceStatusTool")
    try:
        tool = ResourceStatusTool(tool_config)
        result = await tool.run({
            "resource_type": "server",
            "provider": "aws",
        }, context)
        print_check(f"  Tool executed", result.success)
        print_check(f"  Resource status retrieved", "resources" in result.result_data)
        results["ResourceStatusTool"] = result.success
        tool_count += 1
    except Exception as e:
        print_check(f"  ResourceStatusTool failed: {e}", False)
        results["ResourceStatusTool"] = False

    # Test 8: Resource Health Check
    print("\n[TEST 8] ResourceHealthCheckTool")
    try:
        tool = ResourceHealthCheckTool(tool_config)
        if resource_id:
            result = await tool.run({
                "resource_id": resource_id,
                "check_connectivity": True,
                "check_performance": True,
            }, context)
            print_check(f"  Tool executed", result.success)
            print_check(f"  Health check completed", "health_status" in result.result_data)
            results["ResourceHealthCheckTool"] = result.success
        else:
            results["ResourceHealthCheckTool"] = False
        tool_count += 1
    except Exception as e:
        print_check(f"  ResourceHealthCheckTool failed: {e}", False)
        results["ResourceHealthCheckTool"] = False

    # Test 9: Resource Scale
    print("\n[TEST 9] ResourceScaleTool")
    try:
        tool = ResourceScaleTool(tool_config)
        if resource_id:
            result = await tool.run({
                "resource_id": resource_id,
                "new_capacity": {"cpu": 8, "memory": 32, "storage": 200},
                "scale_type": "vertical",
            }, context)
            print_check(f"  Tool executed", result.success)
            print_check(f"  Resource scaled", "cost_impact" in result.result_data)
            results["ResourceScaleTool"] = result.success
        else:
            results["ResourceScaleTool"] = False
        tool_count += 1
    except Exception as e:
        print_check(f"  ResourceScaleTool failed: {e}", False)
        results["ResourceScaleTool"] = False

    # Test 10: Resource Terminate
    print("\n[TEST 10] ResourceTerminateTool")
    try:
        tool = ResourceTerminateTool(tool_config)
        if resource_id:
            result = await tool.run({
                "resource_id": resource_id,
                "force": False,
                "backup_before_terminate": False,
            }, context)
            print_check(f"  Tool executed", result.success)
            print_check(f"  Resource terminated", "cost_savings_monthly" in result.result_data)
            results["ResourceTerminateTool"] = result.success
        else:
            results["ResourceTerminateTool"] = False
        tool_count += 1
    except Exception as e:
        print_check(f"  ResourceTerminateTool failed: {e}", False)
        results["ResourceTerminateTool"] = False

    # ===== DEPLOYMENT TOOLS =====
    print("\n[DEPLOYMENT TOOLS]")

    # Test 11: Service Deploy
    print("\n[TEST 11] ServiceDeployTool")
    try:
        tool = ServiceDeployTool(tool_config)
        result = await tool.run({
            "deployment_name": "jarv-backend-deploy",
            "deployment_type": "application",
            "environment": "staging",
            "version": "v1.0.0",
            "commit_sha": "abc123def456",
            "branch": "main",
            "changes": ["Fix bug in authentication", "Add new API endpoint"],
        }, context)
        print_check(f"  Tool executed", result.success)
        print_check(f"  Service deployed", "deployment_id" in result.result_data)
        deployment_id = result.result_data.get("deployment_id") if result.success else None
        results["ServiceDeployTool"] = result.success
        tool_count += 1
    except Exception as e:
        print_check(f"  ServiceDeployTool failed: {e}", False)
        results["ServiceDeployTool"] = False

    # Test 12: Deployment Status
    print("\n[TEST 12] DeploymentStatusTool")
    try:
        tool = DeploymentStatusTool(tool_config)
        result = await tool.run({
            "environment": "staging",
            "limit": 10,
        }, context)
        print_check(f"  Tool executed", result.success)
        print_check(f"  Deployment status retrieved", "deployments" in result.result_data)
        results["DeploymentStatusTool"] = result.success
        tool_count += 1
    except Exception as e:
        print_check(f"  DeploymentStatusTool failed: {e}", False)
        results["DeploymentStatusTool"] = False

    # Test 13: Deployment Logs
    print("\n[TEST 13] DeploymentLogsTool")
    try:
        tool = DeploymentLogsTool(tool_config)
        if deployment_id:
            result = await tool.run({
                "deployment_id": deployment_id,
                "tail": 100,
            }, context)
            print_check(f"  Tool executed", result.success)
            print_check(f"  Deployment logs retrieved", "logs" in result.result_data)
            results["DeploymentLogsTool"] = result.success
        else:
            results["DeploymentLogsTool"] = False
        tool_count += 1
    except Exception as e:
        print_check(f"  DeploymentLogsTool failed: {e}", False)
        results["DeploymentLogsTool"] = False

    # Test 14: Deployment Rollback
    print("\n[TEST 14] DeploymentRollbackTool")
    try:
        tool = DeploymentRollbackTool(tool_config)
        if deployment_id:
            result = await tool.run({
                "deployment_id": deployment_id,
                "reason": "Testing rollback functionality",
            }, context)
            print_check(f"  Tool executed", result.success)
            print_check(f"  Deployment rolled back", "rollback_deployment_id" in result.result_data)
            results["DeploymentRollbackTool"] = result.success
        else:
            results["DeploymentRollbackTool"] = False
        tool_count += 1
    except Exception as e:
        print_check(f"  DeploymentRollbackTool failed: {e}", False)
        results["DeploymentRollbackTool"] = False

    # ===== MONITORING TOOLS =====
    print("\n[MONITORING TOOLS]")

    # Test 15: SSL Check
    print("\n[TEST 15] SSLCheckTool")
    try:
        tool = SSLCheckTool(tool_config)
        result = await tool.run({
            "domain": "example.com",
            "port": 443,
            "check_expiry": True,
            "warn_days_before_expiry": 30,
        }, context)
        print_check(f"  Tool executed", result.success)
        print_check(f"  SSL check completed", "is_valid" in result.result_data)
        results["SSLCheckTool"] = result.success
        tool_count += 1
    except Exception as e:
        print_check(f"  SSLCheckTool failed: {e}", False)
        results["SSLCheckTool"] = False

    # Test 16: DNS Verify
    print("\n[TEST 16] DNSVerifyTool")
    try:
        tool = DNSVerifyTool(tool_config)
        result = await tool.run({
            "domain": "example.com",
            "expected_ip": "192.0.2.1",
            "check_mx_records": True,
            "check_txt_records": True,
        }, context)
        print_check(f"  Tool executed", result.success)
        print_check(f"  DNS verification completed", "a_records" in result.result_data)
        results["DNSVerifyTool"] = result.success
        tool_count += 1
    except Exception as e:
        print_check(f"  DNSVerifyTool failed: {e}", False)
        results["DNSVerifyTool"] = False

    # Test 17: Resource Metrics
    print("\n[TEST 17] ResourceMetricsTool")
    try:
        # Create a test resource first
        provision_tool = ResourceProvisionTool(tool_config)
        provision_result = await provision_tool.run({
            "resource_name": "metrics-test-server",
            "resource_type": "server",
            "provider": "aws",
            "region": "us-east-1",
            "capacity": {"cpu": 2, "memory": 8},
        }, context)

        if provision_result.success:
            metrics_resource_id = provision_result.result_data["resource_id"]
            tool = ResourceMetricsTool(tool_config)
            result = await tool.run({
                "resource_id": metrics_resource_id,
                "metric_types": ["cpu", "memory", "disk", "network"],
                "time_range_minutes": 60,
            }, context)
            print_check(f"  Tool executed", result.success)
            print_check(f"  Resource metrics retrieved", "metrics" in result.result_data)
            results["ResourceMetricsTool"] = result.success
        else:
            results["ResourceMetricsTool"] = False
        tool_count += 1
    except Exception as e:
        print_check(f"  ResourceMetricsTool failed: {e}", False)
        results["ResourceMetricsTool"] = False

    # ===== COST ANALYSIS TOOL =====
    print("\n[COST ANALYSIS TOOL]")

    # Test 18: Cost Estimate
    print("\n[TEST 18] CostEstimateTool")
    try:
        tool = CostEstimateTool(tool_config)
        result = await tool.run({
            "resource_type": None,  # All resources
            "time_period": "monthly",
            "include_projected": True,
            "growth_rate_percent": 10.0,
        }, context)
        print_check(f"  Tool executed", result.success)
        print_check(f"  Cost estimate generated", "total_cost" in result.result_data)
        print_check(f"  Cost breakdown provided", "cost_breakdown" in result.result_data)
        print_check(f"  Optimization suggestions provided", "cost_optimization_suggestions" in result.result_data)
        results["CostEstimateTool"] = result.success
        tool_count += 1
    except Exception as e:
        print_check(f"  CostEstimateTool failed: {e}", False)
        results["CostEstimateTool"] = False

    return results, tool_count


async def main():
    """Run all tests"""
    results, tool_count = await test_all_infrastructure_tools()

    # Summary
    print_header("PHASE 19 COMPLETE - INFRASTRUCTURE TOOLS SUMMARY")

    print("\n[ALL TOOLS BY CATEGORY]")
    print("\nBackup & Restore (5 tools):")
    print_check("  1. BackupCreateTool", results.get("BackupCreateTool", False))
    print_check("  2. BackupRestoreTool", results.get("BackupRestoreTool", False))
    print_check("  3. BackupListTool", results.get("BackupListTool", False))
    print_check("  4. BackupVerifyTool", results.get("BackupVerifyTool", False))
    print_check("  5. BackupCleanupTool", results.get("BackupCleanupTool", False))

    print("\nResource Management (5 tools):")
    print_check("  6. ResourceProvisionTool", results.get("ResourceProvisionTool", False))
    print_check("  7. ResourceScaleTool", results.get("ResourceScaleTool", False))
    print_check("  8. ResourceHealthCheckTool", results.get("ResourceHealthCheckTool", False))
    print_check("  9. ResourceStatusTool", results.get("ResourceStatusTool", False))
    print_check("  10. ResourceTerminateTool", results.get("ResourceTerminateTool", False))

    print("\nDeployment (4 tools):")
    print_check("  11. ServiceDeployTool", results.get("ServiceDeployTool", False))
    print_check("  12. DeploymentStatusTool", results.get("DeploymentStatusTool", False))
    print_check("  13. DeploymentRollbackTool", results.get("DeploymentRollbackTool", False))
    print_check("  14. DeploymentLogsTool", results.get("DeploymentLogsTool", False))

    print("\nMonitoring (3 tools):")
    print_check("  15. SSLCheckTool", results.get("SSLCheckTool", False))
    print_check("  16. DNSVerifyTool", results.get("DNSVerifyTool", False))
    print_check("  17. ResourceMetricsTool", results.get("ResourceMetricsTool", False))

    print("\nCost Analysis (1 tool):")
    print_check("  18. CostEstimateTool", results.get("CostEstimateTool", False))

    print("\n" + "=" * 70)
    print("PHASE 19 STATISTICS")
    print("=" * 70)
    print(f"Total Infrastructure Tools: {tool_count}")
    print(f"All Tools Passing: {sum(results.values())}/{len(results)}")

    print("\n[INFRASTRUCTURE FEATURES COVERED]")
    print("  - Backup creation and management")
    print("  - Backup restoration and verification")
    print("  - Resource provisioning and scaling")
    print("  - Resource health monitoring")
    print("  - Deployment automation")
    print("  - Deployment rollback")
    print("  - SSL certificate checking")
    print("  - DNS configuration verification")
    print("  - Resource metrics monitoring")
    print("  - Cost estimation and optimization")

    print("\n[DATABASE MODELS USED]")
    print("  - InfrastructureResource (resource tracking)")
    print("  - BackupRecord (backup management)")
    print("  - DeploymentRecord (deployment history)")

    if all(results.values()):
        print("\n[SUCCESS] All Phase 19 infrastructure tools passed!")
        print("\nPhase 19 has complete infrastructure tool coverage:")
        print("  - 18 infrastructure tools implemented and tested")
        print("  - 3 database models utilized")
        print("  - Backup, resource, deployment, monitoring, and cost features covered")
        print("\nPhase 19 infrastructure tools are ready!")
        return 0
    else:
        print("\n[FAILURE] Some infrastructure tools failed")
        failed = [name for name, passed in results.items() if not passed]
        print(f"Failed tools: {', '.join(failed)}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
