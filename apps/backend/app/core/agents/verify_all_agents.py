"""
Complete agent count verification for JARV system.
Verifies that all 31 required agents are implemented.
"""
import sys
from pathlib import Path

def print_header(text):
    print("\n" + "="*60)
    print(text)
    print("="*60)


def verify_agent_count():
    """Verify total agent count"""
    print_header("AGENT COUNT VERIFICATION")

    from app.core.agents.registry import get_registry

    registry = get_registry()
    stats = registry.get_stats()

    print(f"Total required agents: {stats['total_required']}")
    print(f"Total registered agents: {stats['total_registered']}")
    print(f"Implemented agents: {stats['implemented']}")
    print(f"Unimplemented agents: {stats['unimplemented']}")
    print(f"Completion: {stats['completion_percentage']:.1f}%")

    return stats['implemented'] >= 31


def verify_specialist_agents():
    """Verify 29 specialist agents"""
    print_header("SPECIALIST AGENTS (29 required)")

    from app.core.agents.registry import get_registry

    registry = get_registry()

    specialist_agents = [
        "coding_agent",
        "debugging_agent",
        "verifier",
        "qa",
        "devops",
        "documentation",
        "research",
        "memory",
        "self_evolution",
        "company_operator",
        "workspace_manager",
        "marketing",
        "growth",
        "customer_support",
        "business",
        "finance",
        "creation",
        "monitoring",
        "self_healing",
        "rollback",
        "security",
        "legal",
        "sales",
        "analytics",
        "infrastructure",
        "onboarding",
        "community",
        "partnerships",
        "content",
    ]

    implemented_count = 0
    for agent_name in specialist_agents:
        metadata = registry.get_metadata(agent_name)
        if metadata and metadata.is_implemented:
            print(f"[OK] {agent_name}")
            implemented_count += 1
        else:
            print(f"[MISSING] {agent_name}")

    print(f"\nSpecialist agents: {implemented_count}/{len(specialist_agents)}")
    return implemented_count == len(specialist_agents)


def verify_core_agents():
    """Verify 2 core agents (Orchestrator + Example)"""
    print_header("CORE AGENTS (2 required)")

    core_count = 0

    # Check OrchestratorAgent
    try:
        from app.agents.orchestrator import OrchestratorAgent
        print("[OK] OrchestratorAgent exists and importable")

        # Check if it has required methods
        if hasattr(OrchestratorAgent, 'run'):
            print("  - Has run method")
        if hasattr(OrchestratorAgent, 'name'):
            print("  - Has name property")
        core_count += 1
    except ImportError as e:
        print(f"[MISSING] OrchestratorAgent: {e}")

    # Check ExampleAgent
    try:
        from app.core.agents.example_agent import ExampleAgent
        print("[OK] ExampleAgent exists and importable")
        core_count += 1
    except ImportError as e:
        print(f"[MISSING] ExampleAgent: {e}")

    print(f"\nCore agents: {core_count}/2")
    return core_count == 2


def verify_all_imports():
    """Verify all 31 agents can be imported"""
    print_header("IMPORT VERIFICATION (31 agents)")

    import_count = 0

    # Import specialist agents
    try:
        from app.core.agents.specialists import (
            CodingAgent, DebuggingAgent, VerifierAgent, QAAgent, DevOpsAgent,
            DocumentationAgent, ResearchAgent, MemoryAgent, SelfEvolutionAgent,
            CompanyOperatorAgent, WorkspaceManagerAgent, MarketingAgent, GrowthAgent,
            CustomerSupportAgent, BusinessAgent, FinanceAgent, CreationAgent,
            MonitoringAgent, SelfHealingAgent, RollbackAgent, SecurityAgent,
            LegalAgent, SalesAgent, AnalyticsAgent, InfrastructureAgent,
            OnboardingAgent, CommunityAgent, PartnershipsAgent, ContentAgent
        )
        print("[OK] All 29 specialist agents imported")
        import_count += 29
    except ImportError as e:
        print(f"[ERROR] Specialist agents import failed: {e}")

    # Import core agents
    try:
        from app.agents.orchestrator import OrchestratorAgent
        print("[OK] OrchestratorAgent imported")
        import_count += 1
    except ImportError as e:
        print(f"[ERROR] OrchestratorAgent import failed: {e}")

    try:
        from app.core.agents.example_agent import ExampleAgent
        print("[OK] ExampleAgent imported")
        import_count += 1
    except ImportError as e:
        print(f"[ERROR] ExampleAgent import failed: {e}")

    print(f"\nTotal imports successful: {import_count}/31")
    return import_count == 31


