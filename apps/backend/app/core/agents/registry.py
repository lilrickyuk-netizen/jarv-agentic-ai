"""
JARV Backend - Agent Registry

Central registry for all JARV agents with discovery, instantiation, and metadata.
"""
from typing import Dict, List, Optional, Type, Any
from dataclasses import dataclass
import logging

from app.core.agents.base import AgentBase, AgentConfig, AuthorityLevel

logger = logging.getLogger(__name__)


@dataclass
class AgentMetadata:
    """Metadata about a registered agent"""
    name: str
    agent_class: Type[AgentBase]
    role: str
    required_authority_level: int
    default_tools: List[str]
    category: str
    description: str
    is_implemented: bool = True


class AgentRegistry:
    """
    Central registry for all JARV agents.

    The registry:
    - Discovers and registers all available agents
    - Provides agent instantiation by name
    - Lists all registered agents with metadata
    - Validates agent implementation completeness
    - Categorizes agents by function
    """

    # All 31 agents that must be implemented (from spec)
    REQUIRED_AGENTS = {
        # Core agents (1)
        "orchestrator": "Core orchestration and task delegation",

        # Development agents (6)
        "code-writer": "Writes code based on specifications",
        "code-reviewer": "Reviews code for quality and issues",
        "test-writer": "Creates unit and integration tests",
        "test-runner": "Executes tests and reports results",
        "debugger": "Debugs code and fixes issues",
        "refactorer": "Refactors code for better quality",

        # Infrastructure agents (4)
        "devops": "Handles DevOps and deployment tasks",
        "cloud-ops": "Manages cloud infrastructure",
        "database": "Manages database operations",
        "security": "Handles security scanning and fixes",

        # Business operations agents (6)
        "product-manager": "Product planning and roadmap",
        "project-manager": "Project coordination and tracking",
        "business-analyst": "Business analysis and requirements",
        "data-analyst": "Data analysis and insights",
        "researcher": "Research and information gathering",
        "documentation": "Technical documentation creation",

        # Customer-facing agents (5)
        "support": "Customer support and issue resolution",
        "marketing": "Marketing content and campaigns",
        "sales": "Sales outreach and tracking",
        "content-creator": "Content creation and management",
        "community-manager": "Community engagement",

        # Financial agents (3)
        "financial-analyst": "Financial analysis and reporting",
        "revenue-ops": "Revenue operations and tracking",
        "budget-planner": "Budget planning and management",

        # Specialized agents (6)
        "qa-tester": "Quality assurance testing",
        "legal-compliance": "Legal review and compliance",
        "onboarding": "User onboarding workflows",
        "partnership": "Partnership management",
        "risk-manager": "Risk assessment and mitigation",
        "audit": "System auditing and compliance",
    }

    # Agent categories
    CATEGORIES = {
        "core": ["orchestrator"],
        "development": ["code-writer", "code-reviewer", "test-writer", "test-runner", "debugger", "refactorer"],
        "infrastructure": ["devops", "cloud-ops", "database", "security"],
        "business": ["product-manager", "project-manager", "business-analyst", "data-analyst", "researcher", "documentation"],
        "customer": ["support", "marketing", "sales", "content-creator", "community-manager"],
        "financial": ["financial-analyst", "revenue-ops", "budget-planner"],
        "specialized": ["qa-tester", "legal-compliance", "onboarding", "partnership", "risk-manager", "audit"],
    }

    def __init__(self):
        """Initialize agent registry"""
        self._agents: Dict[str, AgentMetadata] = {}
        self._initialized = False
        logger.info("Agent registry created")

    def register(
        self,
        agent_class: Type[AgentBase],
        category: str,
        description: Optional[str] = None,
    ) -> None:
        """
        Register an agent class.

        Args:
            agent_class: Agent class to register (must inherit from AgentBase)
            category: Agent category (core, development, infrastructure, etc.)
            description: Optional detailed description

        Raises:
            ValueError: If agent class is invalid or already registered
        """
        # Validate agent class
        if not issubclass(agent_class, AgentBase):
            raise ValueError(f"Agent class {agent_class} must inherit from AgentBase")

        # Create temporary instance to get metadata
        temp_config = AgentConfig()
        temp_instance = agent_class(temp_config)

        agent_name = temp_instance.name

        # Check if already registered
        if agent_name in self._agents:
            logger.warning(f"Agent {agent_name} is already registered, overwriting")

        # Register agent
        metadata = AgentMetadata(
            name=agent_name,
            agent_class=agent_class,
            role=temp_instance.role,
            required_authority_level=temp_instance.required_authority_level.value,
            default_tools=temp_instance.default_tools,
            category=category,
            description=description or temp_instance.role,
            is_implemented=True,
        )

        self._agents[agent_name] = metadata
        logger.info(
            f"Registered agent: {agent_name}",
            extra={
                "category": category,
                "authority_level": metadata.required_authority_level,
            }
        )

    def register_placeholder(
        self,
        agent_name: str,
        category: str,
        description: str,
    ) -> None:
        """
        Register a placeholder for an unimplemented agent.

        This is used to track which agents still need to be implemented.

        Args:
            agent_name: Agent name
            category: Agent category
            description: Agent description
        """
        metadata = AgentMetadata(
            name=agent_name,
            agent_class=None,  # type: ignore
            role=description,
            required_authority_level=1,
            default_tools=[],
            category=category,
            description=description,
            is_implemented=False,
        )

        self._agents[agent_name] = metadata
        logger.debug(f"Registered placeholder for agent: {agent_name}")

    def get(self, agent_name: str) -> Optional[Type[AgentBase]]:
        """
        Get agent class by name.

        Args:
            agent_name: Name of agent to retrieve

        Returns:
            Agent class or None if not found or not implemented
        """
        metadata = self._agents.get(agent_name)
        if not metadata:
            return None
        if not metadata.is_implemented:
            return None
        return metadata.agent_class

    def create(
        self,
        agent_name: str,
        config: AgentConfig,
    ) -> Optional[AgentBase]:
        """
        Create an agent instance by name.

        Args:
            agent_name: Name of agent to create
            config: Agent configuration

        Returns:
            Agent instance or None if not found

        Raises:
            ValueError: If agent is not implemented
        """
        metadata = self._agents.get(agent_name)
        if not metadata:
            logger.error(f"Agent {agent_name} not found in registry")
            return None

        if not metadata.is_implemented:
            raise ValueError(
                f"Agent {agent_name} is registered but not yet implemented. "
                f"Please implement this agent before using it."
            )

        # Create instance
        agent = metadata.agent_class(config)
        logger.info(
            f"Created agent instance: {agent_name}",
            extra={
                "agent_id": str(config.agent_id),
                "authority_level": config.authority_level.value,
            }
        )
        return agent

    def list_all(self) -> List[AgentMetadata]:
        """
        Get list of all registered agents.

        Returns:
            List of agent metadata
        """
        return list(self._agents.values())

    def list_by_category(self, category: str) -> List[AgentMetadata]:
        """
        Get agents in a specific category.

        Args:
            category: Category name

        Returns:
            List of agent metadata in category
        """
        return [
            metadata
            for metadata in self._agents.values()
            if metadata.category == category
        ]

    def list_implemented(self) -> List[AgentMetadata]:
        """
        Get list of implemented agents.

        Returns:
            List of implemented agent metadata
        """
        return [
            metadata
            for metadata in self._agents.values()
            if metadata.is_implemented
        ]

    def list_unimplemented(self) -> List[AgentMetadata]:
        """
        Get list of unimplemented agents.

        Returns:
            List of unimplemented agent metadata
        """
        return [
            metadata
            for metadata in self._agents.values()
            if not metadata.is_implemented
        ]

    def get_metadata(self, agent_name: str) -> Optional[AgentMetadata]:
        """
        Get metadata for an agent.

        Args:
            agent_name: Agent name

        Returns:
            Agent metadata or None if not found
        """
        return self._agents.get(agent_name)

    def is_registered(self, agent_name: str) -> bool:
        """
        Check if an agent is registered.

        Args:
            agent_name: Agent name

        Returns:
            True if registered, False otherwise
        """
        return agent_name in self._agents

    def is_implemented(self, agent_name: str) -> bool:
        """
        Check if an agent is implemented.

        Args:
            agent_name: Agent name

        Returns:
            True if implemented, False otherwise
        """
        metadata = self._agents.get(agent_name)
        return metadata.is_implemented if metadata else False

    def get_categories(self) -> List[str]:
        """
        Get list of all categories.

        Returns:
            List of category names
        """
        return list(self.CATEGORIES.keys())

    def get_stats(self) -> Dict[str, Any]:
        """
        Get registry statistics.

        Returns:
            Dictionary with registry stats
        """
        total = len(self.REQUIRED_AGENTS)
        implemented = len(self.list_implemented())
        unimplemented = len(self.list_unimplemented())

        by_category = {}
        for category in self.CATEGORIES.keys():
            agents_in_cat = self.list_by_category(category)
            by_category[category] = {
                "total": len(agents_in_cat),
                "implemented": len([a for a in agents_in_cat if a.is_implemented]),
                "unimplemented": len([a for a in agents_in_cat if not a.is_implemented]),
            }

        return {
            "total_required": total,
            "total_registered": len(self._agents),
            "implemented": implemented,
            "unimplemented": unimplemented,
            "completion_percentage": (implemented / total * 100) if total > 0 else 0,
            "by_category": by_category,
        }

    def validate_completeness(self) -> Dict[str, Any]:
        """
        Validate that all required agents are implemented.

        Returns:
            Dictionary with validation results
        """
        missing = []
        placeholders = []

        for agent_name, description in self.REQUIRED_AGENTS.items():
            if not self.is_registered(agent_name):
                missing.append({"name": agent_name, "description": description})
            elif not self.is_implemented(agent_name):
                placeholders.append({"name": agent_name, "description": description})

        is_complete = len(missing) == 0 and len(placeholders) == 0

        return {
            "is_complete": is_complete,
            "total_required": len(self.REQUIRED_AGENTS),
            "total_registered": len(self._agents),
            "total_implemented": len(self.list_implemented()),
            "missing_agents": missing,
            "placeholder_agents": placeholders,
        }

    def initialize_placeholders(self) -> None:
        """
        Register placeholders for all unimplemented required agents.

        This ensures the registry knows about all 31 agents even if
        they're not yet implemented.
        """
        if self._initialized:
            return

        for agent_name, description in self.REQUIRED_AGENTS.items():
            if not self.is_registered(agent_name):
                # Find category for this agent
                category = "specialized"  # default
                for cat, agents in self.CATEGORIES.items():
                    if agent_name in agents:
                        category = cat
                        break

                self.register_placeholder(agent_name, category, description)

        self._initialized = True
        logger.info(
            f"Initialized agent registry with {len(self._agents)} agents",
            extra=self.get_stats()
        )


