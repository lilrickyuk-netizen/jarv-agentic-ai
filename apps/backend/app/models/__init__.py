"""
JARV Backend Database Models

All SQLAlchemy models for the JARV system - Complete implementation.
"""
# Base models
from app.models.base import Base, TimestampMixin, UUIDMixin

# Core models
from app.models.user import User
from app.models.workspace import Workspace
from app.models.agent import Agent
from app.models.task import Task, task_dependencies
from app.models.memory import Memory
from app.models.session import AgentSession, CheckpointState
from app.models.approval import Approval
from app.models.tool import ToolUse
from app.models.company import CompanyRole

# Workspace rules and operations
from app.models.workspace_rules import (
    WorkspaceRule,
    WorkspaceRuleVersion,
    WorkspaceRunbook,
    WorkspaceScan,
)

# Operating plan models
from app.models.operating_plan import (
    OperatingPlan,
    OperatingPlanVersion,
    DailyOperatingLoop,
    WeeklyExecutionPlan,
)

# Company operations models
from app.models.company_operations import (
    AIStandup,
    KPIRecord,
    RevenueOperation,
    LiveOperationsFeedItem,
    RiskRegisterItem,
    DecisionLogItem,
)

# Agent strategy models
from app.models.agent_strategy import AgentStrategyVersion

# Tool system models
from app.models.tool_system import Tool, ToolRun, ToolSelectionRule

# Self evolution models
from app.models.self_evolution import (
    ExperienceRecord,
    SelfEvolutionRecord,
    VerificationResult,
)

# Runbook models
from app.models.runbook import Runbook, RunbookVersion

# Swarm models
from app.models.swarm import (
    SwarmRun,
    SubAgent,
    SubAgentTask,
    SubAgentLog,
    SwarmCostRecord,
    SwarmLimitPolicy,
)

# Boundary models
from app.models.boundary import (
    BoundaryReport,
    BoundaryApproval,
    ApprovalWindow,
    SafeCheckpoint,
    ResumeAction,
    RichardBoundaryInput,
)

# Execution models
from app.models.execution import CommandRun, FileChange

# Asset models
from app.models.assets import Asset, AssetLicence

# Business models
from app.models.business import (
    SupportTicket,
    MarketingCampaign,
    BusinessPlan,
    SalesRecord,
    PartnershipRecord,
)

# Operations models
from app.models.operations import (
    Incident,
    AuditLog,
    InfrastructureResource,
    BackupRecord,
    DeploymentRecord,
    AuthorityPolicy,
)

# Content models
from app.models.content import ContentItem, OnboardingFlow, CommunityItem

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    "UUIDMixin",
    # Core
    "User",
    "Workspace",
    "Agent",
    "Task",
    "task_dependencies",
    "Memory",
    "AgentSession",
    "CheckpointState",
    "Approval",
    "ToolUse",
    "CompanyRole",
    # Workspace rules
    "WorkspaceRule",
    "WorkspaceRuleVersion",
    "WorkspaceRunbook",
    "WorkspaceScan",
    # Operating plans
    "OperatingPlan",
    "OperatingPlanVersion",
    "DailyOperatingLoop",
    "WeeklyExecutionPlan",
    # Company operations
    "AIStandup",
    "KPIRecord",
    "RevenueOperation",
    "LiveOperationsFeedItem",
    "RiskRegisterItem",
    "DecisionLogItem",
    # Agent strategy
    "AgentStrategyVersion",
    # Tool system
    "Tool",
    "ToolRun",
    "ToolSelectionRule",
    # Self evolution
    "ExperienceRecord",
    "SelfEvolutionRecord",
    "VerificationResult",
    # Runbooks
    "Runbook",
    "RunbookVersion",
    # Swarm
    "SwarmRun",
    "SubAgent",
    "SubAgentTask",
    "SubAgentLog",
    "SwarmCostRecord",
    "SwarmLimitPolicy",
    # Boundary
    "BoundaryReport",
    "BoundaryApproval",
    "ApprovalWindow",
    "SafeCheckpoint",
    "ResumeAction",
    "RichardBoundaryInput",
    # Execution
    "CommandRun",
    "FileChange",
    # Assets
    "Asset",
    "AssetLicence",
    # Business
    "SupportTicket",
    "MarketingCampaign",
    "BusinessPlan",
    "SalesRecord",
    "PartnershipRecord",
    # Operations
    "Incident",
    "AuditLog",
    "InfrastructureResource",
    "BackupRecord",
    "DeploymentRecord",
    "AuthorityPolicy",
    # Content
    "ContentItem",
    "OnboardingFlow",
    "CommunityItem",
]