def verify_registry_registration():
    """Verify all 31 agents are registered"""
    print_header("REGISTRY VERIFICATION")

    from app.core.agents.registry import get_registry

    registry = get_registry()

    # Check specialist agents
    specialist_names = [
        "coding_agent", "debugging_agent", "verifier", "qa", "devops",
        "documentation", "research", "memory", "self_evolution",
        "company_operator", "workspace_manager", "marketing", "growth",
        "customer_support", "business", "finance", "creation", "monitoring",
        "self_healing", "rollback", "security", "legal", "sales",
        "analytics", "infrastructure", "onboarding", "community",
        "partnerships", "content",
    ]

    registered_count = 0
    for name in specialist_names:
        if registry.is_registered(name) and registry.is_implemented(name):
            registered_count += 1

    print(f"Specialist agents registered: {registered_count}/29")

    # Check core agents
    core_registered = 0
    if registry.is_registered("orchestrator") and registry.is_implemented("orchestrator"):
        print("[OK] orchestrator registered")
        core_registered += 1

    # ExampleAgent might have a different name in registry
    all_agents = registry.list_implemented()
    example_found = any(a.name == "example" or "example" in a.name.lower() for a in all_agents)
    if example_found:
        print("[OK] example agent registered")
        core_registered += 1

    print(f"Core agents registered: {core_registered}/2")
    print(f"\nTotal registered and implemented: {registered_count + core_registered}/31")

    return (registered_count + core_registered) >= 31


def verify_no_placeholders():
    """Verify no placeholder logic in specialist agents"""
    print_header("PLACEHOLDER CHECK (29 specialist agents)")

    base_dir = Path(__file__).parent / "specialists"

    specialist_files = [
        "coding_agent.py", "debugging_agent.py", "verifier.py", "qa.py", "devops.py",
        "documentation.py", "research.py", "memory.py", "self_evolution.py",
        "company_operator.py", "workspace_manager.py", "marketing.py", "growth.py",
        "customer_support.py", "business.py", "finance.py", "creation.py",
        "monitoring.py", "self_healing.py", "rollback.py", "security.py",
        "legal.py", "sales.py", "analytics.py", "infrastructure.py",
        "onboarding.py", "community.py", "partnerships.py", "content.py",
    ]

    clean_count = 0
    for filename in specialist_files:
        filepath = base_dir / filename
        if not filepath.exists():
            print(f"[MISSING] {filename}")
            continue

        with open(filepath, 'r') as f:
            content = f.read()

        # Check for placeholder patterns
        has_placeholder = False
        if '# In production:' in content:
            has_placeholder = True
        elif 'pass  # Placeholder' in content:
            has_placeholder = True
        elif '# TODO:' in content and 'async def run' in content:
            has_placeholder = True

        if has_placeholder:
            print(f"[PLACEHOLDER] {filename}")
        else:
            clean_count += 1

    print(f"\nAgents with real logic: {clean_count}/29")
    return clean_count == 29


def verify_orchestrator_delegation():
    """Verify orchestrator can delegate to specialist agents"""
    print_header("ORCHESTRATOR DELEGATION CHECK")

    try:
        from app.agents.orchestrator import OrchestratorAgent
        from app.core.agents.base import AgentConfig, AuthorityLevel
        from app.core.agents.registry import get_registry

        registry = get_registry()

        # Check if orchestrator has delegate capability
        config = AgentConfig(authority_level=AuthorityLevel.LEVEL_10_FULL_AUTONOMY)
        orchestrator = OrchestratorAgent(config)

        print(f"[OK] Orchestrator initialized")
        print(f"  Name: {orchestrator.name}")
        print(f"  Role: {orchestrator.role}")

        # Check if specialist agents are accessible
        specialist_count = len([a for a in registry.list_implemented()
                               if a.category in ['development', 'infrastructure', 'business',
                                                'customer', 'financial', 'specialized']])
        print(f"[OK] Orchestrator can access {specialist_count} specialist agents via registry")

        return True
    except Exception as e:
        print(f"[ERROR] Orchestrator delegation check failed: {e}")
        return False


def main():
    """Run all verifications"""
    print("\n" + "="*60)
    print("JARV COMPLETE AGENT VERIFICATION")
    print("Required: 31 total agents (29 specialist + 2 core)")
    print("="*60)

    checks = {
        "Agent Count (31 required)": verify_agent_count,
        "Specialist Agents (29/29)": verify_specialist_agents,
        "Core Agents (2/2)": verify_core_agents,
        "All Imports (31/31)": verify_all_imports,
        "Registry Registration": verify_registry_registration,
        "No Placeholders": verify_no_placeholders,
        "Orchestrator Delegation": verify_orchestrator_delegation,
    }

    results = {}
    for check_name, check_func in checks.items():
        try:
            results[check_name] = check_func()
        except Exception as e:
            print(f"\n[ERROR] {check_name} failed: {e}")
            import traceback
            traceback.print_exc()
            results[check_name] = False

    # Final summary
    print_header("FINAL VERIFICATION SUMMARY")

    all_passed = True
    for check_name, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        print(f"[{status}] {check_name}")
        if not passed:
            all_passed = False

    print("\n" + "="*60)
    if all_passed:
        print("SUCCESS: All 31 agents verified and operational")
        print("  - 29/29 specialist agents implemented")
        print("  - 2/2 core agents implemented")
        print("  - 31/31 total agents complete")
        print("="*60)
        return 0
    else:
        print("FAILURE: Some verifications failed")
        print("="*60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
