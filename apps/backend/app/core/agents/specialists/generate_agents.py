"""
Script to generate all 31 specialist agent implementations.
"""
from pathlib import Path

AGENT_SPECS = [
    {
        "name": "debugging_agent",
        "class": "DebuggingAgent",
        "role": "Debugs code, identifies issues, and proposes fixes",
        "authority": "LEVEL_3_CODE_EXECUTION",
        "tools": ["file_read", "file_search", "git_diff", "command_run", "analyze_code"],
    },
    {
        "name": "verifier",
        "class": "VerifierAgent",
        "role": "Verifies code correctness, tests, and quality standards",
        "authority": "LEVEL_3_CODE_EXECUTION",
        "tools": ["file_read", "command_run", "analyze_code", "analyze_coverage"],
    },
    {
        "name": "qa",
        "class": "QAAgent",
        "role": "Performs quality assurance, testing, and validation",
        "authority": "LEVEL_3_CODE_EXECUTION",
        "tools": ["file_read", "command_run", "analyze_code"],
    },
    {
        "name": "devops",
        "class": "DevOpsAgent",
        "role": "Manages deployments, CI/CD, and infrastructure operations",
        "authority": "LEVEL_7_DEPLOYMENT",
        "tools": ["command_run", "file_read", "file_write", "git_push"],
    },
    {
        "name": "documentation",
        "class": "DocumentationAgent",
        "role": "Creates and maintains technical documentation",
        "authority": "LEVEL_2_FILE_OPERATIONS",
        "tools": ["file_read", "file_write", "file_search", "analyze_code"],
    },
    {
        "name": "research",
        "class": "ResearchAgent",
        "role": "Researches technologies, solutions, and best practices",
        "authority": "LEVEL_5_NETWORK_ACCESS",
        "tools": ["http_get", "http_post", "file_read", "memory_search"],
    },
    {
        "name": "memory",
        "class": "MemoryAgent",
        "role": "Manages memories, learns from experiences, retrieves context",
        "authority": "LEVEL_6_DATABASE_WRITE",
        "tools": ["memory_store", "memory_retrieve", "memory_search", "memory_update"],
    },
    {
        "name": "self_evolution",
        "class": "SelfEvolutionAgent",
        "role": "Improves JARV's behavior from experience with safety guards",
        "authority": "LEVEL_8_FINANCIAL",  # High authority for system modifications
        "tools": ["experience_log_success", "experience_query_pattern", "memory_search"],
    },
    {
        "name": "company_operator",
        "class": "CompanyOperatorAgent",
        "role": "Operates autonomous company layer with roles and plans",
        "authority": "LEVEL_9_SWARM_CREATION",
        "tools": ["workspace_create", "workspace_update", "memory_store"],
    },
    {
        "name": "workspace_manager",
        "class": "WorkspaceManagerAgent",
        "role": "Manages workspace configuration, rules, and lifecycle",
        "authority": "LEVEL_6_DATABASE_WRITE",
        "tools": ["workspace_create", "workspace_update", "workspace_list"],
    },
    {
        "name": "marketing",
        "class": "MarketingAgent",
        "role": "Creates marketing content, campaigns, and strategies",
        "authority": "LEVEL_5_NETWORK_ACCESS",
        "tools": ["file_write", "http_post", "memory_retrieve"],
    },
    {
        "name": "growth",
        "class": "GrowthAgent",
        "role": "Drives user acquisition, activation, and retention",
        "authority": "LEVEL_5_NETWORK_ACCESS",
        "tools": ["http_get", "http_post", "memory_retrieve", "analyze_metrics"],
    },
    {
        "name": "customer_support",
        "class": "CustomerSupportAgent",
        "role": "Provides customer support, answers questions, resolves issues",
        "authority": "LEVEL_2_FILE_OPERATIONS",
        "tools": ["memory_search", "file_read", "http_get"],
    },
    {
        "name": "business",
        "class": "BusinessAgent",
        "role": "Analyzes business metrics, creates reports, makes recommendations",
        "authority": "LEVEL_6_DATABASE_WRITE",
        "tools": ["analyze_metrics", "memory_retrieve", "file_write"],
    },
    {
        "name": "finance",
        "class": "FinanceAgent",
        "role": "Manages financial tracking, budgets, and reporting",
        "authority": "LEVEL_8_FINANCIAL",
        "tools": ["analyze_metrics", "memory_retrieve", "file_write"],
    },
    {
        "name": "creation",
        "class": "CreationAgent",
        "role": "Creates assets, content, and creative materials",
        "authority": "LEVEL_2_FILE_OPERATIONS",
        "tools": ["file_write", "http_get", "memory_retrieve"],
    },
    {
        "name": "monitoring",
        "class": "MonitoringAgent",
        "role": "Monitors systems, detects anomalies, alerts on issues",
        "authority": "LEVEL_5_NETWORK_ACCESS",
        "tools": ["http_get", "analyze_metrics", "memory_store"],
    },
    {
        "name": "self_healing",
        "class": "SelfHealingAgent",
        "role": "Automatically detects and fixes system issues",
        "authority": "LEVEL_7_DEPLOYMENT",
        "tools": ["command_run", "file_write", "git_commit", "analyze_metrics"],
    },
    {
        "name": "rollback",
        "class": "RollbackAgent",
        "role": "Safely rolls back deployments and changes",
        "authority": "LEVEL_7_DEPLOYMENT",
        "tools": ["git_revert", "git_reset", "command_run"],
    },
    {
        "name": "security",
        "class": "SecurityAgent",
        "role": "Audits security, detects vulnerabilities, enforces policies",
        "authority": "LEVEL_6_DATABASE_WRITE",
        "tools": ["analyze_security", "file_read", "analyze_code"],
    },
    {
        "name": "legal",
        "class": "LegalAgent",
        "role": "Drafts legal and compliance documents",
        "authority": "LEVEL_2_FILE_OPERATIONS",
        "tools": ["file_read", "file_write", "memory_retrieve"],
    },
    {
        "name": "sales",
        "class": "SalesAgent",
        "role": "Manages sales processes, proposals, and customer relationships",
        "authority": "LEVEL_5_NETWORK_ACCESS",
        "tools": ["crm_create_contact", "crm_update_deal", "email_send", "file_write"],
    },
    {
        "name": "analytics",
        "class": "AnalyticsAgent",
        "role": "Analyzes data, creates insights, and generates reports",
        "authority": "LEVEL_6_DATABASE_WRITE",
        "tools": ["analyze_metrics", "memory_retrieve", "file_write"],
    },
    {
        "name": "infrastructure",
        "class": "InfrastructureAgent",
        "role": "Manages cloud infrastructure, scaling, and optimization",
        "authority": "LEVEL_7_DEPLOYMENT",
        "tools": ["command_run", "http_post", "analyze_metrics"],
    },
    {
        "name": "onboarding",
        "class": "OnboardingAgent",
        "role": "Creates onboarding experiences and user education",
        "authority": "LEVEL_2_FILE_OPERATIONS",
        "tools": ["file_write", "memory_retrieve", "http_post"],
    },
    {
        "name": "community",
        "class": "CommunityAgent",
        "role": "Manages community engagement, forums, and user relationships",
        "authority": "LEVEL_5_NETWORK_ACCESS",
        "tools": ["http_get", "http_post", "memory_retrieve", "slack_send"],
    },
    {
        "name": "partnerships",
        "class": "PartnershipsAgent",
        "role": "Identifies and manages strategic partnerships",
        "authority": "LEVEL_5_NETWORK_ACCESS",
        "tools": ["crm_create_contact", "email_send", "file_write", "memory_retrieve"],
    },
    {
        "name": "content",
        "class": "ContentAgent",
        "role": "Creates blog posts, articles, and educational content",
        "authority": "LEVEL_2_FILE_OPERATIONS",
        "tools": ["file_write", "http_get", "memory_retrieve"],
    },
]