# Global registry instance
_registry: Optional[AgentRegistry] = None


def get_registry() -> AgentRegistry:
    """
    Get the global agent registry instance.

    Returns:
        AgentRegistry singleton
    """
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
        _registry.initialize_placeholders()

        # Import and register any implemented agents
        _register_implemented_agents(_registry)

    return _registry


def _register_implemented_agents(registry: AgentRegistry) -> None:
    """
    Register all implemented agents.

    This function imports and registers agents that have been implemented.
    All 31 specialist agents from Phase 13 are registered here.

    Args:
        registry: Registry to register agents in
    """
    # Import and register example agent (for demonstration)
    try:
        from app.core.agents.example_agent import ExampleAgent
        registry.register(ExampleAgent, category="specialized", description="Example agent for testing")
    except ImportError:
        logger.debug("Example agent not available for registration")

    # Core agents
    try:
        from app.agents.orchestrator import OrchestratorAgent
        registry.register(
            OrchestratorAgent,
            category="core",
            description="Core orchestration agent that coordinates tasks and delegates to specialist agents"
        )
    except ImportError:
        logger.debug("Orchestrator agent not available for registration")

    # Phase 13: Register all 31 specialist agents
    try:
        # Core Development Agents (6)
        from app.core.agents.specialists.coding_agent import CodingAgent
        from app.core.agents.specialists.debugging_agent import DebuggingAgent
        from app.core.agents.specialists.verifier import VerifierAgent
        from app.core.agents.specialists.qa import QAAgent
        from app.core.agents.specialists.devops import DevOpsAgent
        from app.core.agents.specialists.documentation import DocumentationAgent

        registry.register(CodingAgent, category="development", description="Writes, modifies, and reviews code across all languages")
        registry.register(DebuggingAgent, category="development", description="Debugs code, identifies issues, and proposes fixes")
        registry.register(VerifierAgent, category="development", description="Verifies code correctness, tests, and quality standards")
        registry.register(QAAgent, category="development", description="Performs quality assurance, testing, and validation")
        registry.register(DevOpsAgent, category="infrastructure", description="Manages deployments, CI/CD, and infrastructure operations")
        registry.register(DocumentationAgent, category="business", description="Creates and maintains technical documentation")

        # Intelligence Agents (3)
        from app.core.agents.specialists.research import ResearchAgent
        from app.core.agents.specialists.memory import MemoryAgent
        from app.core.agents.specialists.self_evolution import SelfEvolutionAgent

        registry.register(ResearchAgent, category="business", description="Researches technologies, solutions, and best practices")
        registry.register(MemoryAgent, category="specialized", description="Manages memories, learns from experiences, retrieves context")
        registry.register(SelfEvolutionAgent, category="specialized", description="Improves JARV's behavior from experience with safety guards")

        # Business Agents (6)
        from app.core.agents.specialists.company_operator import CompanyOperatorAgent
        from app.core.agents.specialists.workspace_manager import WorkspaceManagerAgent
        from app.core.agents.specialists.marketing import MarketingAgent
        from app.core.agents.specialists.growth import GrowthAgent
        from app.core.agents.specialists.business import BusinessAgent
        from app.core.agents.specialists.finance import FinanceAgent

        registry.register(CompanyOperatorAgent, category="business", description="Operates autonomous company layer with roles and plans")
        registry.register(WorkspaceManagerAgent, category="business", description="Manages workspace configuration, rules, and lifecycle")
        registry.register(MarketingAgent, category="customer", description="Creates marketing content, campaigns, and strategies")
        registry.register(GrowthAgent, category="customer", description="Drives user acquisition, activation, and retention")
        registry.register(BusinessAgent, category="business", description="Analyzes business metrics, creates reports, makes recommendations")
        registry.register(FinanceAgent, category="financial", description="Manages financial tracking, budgets, and reporting")

        # Operations Agents (5)
        from app.core.agents.specialists.monitoring import MonitoringAgent
        from app.core.agents.specialists.self_healing import SelfHealingAgent
        from app.core.agents.specialists.rollback import RollbackAgent
        from app.core.agents.specialists.security import SecurityAgent
        from app.core.agents.specialists.infrastructure import InfrastructureAgent

        registry.register(MonitoringAgent, category="infrastructure", description="Monitors systems, detects anomalies, alerts on issues")
        registry.register(SelfHealingAgent, category="infrastructure", description="Automatically detects and fixes system issues")
        registry.register(RollbackAgent, category="infrastructure", description="Safely rolls back deployments and changes")
        registry.register(SecurityAgent, category="infrastructure", description="Audits security, detects vulnerabilities, enforces policies")
        registry.register(InfrastructureAgent, category="infrastructure", description="Manages cloud infrastructure, scaling, and optimization")

        # Customer & Community Agents (4)
        from app.core.agents.specialists.customer_support import CustomerSupportAgent
        from app.core.agents.specialists.onboarding import OnboardingAgent
        from app.core.agents.specialists.community import CommunityAgent
        from app.core.agents.specialists.partnerships import PartnershipsAgent

        registry.register(CustomerSupportAgent, category="customer", description="Provides customer support, answers questions, resolves issues")
        registry.register(OnboardingAgent, category="customer", description="Creates onboarding experiences and user education")
        registry.register(CommunityAgent, category="customer", description="Manages community engagement, forums, and user relationships")
        registry.register(PartnershipsAgent, category="customer", description="Identifies and manages strategic partnerships")

        # Content & Creative Agents (2)
        from app.core.agents.specialists.creation import CreationAgent
        from app.core.agents.specialists.content import ContentAgent

        registry.register(CreationAgent, category="specialized", description="Creates assets, content, and creative materials")
        registry.register(ContentAgent, category="customer", description="Creates blog posts, articles, and educational content")

        # Compliance & Analytics Agents (3)
        from app.core.agents.specialists.legal import LegalAgent
        from app.core.agents.specialists.sales import SalesAgent
        from app.core.agents.specialists.analytics import AnalyticsAgent

        registry.register(LegalAgent, category="specialized", description="Drafts legal and compliance documents")
        registry.register(SalesAgent, category="customer", description="Manages sales processes, proposals, and customer relationships")
        registry.register(AnalyticsAgent, category="financial", description="Analyzes data, creates insights, and generates reports")

        logger.info("Successfully registered all 29 specialist agents from Phase 13")

    except ImportError as e:
        logger.warning(f"Failed to register some specialist agents: {e}")
    except Exception as e:
        logger.error(f"Error registering specialist agents: {e}", exc_info=True)


def register_agent(
    agent_class: Type[AgentBase],
    category: str,
    description: Optional[str] = None,
) -> None:
    """
    Convenience function to register an agent with the global registry.

    Args:
        agent_class: Agent class to register
        category: Agent category
        description: Optional description
    """
    registry = get_registry()
    registry.register(agent_class, category, description)


def create_agent(agent_name: str, config: AgentConfig) -> Optional[AgentBase]:
    """
    Convenience function to create an agent from the global registry.

    Args:
        agent_name: Name of agent to create
        config: Agent configuration

    Returns:
        Agent instance or None if not found
    """
    registry = get_registry()
    return registry.create(agent_name, config)


def list_agents(
    category: Optional[str] = None,
    only_implemented: bool = False,
) -> List[AgentMetadata]:
    """
    Convenience function to list agents from the global registry.

    Args:
        category: Optional category filter
        only_implemented: Only return implemented agents

    Returns:
        List of agent metadata
    """
    registry = get_registry()

    if category:
        agents = registry.list_by_category(category)
    else:
        agents = registry.list_all()

    if only_implemented:
        agents = [a for a in agents if a.is_implemented]

    return agents
