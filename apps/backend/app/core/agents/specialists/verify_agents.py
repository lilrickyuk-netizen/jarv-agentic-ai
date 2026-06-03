"""
Verification script for all specialist agents.

Checks that all 29 specialist agents are:
1. Importable
2. Properly implemented (no placeholders)
3. Registered in the registry
4. Have correct authority levels and tools
"""
import sys
import re
from pathlib import Path
from typing import List, Dict, Any

# Color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def print_success(msg: str):
    print(f"{GREEN}[OK]{RESET} {msg}")


def print_error(msg: str):
    print(f"{RED}[ERROR]{RESET} {msg}")


def print_warning(msg: str):
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def print_info(msg: str):
    print(f"{BLUE}[INFO]{RESET} {msg}")


# List of all 29 specialist agents
EXPECTED_AGENTS = [
    "coding_agent.py",
    "debugging_agent.py",
    "verifier.py",
    "qa.py",
    "devops.py",
    "documentation.py",
    "research.py",
    "memory.py",
    "self_evolution.py",
    "company_operator.py",
    "workspace_manager.py",
    "marketing.py",
    "growth.py",
    "customer_support.py",
    "business.py",
    "finance.py",
    "creation.py",
    "monitoring.py",
    "self_healing.py",
    "rollback.py",
    "security.py",
    "legal.py",
    "sales.py",
    "analytics.py",
    "infrastructure.py",
    "onboarding.py",
    "community.py",
    "partnerships.py",
    "content.py",
]


def check_files_exist() -> bool:
    """Check that all agent files exist"""
    print("\n" + "="*60)
    print("CHECK 1: Verifying all agent files exist")
    print("="*60)

    base_dir = Path(__file__).parent
    all_exist = True

    for agent_file in EXPECTED_AGENTS:
        filepath = base_dir / agent_file
        if filepath.exists():
            print_success(f"{agent_file} exists")
        else:
            print_error(f"{agent_file} NOT FOUND")
            all_exist = False

    if all_exist:
        print_success(f"\nAll {len(EXPECTED_AGENTS)} agent files exist")
    else:
        print_error(f"\nSome agent files are missing")

    return all_exist


def check_no_placeholders() -> bool:
    """Check that no agents have placeholder logic"""
    print("\n" + "="*60)
    print("CHECK 2: Verifying no placeholder logic in run methods")
    print("="*60)

    base_dir = Path(__file__).parent
    all_good = True

    # Patterns that indicate placeholder/incomplete implementation
    placeholder_patterns = [
        r'pass\s*$',  # Just 'pass'
        r'#\s*TODO',  # TODO comments
        r'#\s*In production:',  # "In production" comments without actual implementation
        r'result_data\s*=\s*\{\s*"completed":\s*True,\s*"summary":\s*"Task completed successfully"',  # Generic placeholder
    ]

    for agent_file in EXPECTED_AGENTS:
        filepath = base_dir / agent_file
        if not filepath.exists():
            continue

        with open(filepath, 'r') as f:
            content = f.read()

        # Find the run method
        run_method_match = re.search(
            r'async def run\([\s\S]*?\n([\s\S]*?)(?=\n    def |\n    @property|\nclass |\Z)',
            content
        )

        if not run_method_match:
            print_error(f"{agent_file}: Could not find run method")
            all_good = False
            continue

        run_method_code = run_method_match.group(1)

        # Check for placeholder patterns
        has_placeholder = False
        for pattern in placeholder_patterns:
            if re.search(pattern, run_method_code, re.MULTILINE):
                has_placeholder = True
                break

        # Check for actual logic (should have result_data with specific fields)
        has_logic = 'result_data' in run_method_code and 'self.logger.info' in run_method_code

        if has_placeholder or not has_logic:
            print_error(f"{agent_file}: Contains placeholder logic")
            all_good = False
        else:
            print_success(f"{agent_file}: Real implementation found")

    if all_good:
        print_success(f"\nAll agents have real implementations")
    else:
        print_error(f"\nSome agents still have placeholder logic")

    return all_good


