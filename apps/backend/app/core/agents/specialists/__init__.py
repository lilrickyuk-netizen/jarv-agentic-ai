"""
JARV Backend - Specialist Agents

All 29 specialized agents for JARV system.
"""
# Core Development Agents
from app.core.agents.specialists.coding_agent import CodingAgent
from app.core.agents.specialists.debugging_agent import DebuggingAgent
from app.core.agents.specialists.verifier import VerifierAgent
from app.core.agents.specialists.qa import QAAgent
from app.core.agents.specialists.devops import DevOpsAgent
from app.core.agents.specialists.documentation import DocumentationAgent

# Intelligence Agents
from app.core.agents.specialists.research import ResearchAgent
from app.core.agents.specialists.memory import MemoryAgent
from app.core.agents.specialists.self_evolution import SelfEvolutionAgent

# Business Agents
from app.core.agents.specialists.company_operator import CompanyOperatorAgent
from app.core.agents.specialists.workspace_manager import WorkspaceManagerAgent
from app.core.agents.specialists.marketing import MarketingAgent
from app.core.agents.specialists.growth import GrowthAgent
from app.core.agents.specialists.business import BusinessAgent
from app.core.agents.specialists.finance import FinanceAgent

# Operations Agents
from app.core.agents.specialists.monitoring import MonitoringAgent
from app.core.agents.specialists.self_healing import SelfHealingAgent
from app.core.agents.specialists.rollback import RollbackAgent
from app.core.agents.specialists.security import SecurityAgent
from app.core.agents.specialists.infrastructure import InfrastructureAgent

# Customer & Community Agents
from app.core.agents.specialists.customer_support import CustomerSupportAgent
from app.core.agents.specialists.onboarding import OnboardingAgent
from app.core.agents.specialists.community import CommunityAgent
from app.core.agents.specialists.partnerships import PartnershipsAgent

# Content & Creative Agents
from app.core.agents.specialists.creation import CreationAgent
from app.core.agents.specialists.content import ContentAgent

# Compliance & Analytics Agents
from app.core.agents.specialists.legal import LegalAgent
from app.core.agents.specialists.sales import SalesAgent
from app.core.agents.specialists.analytics import AnalyticsAgent

__all__ = [
    # Core Development Agents
    "CodingAgent",
    "DebuggingAgent",
    "VerifierAgent",
    "QAAgent",
    "DevOpsAgent",
    "DocumentationAgent",

    # Intelligence Agents
    "ResearchAgent",
    "MemoryAgent",
    "SelfEvolutionAgent",

    # Business Agents
    "CompanyOperatorAgent",
    "WorkspaceManagerAgent",
    "MarketingAgent",
    "GrowthAgent",
    "SalesAgent",
    "BusinessAgent",
    "FinanceAgent",

    # Operations Agents
    "MonitoringAgent",
    "SelfHealingAgent",
    "RollbackAgent",
    "SecurityAgent",
    "InfrastructureAgent",

    # Customer & Community Agents
    "CustomerSupportAgent",
    "OnboardingAgent",
    "CommunityAgent",
    "PartnershipsAgent",

    # Content & Creative Agents
    "CreationAgent",
    "ContentAgent",
    "DocumentationAgent",

    # Compliance Agents
    "LegalAgent",
    "AnalyticsAgent",
]
