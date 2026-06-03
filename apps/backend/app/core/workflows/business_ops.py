"""
JARV Backend - Business Operations Workflow System

Orchestrates business operation workflows across marketing, growth, business analysis,
sales, finance, and revenue optimization using specialist agents.
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
import logging
import uuid

from app.core.agents.registry import get_registry
from app.core.agents.base import AgentContext, AgentConfig

logger = logging.getLogger(__name__)


class WorkflowType(str, Enum):
    """Business workflow types"""
    MARKETING_CAMPAIGN = "marketing_campaign"
    GROWTH_STRATEGY = "growth_strategy"
    BUSINESS_ANALYSIS = "business_analysis"
    SALES_PIPELINE = "sales_pipeline"
    FINANCE_REPORT = "finance_report"
    REVENUE_OPTIMIZATION = "revenue_optimization"
    QUARTERLY_REVIEW = "quarterly_review"


class WorkflowStatus(str, Enum):
    """Workflow execution status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentExecution(BaseModel):
    """Record of agent execution in workflow"""
    agent_name: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    success: bool = False
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    duration_seconds: float = 0.0


class WorkflowResult(BaseModel):
    """Result of business workflow execution"""
    workflow_id: str
    workflow_type: WorkflowType
    status: WorkflowStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    agents_executed: List[AgentExecution] = Field(default_factory=list)
    final_output: Dict[str, Any] = Field(default_factory=dict)
    recommendations: List[str] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    duration_seconds: float = 0.0