def check_imports() -> bool:
    """Check that all agents can be imported"""
    print("\n" + "="*60)
    print("CHECK 3: Verifying all agents can be imported")
    print("="*60)

    all_imported = True

    try:
        from app.core.agents.specialists.coding_agent import CodingAgent
        print_success("CodingAgent imported")
    except Exception as e:
        print_error(f"CodingAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.debugging_agent import DebuggingAgent
        print_success("DebuggingAgent imported")
    except Exception as e:
        print_error(f"DebuggingAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.verifier import VerifierAgent
        print_success("VerifierAgent imported")
    except Exception as e:
        print_error(f"VerifierAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.qa import QAAgent
        print_success("QAAgent imported")
    except Exception as e:
        print_error(f"QAAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.devops import DevOpsAgent
        print_success("DevOpsAgent imported")
    except Exception as e:
        print_error(f"DevOpsAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.documentation import DocumentationAgent
        print_success("DocumentationAgent imported")
    except Exception as e:
        print_error(f"DocumentationAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.research import ResearchAgent
        print_success("ResearchAgent imported")
    except Exception as e:
        print_error(f"ResearchAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.memory import MemoryAgent
        print_success("MemoryAgent imported")
    except Exception as e:
        print_error(f"MemoryAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.self_evolution import SelfEvolutionAgent
        print_success("SelfEvolutionAgent imported")
    except Exception as e:
        print_error(f"SelfEvolutionAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.company_operator import CompanyOperatorAgent
        print_success("CompanyOperatorAgent imported")
    except Exception as e:
        print_error(f"CompanyOperatorAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.workspace_manager import WorkspaceManagerAgent
        print_success("WorkspaceManagerAgent imported")
    except Exception as e:
        print_error(f"WorkspaceManagerAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.marketing import MarketingAgent
        print_success("MarketingAgent imported")
    except Exception as e:
        print_error(f"MarketingAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.growth import GrowthAgent
        print_success("GrowthAgent imported")
    except Exception as e:
        print_error(f"GrowthAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.customer_support import CustomerSupportAgent
        print_success("CustomerSupportAgent imported")
    except Exception as e:
        print_error(f"CustomerSupportAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.business import BusinessAgent
        print_success("BusinessAgent imported")
    except Exception as e:
        print_error(f"BusinessAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.finance import FinanceAgent
        print_success("FinanceAgent imported")
    except Exception as e:
        print_error(f"FinanceAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.creation import CreationAgent
        print_success("CreationAgent imported")
    except Exception as e:
        print_error(f"CreationAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.monitoring import MonitoringAgent
        print_success("MonitoringAgent imported")
    except Exception as e:
        print_error(f"MonitoringAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.self_healing import SelfHealingAgent
        print_success("SelfHealingAgent imported")
    except Exception as e:
        print_error(f"SelfHealingAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.rollback import RollbackAgent
        print_success("RollbackAgent imported")
    except Exception as e:
        print_error(f"RollbackAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.security import SecurityAgent
        print_success("SecurityAgent imported")
    except Exception as e:
        print_error(f"SecurityAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.legal import LegalAgent
        print_success("LegalAgent imported")
    except Exception as e:
        print_error(f"LegalAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.sales import SalesAgent
        print_success("SalesAgent imported")
    except Exception as e:
        print_error(f"SalesAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.analytics import AnalyticsAgent
        print_success("AnalyticsAgent imported")
    except Exception as e:
        print_error(f"AnalyticsAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.infrastructure import InfrastructureAgent
        print_success("InfrastructureAgent imported")
    except Exception as e:
        print_error(f"InfrastructureAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.onboarding import OnboardingAgent
        print_success("OnboardingAgent imported")
    except Exception as e:
        print_error(f"OnboardingAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.community import CommunityAgent
        print_success("CommunityAgent imported")
    except Exception as e:
        print_error(f"CommunityAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.partnerships import PartnershipsAgent
        print_success("PartnershipsAgent imported")
    except Exception as e:
        print_error(f"PartnershipsAgent import failed: {e}")
        all_imported = False

    try:
        from app.core.agents.specialists.content import ContentAgent
        print_success("ContentAgent imported")
    except Exception as e:
        print_error(f"ContentAgent import failed: {e}")
        all_imported = False

    if all_imported:
        print_success(f"\nAll 29 agents imported successfully")
    else:
        print_error(f"\nSome agents failed to import")

    return all_imported


def check_registry() -> bool:
    """Check that all agents are registered in the registry"""
    print("\n" + "="*60)
    print("CHECK 4: Verifying all agents are registered")
    print("="*60)

    try:
        from app.core.agents.registry import get_registry

        registry = get_registry()
        stats = registry.get_stats()

        print_info(f"Total registered agents: {stats['total_registered']}")
        print_info(f"Implemented agents: {stats['implemented']}")
        print_info(f"Unimplemented agents: {stats['unimplemented']}")

        # Check if our 29 specialist agents are registered
        specialist_count = 0
        agents = registry.list_all()

        expected_names = [
            "coding_agent", "debugging_agent", "verifier", "qa", "devops",
            "documentation", "research", "memory", "self_evolution",
            "company_operator", "workspace_manager", "marketing", "growth",
            "customer_support", "business", "finance", "creation", "monitoring",
            "self_healing", "rollback", "security", "legal", "sales",
            "analytics", "infrastructure", "onboarding", "community",
            "partnerships", "content"
        ]

        for agent_name in expected_names:
            metadata = registry.get_metadata(agent_name)
            if metadata and metadata.is_implemented:
                print_success(f"{agent_name} is registered and implemented")
                specialist_count += 1
            elif metadata:
                print_warning(f"{agent_name} is registered but not implemented")
            else:
                print_error(f"{agent_name} is NOT registered")

        print_info(f"\nSpecialist agents registered: {specialist_count}/29")

        if specialist_count == 29:
            print_success("All 29 specialist agents are registered")
            return True
        else:
            print_error(f"Missing {29 - specialist_count} specialist agents")
            return False

    except Exception as e:
        print_error(f"Registry check failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification checks"""
    print("\n" + "="*60)
    print("JARV SPECIALIST AGENTS VERIFICATION")
    print("="*60)

    checks = [
        ("Files Exist", check_files_exist),
        ("No Placeholders", check_no_placeholders),
        ("Imports Work", check_imports),
        ("Registry Complete", check_registry),
    ]

    results = {}
    for check_name, check_func in checks:
        try:
            results[check_name] = check_func()
        except Exception as e:
            print_error(f"Check '{check_name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results[check_name] = False

    # Final summary
    print("\n" + "="*60)
    print("VERIFICATION SUMMARY")
    print("="*60)

    all_passed = True
    for check_name, passed in results.items():
        if passed:
            print_success(f"{check_name}: PASSED")
        else:
            print_error(f"{check_name}: FAILED")
            all_passed = False

    print("\n" + "="*60)
    if all_passed:
        print_success("ALL CHECKS PASSED")
        print_success("Phase 13: Specialist Agents is COMPLETE")
        print("="*60)
        return 0
    else:
        print_error("SOME CHECKS FAILED")
        print_error("Phase 13: Specialist Agents needs more work")
        print("="*60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