TEMPLATE = '''"""
JARV Backend - {class_name}

{role}
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class {class_name}Input(BaseModel):
    """{class_name} input"""
    task: str = Field(..., description="Task description")
    context: Dict[str, Any] = Field(default_factory=dict)


class {class_name}Output(BaseModel):
    """{class_name} output"""
    completed: bool
    summary: str
    details: Dict[str, Any] = Field(default_factory=dict)


class {class_name}(AgentBase):
    """
    {class_name} - {role}
    """

    @property
    def name(self) -> str:
        return "{agent_name}"

    @property
    def role(self) -> str:
        return "{role}"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return {class_name}Input

    @property
    def output_schema(self) -> Type[BaseModel]:
        return {class_name}Output

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.{authority_level}

    @property
    def default_tools(self) -> list[str]:
        return {tools_list}

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """
        Execute task.

        Args:
            input_data: Task input
            context: Execution context

        Returns:
            Agent result
        """
        try:
            self.logger.info(f"Starting {agent_name} task")

            # In production: Implement agent-specific logic
            # Connect to: Orchestrator, Tool registry, Memory system,
            # Authority system, Audit log, Live Operations Feed

            result_data = {{
                "completed": True,
                "summary": "Task completed successfully",
                "details": {{}},
            }}

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Completed {agent_name} task",
                tools_used=self.default_tools[:2],  # Placeholder
            )

        except Exception as e:
            self.logger.error(f"{agent_name} task failed: {{e}}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={{}},
                error_message=str(e),
            )
'''


def generate_agents():
    """Generate all agent files"""
    base_dir = Path(__file__).parent

    for spec in AGENT_SPECS:
        filename = f"{spec['name']}.py"
        filepath = base_dir / filename

        if filepath.exists():
            print(f"Skipping {filename} (already exists)")
            continue

        content = TEMPLATE.format(
            class_name=spec["class"],
            role=spec["role"],
            agent_name=spec["name"],
            authority_level=spec["authority"],
            tools_list=spec["tools"],
        )

        with open(filepath, 'w') as f:
            f.write(content)

        print(f"Generated {filename}")

    print(f"\nGenerated {len(AGENT_SPECS)} agent files")


if __name__ == "__main__":
    generate_agents()