class BusinessOperationsWorkflow:
    """
    Orchestrates business operation workflows using specialist agents.

    Provides end-to-end workflows for:
    - Marketing campaign creation and execution
    - Growth strategy development
    - Business analysis and reporting
    - Sales pipeline management
    - Financial reporting and tracking
    - Revenue optimization strategies
    """

    def __init__(self):
        """Initialize business operations workflow system"""
        self.logger = logging.getLogger(__name__)
        self.registry = get_registry()

    async def run_marketing_campaign(
        self,
        campaign_type: str,
        target_audience: str,
        message: str,
        channels: List[str],
        budget: float,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WorkflowResult:
        """
        Execute marketing campaign workflow.

        Workflow steps:
        1. MarketingAgent - Create campaign
        2. GrowthAgent - Analyze growth potential
        3. FinanceAgent - Track budget
        4. BusinessAgent - Report on performance

        Args:
            campaign_type: Type of campaign (social, email, content, etc.)
            target_audience: Target audience description
            message: Campaign message/theme
            channels: Marketing channels to use
            budget: Campaign budget
            workspace_id: Workspace context
            user_id: User executing workflow

        Returns:
            WorkflowResult with campaign details
        """
        workflow_id = str(uuid.uuid4())
        started_at = datetime.utcnow()
        agents_executed = []

        self.logger.info(f"Starting marketing campaign workflow {workflow_id}")

        try:
            # Create context
            context = AgentContext(
                workspace_id=workspace_id,
                user_id=user_id,
                task_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
            )

            config = AgentConfig(
                max_tokens=2000,
                temperature=0.7,
                model_provider="claude",
            )

            # Step 1: Marketing Agent - Create campaign
            marketing_agent_class = self.registry.get("marketing")
            marketing_agent = marketing_agent_class(config=config)

            marketing_start = datetime.utcnow()
            marketing_result = await marketing_agent.run(
                {
                    "campaign_type": campaign_type,
                    "target_audience": target_audience,
                    "message": message,
                    "channels": channels,
                },
                context,
            )
            marketing_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="marketing",
                started_at=marketing_start,
                completed_at=marketing_end,
                success=marketing_result.success,
                output=marketing_result.result_data,
                error=marketing_result.error_message,
                duration_seconds=(marketing_end - marketing_start).total_seconds(),
            ))

            if not marketing_result.success:
                raise Exception(f"Marketing agent failed: {marketing_result.error_message}")

            # Step 2: Growth Agent - Analyze growth potential
            growth_agent_class = self.registry.get("growth")
            growth_agent = growth_agent_class(config=config)

            growth_start = datetime.utcnow()
            growth_result = await growth_agent.run(
                {
                    "growth_metric": "user_acquisition",
                    "current_value": 1000,  # Would come from analytics
                    "target_value": 5000,
                    "timeframe": "90 days",
                },
                context,
            )
            growth_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="growth",
                started_at=growth_start,
                completed_at=growth_end,
                success=growth_result.success,
                output=growth_result.result_data,
                error=growth_result.error_message,
                duration_seconds=(growth_end - growth_start).total_seconds(),
            ))

            # Step 3: Finance Agent - Track budget
            finance_agent_class = self.registry.get("finance")
            finance_agent = finance_agent_class(config=config)

            finance_start = datetime.utcnow()
            finance_result = await finance_agent.run(
                {
                    "operation": "allocate_budget",
                    "time_period": "Q1 2026",
                    "amount": budget,
                    "category": "marketing",
                },
                context,
            )
            finance_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="finance",
                started_at=finance_start,
                completed_at=finance_end,
                success=finance_result.success,
                output=finance_result.result_data,
                error=finance_result.error_message,
                duration_seconds=(finance_end - finance_start).total_seconds(),
            ))

            # Step 4: Business Agent - Generate report
            business_agent_class = self.registry.get("business")
            business_agent = business_agent_class(config=config)

            business_start = datetime.utcnow()
            business_result = await business_agent.run(
                {
                    "report_type": "marketing_campaign",
                    "time_period": "current",
                    "metrics": ["reach", "engagement", "conversion", "roi"],
                },
                context,
            )
            business_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="business",
                started_at=business_start,
                completed_at=business_end,
                success=business_result.success,
                output=business_result.result_data,
                error=business_result.error_message,
                duration_seconds=(business_end - business_start).total_seconds(),
            ))

            # Compile final output
            completed_at = datetime.utcnow()
            final_output = {
                "campaign": marketing_result.result_data,
                "growth_analysis": growth_result.result_data,
                "budget_tracking": finance_result.result_data,
                "business_report": business_result.result_data,
            }

            recommendations = [
                "Monitor campaign performance daily for first week",
                "Adjust targeting based on early engagement data",
                "A/B test messaging across channels",
                "Track ROI and adjust budget allocation",
            ]

            metrics = {
                "estimated_reach": marketing_result.result_data.get("estimated_reach", 0),
                "budget_allocated": budget,
                "growth_potential": growth_result.result_data.get("estimated_impact", "medium"),
                "agents_executed": len(agents_executed),
            }

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.MARKETING_CAMPAIGN,
                status=WorkflowStatus.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output=final_output,
                recommendations=recommendations,
                metrics=metrics,
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

        except Exception as e:
            self.logger.error(f"Marketing campaign workflow failed: {e}", exc_info=True)
            completed_at = datetime.utcnow()

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.MARKETING_CAMPAIGN,
                status=WorkflowStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output={},
                recommendations=["Review error and retry workflow"],
                metrics={},
                error_message=str(e),
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

    async def run_sales_pipeline(
        self,
        operation: str,
        contact_info: Dict[str, str],
        deal_value: float,
        stage: str,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WorkflowResult:
        """
        Execute sales pipeline workflow.

        Workflow steps:
        1. SalesAgent - Manage sales operation
        2. BusinessAgent - Analyze deal metrics
        3. FinanceAgent - Track revenue forecast

        Args:
            operation: Sales operation (create_lead, update_deal, etc.)
            contact_info: Contact information
            deal_value: Deal value in dollars
            stage: Sales stage
            workspace_id: Workspace context
            user_id: User executing workflow

        Returns:
            WorkflowResult with sales pipeline details
        """
        workflow_id = str(uuid.uuid4())
        started_at = datetime.utcnow()
        agents_executed = []

        self.logger.info(f"Starting sales pipeline workflow {workflow_id}")

        try:
            context = AgentContext(
                workspace_id=workspace_id,
                user_id=user_id,
                task_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
            )

            config = AgentConfig(
                max_tokens=2000,
                temperature=0.7,
                model_provider="claude",
            )

            # Step 1: Sales Agent
            sales_agent_class = self.registry.get("sales")
            sales_agent = sales_agent_class(config=config)

            sales_start = datetime.utcnow()
            sales_result = await sales_agent.run(
                {
                    "operation": operation,
                    "contact_info": contact_info,
                    "deal_value": deal_value,
                    "stage": stage,
                },
                context,
            )
            sales_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="sales",
                started_at=sales_start,
                completed_at=sales_end,
                success=sales_result.success,
                output=sales_result.result_data,
                error=sales_result.error_message,
                duration_seconds=(sales_end - sales_start).total_seconds(),
            ))

            if not sales_result.success:
                raise Exception(f"Sales agent failed: {sales_result.error_message}")

            # Step 2: Business Agent - Analyze metrics
            business_agent_class = self.registry.get("business")
            business_agent = business_agent_class(config=config)

            business_start = datetime.utcnow()
            business_result = await business_agent.run(
                {
                    "report_type": "sales_pipeline",
                    "time_period": "current",
                    "metrics": ["conversion_rate", "average_deal_size", "sales_velocity"],
                },
                context,
            )
            business_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="business",
                started_at=business_start,
                completed_at=business_end,
                success=business_result.success,
                output=business_result.result_data,
                error=business_result.error_message,
                duration_seconds=(business_end - business_start).total_seconds(),
            ))

            # Step 3: Finance Agent - Revenue forecast
            finance_agent_class = self.registry.get("finance")
            finance_agent = finance_agent_class(config=config)

            finance_start = datetime.utcnow()
            finance_result = await finance_agent.run(
                {
                    "operation": "forecast_revenue",
                    "time_period": "Q1 2026",
                    "amount": deal_value,
                    "category": "sales",
                },
                context,
            )
            finance_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="finance",
                started_at=finance_start,
                completed_at=finance_end,
                success=finance_result.success,
                output=finance_result.result_data,
                error=finance_result.error_message,
                duration_seconds=(finance_end - finance_start).total_seconds(),
            ))

            # Compile results
            completed_at = datetime.utcnow()
            final_output = {
                "sales_operation": sales_result.result_data,
                "business_metrics": business_result.result_data,
                "revenue_forecast": finance_result.result_data,
            }

            win_probability = sales_result.result_data.get("win_probability", 0.5)
            recommendations = [
                f"Follow up on next steps: {', '.join(sales_result.result_data.get('next_steps', []))}",
                f"Win probability: {win_probability * 100}%",
                "Update CRM with latest contact information",
                "Schedule follow-up meeting within 48 hours",
            ]

            metrics = {
                "deal_value": deal_value,
                "win_probability": win_probability,
                "forecasted_revenue": deal_value * win_probability,
                "agents_executed": len(agents_executed),
            }

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.SALES_PIPELINE,
                status=WorkflowStatus.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output=final_output,
                recommendations=recommendations,
                metrics=metrics,
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

        except Exception as e:
            self.logger.error(f"Sales pipeline workflow failed: {e}", exc_info=True)
            completed_at = datetime.utcnow()

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.SALES_PIPELINE,
                status=WorkflowStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output={},
                recommendations=["Review error and retry workflow"],
                metrics={},
                error_message=str(e),
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

    async def run_quarterly_review(
        self,
        quarter: str,
        year: int,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WorkflowResult:
        """
        Execute comprehensive quarterly business review.

        Workflow steps:
        1. FinanceAgent - Financial performance
        2. SalesAgent - Sales performance
        3. MarketingAgent - Marketing performance
        4. GrowthAgent - Growth metrics
        5. BusinessAgent - Comprehensive report

        Args:
            quarter: Quarter (Q1, Q2, Q3, Q4)
            year: Year
            workspace_id: Workspace context
            user_id: User executing workflow

        Returns:
            WorkflowResult with quarterly review
        """
        workflow_id = str(uuid.uuid4())
        started_at = datetime.utcnow()
        agents_executed = []

        self.logger.info(f"Starting quarterly review workflow {workflow_id} for {quarter} {year}")

        try:
            context = AgentContext(
                workspace_id=workspace_id,
                user_id=user_id,
                task_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
            )

            config = AgentConfig(
                max_tokens=2000,
                temperature=0.7,
                model_provider="claude",
            )

            time_period = f"{quarter} {year}"

            # Step 1: Finance Agent
            finance_agent_class = self.registry.get("finance")
            finance_agent = finance_agent_class(config=config)

            finance_start = datetime.utcnow()
            finance_result = await finance_agent.run(
                {
                    "operation": "generate_report",
                    "time_period": time_period,
                    "amount": 0,
                    "category": "quarterly_review",
                },
                context,
            )
            finance_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="finance",
                started_at=finance_start,
                completed_at=finance_end,
                success=finance_result.success,
                output=finance_result.result_data,
                duration_seconds=(finance_end - finance_start).total_seconds(),
            ))

            # Step 2: Sales Agent
            sales_agent_class = self.registry.get("sales")
            sales_agent = sales_agent_class(config=config)

            sales_start = datetime.utcnow()
            sales_result = await sales_agent.run(
                {
                    "operation": "report_performance",
                    "contact_info": {},
                    "deal_value": 0,
                    "stage": time_period,
                },
                context,
            )
            sales_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="sales",
                started_at=sales_start,
                completed_at=sales_end,
                success=sales_result.success,
                output=sales_result.result_data,
                duration_seconds=(sales_end - sales_start).total_seconds(),
            ))

            # Step 3: Marketing Agent
            marketing_agent_class = self.registry.get("marketing")
            marketing_agent = marketing_agent_class(config=config)

            marketing_start = datetime.utcnow()
            marketing_result = await marketing_agent.run(
                {
                    "campaign_type": "quarterly_summary",
                    "target_audience": "all",
                    "message": time_period,
                    "channels": ["summary"],
                },
                context,
            )
            marketing_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="marketing",
                started_at=marketing_start,
                completed_at=marketing_end,
                success=marketing_result.success,
                output=marketing_result.result_data,
                duration_seconds=(marketing_end - marketing_start).total_seconds(),
            ))

            # Step 4: Growth Agent
            growth_agent_class = self.registry.get("growth")
            growth_agent = growth_agent_class(config=config)

            growth_start = datetime.utcnow()
            growth_result = await growth_agent.run(
                {
                    "growth_metric": "quarterly_review",
                    "current_value": 100,
                    "target_value": 150,
                    "timeframe": "next quarter",
                },
                context,
            )
            growth_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="growth",
                started_at=growth_start,
                completed_at=growth_end,
                success=growth_result.success,
                output=growth_result.result_data,
                duration_seconds=(growth_end - growth_start).total_seconds(),
            ))

            # Step 5: Business Agent - Comprehensive report
            business_agent_class = self.registry.get("business")
            business_agent = business_agent_class(config=config)

            business_start = datetime.utcnow()
            business_result = await business_agent.run(
                {
                    "report_type": "quarterly_review",
                    "time_period": time_period,
                    "metrics": ["revenue", "growth", "marketing", "sales", "operations"],
                },
                context,
            )
            business_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="business",
                started_at=business_start,
                completed_at=business_end,
                success=business_result.success,
                output=business_result.result_data,
                duration_seconds=(business_end - business_start).total_seconds(),
            ))

            # Compile results
            completed_at = datetime.utcnow()
            final_output = {
                "financial_performance": finance_result.result_data,
                "sales_performance": sales_result.result_data,
                "marketing_performance": marketing_result.result_data,
                "growth_metrics": growth_result.result_data,
                "comprehensive_report": business_result.result_data,
            }

            recommendations = [
                "Review all department metrics with leadership team",
                "Set targets for next quarter based on trends",
                "Identify areas for improvement and investment",
                "Celebrate wins and learn from challenges",
                "Update annual strategy based on quarterly performance",
            ]

            metrics = {
                "quarter": quarter,
                "year": year,
                "departments_reviewed": 5,
                "agents_executed": len(agents_executed),
                "total_duration_seconds": (completed_at - started_at).total_seconds(),
            }

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.QUARTERLY_REVIEW,
                status=WorkflowStatus.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output=final_output,
                recommendations=recommendations,
                metrics=metrics,
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

        except Exception as e:
            self.logger.error(f"Quarterly review workflow failed: {e}", exc_info=True)
            completed_at = datetime.utcnow()

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.QUARTERLY_REVIEW,
                status=WorkflowStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output={},
                recommendations=["Review error and retry workflow"],
                metrics={},
                error_message=str(e),
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

    async def run_growth_planning(
        self,
        growth_metric: str,
        current_value: float,
        target_value: float,
        timeframe: str,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WorkflowResult:
        """
        Execute growth planning workflow.

        Workflow steps:
        1. GrowthAgent - Develop growth strategy
        2. MarketingAgent - Plan marketing tactics
        3. SalesAgent - Align sales approach
        4. BusinessAgent - Create implementation roadmap

        Args:
            growth_metric: Metric to grow (user_acquisition, revenue, engagement, etc.)
            current_value: Current metric value
            target_value: Target metric value
            timeframe: Timeframe to achieve target
            workspace_id: Workspace context
            user_id: User executing workflow

        Returns:
            WorkflowResult with growth plan
        """
        workflow_id = str(uuid.uuid4())
        started_at = datetime.utcnow()
        agents_executed = []

        self.logger.info(f"Starting growth planning workflow {workflow_id}")

        try:
            context = AgentContext(
                workspace_id=workspace_id,
                user_id=user_id,
                task_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
            )

            config = AgentConfig(
                max_tokens=2000,
                temperature=0.7,
                model_provider="claude",
            )

            # Step 1: Growth Agent - Develop strategy
            growth_agent_class = self.registry.get("growth")
            growth_agent = growth_agent_class(config=config)

            growth_start = datetime.utcnow()
            growth_result = await growth_agent.run(
                {
                    "growth_metric": growth_metric,
                    "current_value": current_value,
                    "target_value": target_value,
                    "timeframe": timeframe,
                },
                context,
            )
            growth_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="growth",
                started_at=growth_start,
                completed_at=growth_end,
                success=growth_result.success,
                output=growth_result.result_data,
                error=growth_result.error_message,
                duration_seconds=(growth_end - growth_start).total_seconds(),
            ))

            if not growth_result.success:
                raise Exception(f"Growth agent failed: {growth_result.error_message}")

            # Step 2: Marketing Agent - Marketing tactics
            marketing_agent_class = self.registry.get("marketing")
            marketing_agent = marketing_agent_class(config=config)

            marketing_start = datetime.utcnow()
            marketing_result = await marketing_agent.run(
                {
                    "campaign_type": f"growth_{growth_metric}",
                    "target_audience": "growth targets",
                    "message": f"Achieve {target_value} {growth_metric}",
                    "channels": ["multi-channel"],
                },
                context,
            )
            marketing_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="marketing",
                started_at=marketing_start,
                completed_at=marketing_end,
                success=marketing_result.success,
                output=marketing_result.result_data,
                duration_seconds=(marketing_end - marketing_start).total_seconds(),
            ))

            # Step 3: Sales Agent - Sales alignment
            sales_agent_class = self.registry.get("sales")
            sales_agent = sales_agent_class(config=config)

            sales_start = datetime.utcnow()
            sales_result = await sales_agent.run(
                {
                    "operation": "align_with_growth",
                    "contact_info": {},
                    "deal_value": target_value,
                    "stage": "planning",
                },
                context,
            )
            sales_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="sales",
                started_at=sales_start,
                completed_at=sales_end,
                success=sales_result.success,
                output=sales_result.result_data,
                duration_seconds=(sales_end - sales_start).total_seconds(),
            ))

            # Step 4: Business Agent - Implementation roadmap
            business_agent_class = self.registry.get("business")
            business_agent = business_agent_class(config=config)

            business_start = datetime.utcnow()
            business_result = await business_agent.run(
                {
                    "report_type": "growth_roadmap",
                    "time_period": timeframe,
                    "metrics": [growth_metric, "timeline", "resources", "milestones"],
                },
                context,
            )
            business_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="business",
                started_at=business_start,
                completed_at=business_end,
                success=business_result.success,
                output=business_result.result_data,
                duration_seconds=(business_end - business_start).total_seconds(),
            ))

            # Compile results
            completed_at = datetime.utcnow()
            growth_gap = target_value - current_value
            growth_rate = (growth_gap / current_value) * 100 if current_value > 0 else 0

            final_output = {
                "growth_strategy": growth_result.result_data,
                "marketing_tactics": marketing_result.result_data,
                "sales_alignment": sales_result.result_data,
                "implementation_roadmap": business_result.result_data,
                "growth_gap": growth_gap,
                "required_growth_rate": f"{growth_rate:.1f}%",
            }

            recommendations = [
                f"Focus on {growth_metric} as primary growth driver",
                f"Achieve {growth_rate:.1f}% growth over {timeframe}",
                "Align marketing and sales efforts with growth targets",
                "Track progress weekly against milestones",
                "Adjust tactics based on performance data",
            ]

            metrics = {
                "growth_metric": growth_metric,
                "current_value": current_value,
                "target_value": target_value,
                "growth_gap": growth_gap,
                "growth_rate_percent": growth_rate,
                "timeframe": timeframe,
                "agents_executed": len(agents_executed),
            }

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.GROWTH_STRATEGY,
                status=WorkflowStatus.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output=final_output,
                recommendations=recommendations,
                metrics=metrics,
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

        except Exception as e:
            self.logger.error(f"Growth planning workflow failed: {e}", exc_info=True)
            completed_at = datetime.utcnow()

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.GROWTH_STRATEGY,
                status=WorkflowStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output={},
                recommendations=["Review error and retry workflow"],
                metrics={},
                error_message=str(e),
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

    async def run_finance_analysis(
        self,
        analysis_type: str,
        time_period: str,
        include_forecast: bool = True,
        workspace_id: uuid.UUID = None,
        user_id: uuid.UUID = None,
    ) -> WorkflowResult:
        """
        Execute finance and revenue analysis workflow.

        Workflow steps:
        1. FinanceAgent - Financial analysis and metrics
        2. BusinessAgent - Business performance analysis
        3. SalesAgent - Revenue pipeline analysis (if applicable)
        4. GrowthAgent - Growth impact on finances

        Args:
            analysis_type: Type of analysis (revenue, expenses, profitability, forecast)
            time_period: Time period to analyze
            include_forecast: Whether to include forecast
            workspace_id: Workspace context
            user_id: User executing workflow

        Returns:
            WorkflowResult with financial analysis
        """
        workflow_id = str(uuid.uuid4())
        started_at = datetime.utcnow()
        agents_executed = []

        self.logger.info(f"Starting finance analysis workflow {workflow_id}")

        try:
            context = AgentContext(
                workspace_id=workspace_id,
                user_id=user_id,
                task_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
            )

            config = AgentConfig(
                max_tokens=2000,
                temperature=0.7,
                model_provider="claude",
            )

            # Step 1: Finance Agent - Core analysis
            finance_agent_class = self.registry.get("finance")
            finance_agent = finance_agent_class(config=config)

            finance_start = datetime.utcnow()
            finance_result = await finance_agent.run(
                {
                    "operation": analysis_type,
                    "time_period": time_period,
                    "amount": 0,
                    "category": "analysis",
                },
                context,
            )
            finance_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="finance",
                started_at=finance_start,
                completed_at=finance_end,
                success=finance_result.success,
                output=finance_result.result_data,
                duration_seconds=(finance_end - finance_start).total_seconds(),
            ))

            if not finance_result.success:
                raise Exception(f"Finance agent failed: {finance_result.error_message}")

            # Step 2: Business Agent - Business context
            business_agent_class = self.registry.get("business")
            business_agent = business_agent_class(config=config)

            business_start = datetime.utcnow()
            business_result = await business_agent.run(
                {
                    "report_type": "financial_performance",
                    "time_period": time_period,
                    "metrics": ["revenue", "expenses", "profit", "margins"],
                },
                context,
            )
            business_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="business",
                started_at=business_start,
                completed_at=business_end,
                success=business_result.success,
                output=business_result.result_data,
                duration_seconds=(business_end - business_start).total_seconds(),
            ))

            # Step 3: Sales Agent - Revenue pipeline
            sales_agent_class = self.registry.get("sales")
            sales_agent = sales_agent_class(config=config)

            sales_start = datetime.utcnow()
            sales_result = await sales_agent.run(
                {
                    "operation": "revenue_analysis",
                    "contact_info": {},
                    "deal_value": 0,
                    "stage": time_period,
                },
                context,
            )
            sales_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="sales",
                started_at=sales_start,
                completed_at=sales_end,
                success=sales_result.success,
                output=sales_result.result_data,
                duration_seconds=(sales_end - sales_start).total_seconds(),
            ))

            # Step 4: Growth Agent - Growth impact (if forecasting)
            if include_forecast:
                growth_agent_class = self.registry.get("growth")
                growth_agent = growth_agent_class(config=config)

                growth_start = datetime.utcnow()
                growth_result = await growth_agent.run(
                    {
                        "growth_metric": "revenue",
                        "current_value": 100,
                        "target_value": 150,
                        "timeframe": "next period",
                    },
                    context,
                )
                growth_end = datetime.utcnow()

                agents_executed.append(AgentExecution(
                    agent_name="growth",
                    started_at=growth_start,
                    completed_at=growth_end,
                    success=growth_result.success,
                    output=growth_result.result_data,
                    duration_seconds=(growth_end - growth_start).total_seconds(),
                ))

                final_output = {
                    "financial_analysis": finance_result.result_data,
                    "business_performance": business_result.result_data,
                    "revenue_pipeline": sales_result.result_data,
                    "growth_forecast": growth_result.result_data,
                }
            else:
                final_output = {
                    "financial_analysis": finance_result.result_data,
                    "business_performance": business_result.result_data,
                    "revenue_pipeline": sales_result.result_data,
                }

            completed_at = datetime.utcnow()

            recommendations = [
                f"Review {analysis_type} trends for {time_period}",
                "Monitor key financial metrics weekly",
                "Align revenue targets with growth strategy",
                "Optimize expense allocation based on ROI",
                "Update financial forecasts monthly",
            ]

            metrics = {
                "analysis_type": analysis_type,
                "time_period": time_period,
                "forecast_included": include_forecast,
                "agents_executed": len(agents_executed),
            }

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.FINANCE_REPORT,
                status=WorkflowStatus.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output=final_output,
                recommendations=recommendations,
                metrics=metrics,
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

        except Exception as e:
            self.logger.error(f"Finance analysis workflow failed: {e}", exc_info=True)
            completed_at = datetime.utcnow()

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.FINANCE_REPORT,
                status=WorkflowStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output={},
                recommendations=["Review error and retry workflow"],
                metrics={},
                error_message=str(e),
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

    async def run_business_strategy(
        self,
        strategy_type: str,
        focus_areas: List[str],
        timeframe: str,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WorkflowResult:
        """
        Execute business strategy workflow.

        Workflow steps:
        1. BusinessAgent - Strategic analysis and planning
        2. FinanceAgent - Financial implications
        3. GrowthAgent - Growth opportunities
        4. MarketingAgent - Market positioning
        5. SalesAgent - Sales strategy alignment

        Args:
            strategy_type: Type of strategy (expansion, optimization, pivot, etc.)
            focus_areas: Areas to focus on (product, market, operations, etc.)
            timeframe: Strategy timeframe
            workspace_id: Workspace context
            user_id: User executing workflow

        Returns:
            WorkflowResult with business strategy
        """
        workflow_id = str(uuid.uuid4())
        started_at = datetime.utcnow()
        agents_executed = []

        self.logger.info(f"Starting business strategy workflow {workflow_id}")

        try:
            context = AgentContext(
                workspace_id=workspace_id,
                user_id=user_id,
                task_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
            )

            config = AgentConfig(
                max_tokens=2000,
                temperature=0.7,
                model_provider="claude",
            )

            # Step 1: Business Agent - Strategic planning
            business_agent_class = self.registry.get("business")
            business_agent = business_agent_class(config=config)

            business_start = datetime.utcnow()
            business_result = await business_agent.run(
                {
                    "report_type": "strategic_plan",
                    "time_period": timeframe,
                    "metrics": focus_areas,
                },
                context,
            )
            business_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="business",
                started_at=business_start,
                completed_at=business_end,
                success=business_result.success,
                output=business_result.result_data,
                duration_seconds=(business_end - business_start).total_seconds(),
            ))

            if not business_result.success:
                raise Exception(f"Business agent failed: {business_result.error_message}")

            # Step 2: Finance Agent - Financial analysis
            finance_agent_class = self.registry.get("finance")
            finance_agent = finance_agent_class(config=config)

            finance_start = datetime.utcnow()
            finance_result = await finance_agent.run(
                {
                    "operation": "strategic_finance",
                    "time_period": timeframe,
                    "amount": 0,
                    "category": strategy_type,
                },
                context,
            )
            finance_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="finance",
                started_at=finance_start,
                completed_at=finance_end,
                success=finance_result.success,
                output=finance_result.result_data,
                duration_seconds=(finance_end - finance_start).total_seconds(),
            ))

            # Step 3: Growth Agent - Growth opportunities
            growth_agent_class = self.registry.get("growth")
            growth_agent = growth_agent_class(config=config)

            growth_start = datetime.utcnow()
            growth_result = await growth_agent.run(
                {
                    "growth_metric": "strategic_growth",
                    "current_value": 100,
                    "target_value": 200,
                    "timeframe": timeframe,
                },
                context,
            )
            growth_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="growth",
                started_at=growth_start,
                completed_at=growth_end,
                success=growth_result.success,
                output=growth_result.result_data,
                duration_seconds=(growth_end - growth_start).total_seconds(),
            ))

            # Step 4: Marketing Agent - Market positioning
            marketing_agent_class = self.registry.get("marketing")
            marketing_agent = marketing_agent_class(config=config)

            marketing_start = datetime.utcnow()
            marketing_result = await marketing_agent.run(
                {
                    "campaign_type": "strategic_positioning",
                    "target_audience": "strategic targets",
                    "message": strategy_type,
                    "channels": focus_areas,
                },
                context,
            )
            marketing_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="marketing",
                started_at=marketing_start,
                completed_at=marketing_end,
                success=marketing_result.success,
                output=marketing_result.result_data,
                duration_seconds=(marketing_end - marketing_start).total_seconds(),
            ))

            # Step 5: Sales Agent - Sales strategy
            sales_agent_class = self.registry.get("sales")
            sales_agent = sales_agent_class(config=config)

            sales_start = datetime.utcnow()
            sales_result = await sales_agent.run(
                {
                    "operation": "strategic_sales",
                    "contact_info": {},
                    "deal_value": 0,
                    "stage": strategy_type,
                },
                context,
            )
            sales_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="sales",
                started_at=sales_start,
                completed_at=sales_end,
                success=sales_result.success,
                output=sales_result.result_data,
                duration_seconds=(sales_end - sales_start).total_seconds(),
            ))

            # Compile results
            completed_at = datetime.utcnow()

            final_output = {
                "strategic_plan": business_result.result_data,
                "financial_implications": finance_result.result_data,
                "growth_opportunities": growth_result.result_data,
                "market_positioning": marketing_result.result_data,
                "sales_strategy": sales_result.result_data,
            }

            recommendations = [
                f"Execute {strategy_type} strategy over {timeframe}",
                f"Focus on: {', '.join(focus_areas)}",
                "Align all departments with strategic goals",
                "Review progress quarterly",
                "Adjust strategy based on market conditions",
            ]

            metrics = {
                "strategy_type": strategy_type,
                "focus_areas_count": len(focus_areas),
                "timeframe": timeframe,
                "agents_executed": len(agents_executed),
            }

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.BUSINESS_ANALYSIS,
                status=WorkflowStatus.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output=final_output,
                recommendations=recommendations,
                metrics=metrics,
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

        except Exception as e:
            self.logger.error(f"Business strategy workflow failed: {e}", exc_info=True)
            completed_at = datetime.utcnow()

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.BUSINESS_ANALYSIS,
                status=WorkflowStatus.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output={},
                recommendations=["Review error and retry workflow"],
                metrics={},
                error_message=str(e),
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

    async def run_content_generation(
        self,
        content_type: str,
        topic: str,
        target_audience: str,
        length: str,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WorkflowResult:
        """
        Execute content generation workflow.

        Workflow steps:
        1. ResearchAgent - Research topic and gather information
        2. ContentAgent - Generate content
        3. MarketingAgent - Optimize for marketing channels
        4. BusinessAgent - Review for business alignment

        Args:
            content_type: Type of content (blog, article, social, email, etc.)
            topic: Content topic
            target_audience: Target audience description
            length: Content length (short, medium, long)
            workspace_id: Workspace context
            user_id: User executing workflow

        Returns:
            WorkflowResult with generated content
        """
        workflow_id = str(uuid.uuid4())
        started_at = datetime.utcnow()
        agents_executed = []

        self.logger.info(f"Starting content generation workflow {workflow_id}")

        try:
            context = AgentContext(
                workspace_id=workspace_id,
                user_id=user_id,
                task_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
            )

            config = AgentConfig(
                max_tokens=2000,
                temperature=0.7,
                model_provider="claude",
            )

            # Step 1: Research Agent - Gather information
            research_agent_class = self.registry.get("research")
            research_agent = research_agent_class(config=config)

            research_start = datetime.utcnow()
            research_result = await research_agent.run(
                {
                    "query": topic,
                    "sources": ["web", "documentation", "best practices"],
                    "depth": "medium",
                },
                context,
            )
            research_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="research",
                started_at=research_start,
                completed_at=research_end,
                success=research_result.success,
                output=research_result.result_data,
                duration_seconds=(research_end - research_start).total_seconds(),
            ))

            if not research_result.success:
                raise Exception(f"Research agent failed: {research_result.error_message}")

            # Step 2: Content Agent - Generate content
            content_agent_class = self.registry.get("content")
            content_agent = content_agent_class(config=config)

            content_start = datetime.utcnow()
            content_result = await content_agent.run(
                {
                    "content_type": content_type,
                    "topic": topic,
                    "target_audience": target_audience,
                    "length": length,
                },
                context,
            )
            content_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="content",
                started_at=content_start,
                completed_at=content_end,
                success=content_result.success,
                output=content_result.result_data,
                duration_seconds=(content_end - content_start).total_seconds(),
            ))

            if not content_result.success:
                raise Exception(f"Content agent failed: {content_result.error_message}")

            # Step 3: Marketing Agent - Optimize for channels
            marketing_agent_class = self.registry.get("marketing")
            marketing_agent = marketing_agent_class(config=config)

            marketing_start = datetime.utcnow()
            marketing_result = await marketing_agent.run(
                {
                    "campaign_type": "content_distribution",
                    "target_audience": target_audience,
                    "message": f"{content_type}: {topic}",
                    "channels": ["blog", "social", "email"],
                },
                context,
            )
            marketing_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="marketing",
                started_at=marketing_start,
                completed_at=marketing_end,
                success=marketing_result.success,
                output=marketing_result.result_data,
                duration_seconds=(marketing_end - marketing_start).total_seconds(),
            ))

            # Step 4: Business Agent - Review alignment
            business_agent_class = self.registry.get("business")
            business_agent = business_agent_class(config=config)

            business_start = datetime.utcnow()
            business_result = await business_agent.run(
                {
                    "report_type": "content_review",
                    "time_period": "current",
                    "metrics": ["quality", "alignment", "impact"],
                },
                context,
            )
            business_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="business",
                started_at=business_start,
                completed_at=business_end,
                success=business_result.success,
                output=business_result.result_data,
                duration_seconds=(business_end - business_start).total_seconds(),
            ))

            # Compile results
            completed_at = datetime.utcnow()

            final_output = {
                "research_findings": research_result.result_data,
                "generated_content": content_result.result_data,
                "distribution_plan": marketing_result.result_data,
                "quality_review": business_result.result_data,
            }

            recommendations = [
                f"Publish {content_type} on primary channels",
                "Promote content across identified marketing channels",
                "Monitor engagement metrics",
                "Repurpose content for different formats",
                "Update content based on audience feedback",
            ]

            word_count = content_result.result_data.get("word_count", 0)
            metrics = {
                "content_type": content_type,
                "topic": topic,
                "word_count": word_count,
                "target_audience": target_audience,
                "agents_executed": len(agents_executed),
            }

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.REVENUE_OPTIMIZATION,  # Reuse enum
                status=WorkflowStatus.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output=final_output,
                recommendations=recommendations,
                metrics=metrics,
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

        except Exception as e:
            self.logger.error(f"Content generation workflow failed: {e}", exc_info=True)
            completed_at = datetime.utcnow()

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.REVENUE_OPTIMIZATION,
                status=WorkflowStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output={},
                recommendations=["Review error and retry workflow"],
                metrics={},
                error_message=str(e),
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

    async def run_research_analysis(
        self,
        research_query: str,
        analysis_type: str,
        data_sources: List[str],
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WorkflowResult:
        """
        Execute research and data analysis workflow.

        Workflow steps:
        1. ResearchAgent - Conduct research
        2. AnalyticsAgent - Analyze data and patterns
        3. BusinessAgent - Business insights and recommendations

        Args:
            research_query: Research question or topic
            analysis_type: Type of analysis (market, competitive, trend, data)
            data_sources: Data sources to use
            workspace_id: Workspace context
            user_id: User executing workflow

        Returns:
            WorkflowResult with research and analysis results
        """
        workflow_id = str(uuid.uuid4())
        started_at = datetime.utcnow()
        agents_executed = []

        self.logger.info(f"Starting research analysis workflow {workflow_id}")

        try:
            context = AgentContext(
                workspace_id=workspace_id,
                user_id=user_id,
                task_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
            )

            config = AgentConfig(
                max_tokens=2000,
                temperature=0.7,
                model_provider="claude",
            )

            # Step 1: Research Agent - Conduct research
            research_agent_class = self.registry.get("research")
            research_agent = research_agent_class(config=config)

            research_start = datetime.utcnow()
            research_result = await research_agent.run(
                {
                    "query": research_query,
                    "sources": data_sources,
                    "depth": "deep" if analysis_type in ["market", "competitive"] else "medium",
                },
                context,
            )
            research_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="research",
                started_at=research_start,
                completed_at=research_end,
                success=research_result.success,
                output=research_result.result_data,
                duration_seconds=(research_end - research_start).total_seconds(),
            ))

            if not research_result.success:
                raise Exception(f"Research agent failed: {research_result.error_message}")

            # Step 2: Analytics Agent - Data analysis
            analytics_agent_class = self.registry.get("analytics")
            analytics_agent = analytics_agent_class(config=config)

            analytics_start = datetime.utcnow()
            analytics_result = await analytics_agent.run(
                {
                    "data_sources": data_sources,
                    "metrics": ["trends", "patterns", "correlations"],
                    "time_range": "recent",
                    "analysis_type": analysis_type,
                },
                context,
            )
            analytics_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="analytics",
                started_at=analytics_start,
                completed_at=analytics_end,
                success=analytics_result.success,
                output=analytics_result.result_data,
                duration_seconds=(analytics_end - analytics_start).total_seconds(),
            ))

            if not analytics_result.success:
                raise Exception(f"Analytics agent failed: {analytics_result.error_message}")

            # Step 3: Business Agent - Strategic insights
            business_agent_class = self.registry.get("business")
            business_agent = business_agent_class(config=config)

            business_start = datetime.utcnow()
            business_result = await business_agent.run(
                {
                    "report_type": "research_insights",
                    "time_period": "current",
                    "metrics": ["findings", "insights", "recommendations"],
                },
                context,
            )
            business_end = datetime.utcnow()

            agents_executed.append(AgentExecution(
                agent_name="business",
                started_at=business_start,
                completed_at=business_end,
                success=business_result.success,
                output=business_result.result_data,
                duration_seconds=(business_end - business_start).total_seconds(),
            ))

            # Compile results
            completed_at = datetime.utcnow()

            final_output = {
                "research_findings": research_result.result_data,
                "data_analysis": analytics_result.result_data,
                "business_insights": business_result.result_data,
            }

            recommendations = [
                f"Act on key findings from {analysis_type} analysis",
                "Share insights with relevant stakeholders",
                "Monitor identified trends",
                "Update strategy based on research",
                "Conduct follow-up research in 3 months",
            ]

            metrics = {
                "research_query": research_query,
                "analysis_type": analysis_type,
                "data_sources_count": len(data_sources),
                "findings_count": len(research_result.result_data.get("findings", [])),
                "agents_executed": len(agents_executed),
            }

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.REVENUE_OPTIMIZATION,  # Reuse enum
                status=WorkflowStatus.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output=final_output,
                recommendations=recommendations,
                metrics=metrics,
                duration_seconds=(completed_at - started_at).total_seconds(),
            )

        except Exception as e:
            self.logger.error(f"Research analysis workflow failed: {e}", exc_info=True)
            completed_at = datetime.utcnow()

            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_type=WorkflowType.REVENUE_OPTIMIZATION,
                status=WorkflowStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                agents_executed=agents_executed,
                final_output={},
                recommendations=["Review error and retry workflow"],
                metrics={},
                error_message=str(e),
                duration_seconds=(completed_at - started_at).total_seconds(),
            )


# Global instance
_business_workflow: Optional[BusinessOperationsWorkflow] = None


def get_business_workflow() -> BusinessOperationsWorkflow:
    """Get global business operations workflow instance"""
    global _business_workflow
    if _business_workflow is None:
        _business_workflow = BusinessOperationsWorkflow()
    return _business_workflow
