"""
JARV Backend - Business Operations API

RESTful API endpoints for business operation workflows including marketing,
growth, sales, finance, and comprehensive business reviews.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

from app.core.workflows.business_ops import (
    get_business_workflow,
    WorkflowType,
    WorkflowStatus,
    WorkflowResult,
)
from app.core.auth import get_current_user

router = APIRouter(prefix="/business", tags=["business-operations"])


class MarketingCampaignRequest(BaseModel):
    campaign_type: str = Field(..., description="Type of campaign (social, email, content)")
    target_audience: str = Field(..., description="Target audience description")
    message: str = Field(..., description="Campaign message/theme")
    channels: List[str] = Field(..., description="Marketing channels (social_media, email, blog, etc.)")
    budget: float = Field(..., ge=0, description="Campaign budget in dollars")


class SalesPipelineRequest(BaseModel):
    operation: str = Field(..., description="Sales operation (create_lead, update_deal, close_deal)")
    contact_name: str = Field(..., description="Contact name")
    contact_email: str = Field(..., description="Contact email")
    contact_company: str = Field(default="", description="Contact company")
    deal_value: float = Field(..., ge=0, description="Deal value in dollars")
    stage: str = Field(..., description="Sales stage (lead, qualified, proposal, negotiation, closed)")


class QuarterlyReviewRequest(BaseModel):
    quarter: str = Field(..., description="Quarter (Q1, Q2, Q3, Q4)")
    year: int = Field(..., ge=2020, le=2030, description="Year")


class WorkflowResponse(BaseModel):
    workflow_id: str
    workflow_type: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    final_output: Dict[str, Any]
    recommendations: List[str]
    metrics: Dict[str, Any]
    error_message: Optional[str] = None
    duration_seconds: float


@router.post("/workflows/marketing-campaign", response_model=WorkflowResponse)
async def run_marketing_campaign(
    request: MarketingCampaignRequest,
    current_user=Depends(get_current_user),
):
    """
    Execute marketing campaign workflow.

    Orchestrates multiple agents:
    - MarketingAgent: Creates and configures campaign
    - GrowthAgent: Analyzes growth potential and impact
    - FinanceAgent: Tracks budget allocation
    - BusinessAgent: Generates performance report

    Returns comprehensive campaign plan with recommendations.
    """
    workflow = get_business_workflow()

    try:
        result = await workflow.run_marketing_campaign(
            campaign_type=request.campaign_type,
            target_audience=request.target_audience,
            message=request.message,
            channels=request.channels,
            budget=request.budget,
            workspace_id=current_user.workspace_id or uuid.uuid4(),
            user_id=current_user.id,
        )

        return WorkflowResponse(
            workflow_id=result.workflow_id,
            workflow_type=result.workflow_type.value,
            status=result.status.value,
            started_at=result.started_at,
            completed_at=result.completed_at,
            final_output=result.final_output,
            recommendations=result.recommendations,
            metrics=result.metrics,
            error_message=result.error_message,
            duration_seconds=result.duration_seconds,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")


@router.post("/workflows/sales-pipeline", response_model=WorkflowResponse)
async def run_sales_pipeline(
    request: SalesPipelineRequest,
    current_user=Depends(get_current_user),
):
    """
    Execute sales pipeline workflow.

    Orchestrates multiple agents:
    - SalesAgent: Manages sales operation and pipeline
    - BusinessAgent: Analyzes deal metrics and trends
    - FinanceAgent: Forecasts revenue impact

    Returns sales pipeline status with next steps and win probability.
    """
    workflow = get_business_workflow()

    try:
        contact_info = {
            "name": request.contact_name,
            "email": request.contact_email,
            "company": request.contact_company,
        }

        result = await workflow.run_sales_pipeline(
            operation=request.operation,
            contact_info=contact_info,
            deal_value=request.deal_value,
            stage=request.stage,
            workspace_id=current_user.workspace_id or uuid.uuid4(),
            user_id=current_user.id,
        )

        return WorkflowResponse(
            workflow_id=result.workflow_id,
            workflow_type=result.workflow_type.value,
            status=result.status.value,
            started_at=result.started_at,
            completed_at=result.completed_at,
            final_output=result.final_output,
            recommendations=result.recommendations,
            metrics=result.metrics,
            error_message=result.error_message,
            duration_seconds=result.duration_seconds,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")


@router.post("/workflows/quarterly-review", response_model=WorkflowResponse)
async def run_quarterly_review(
    request: QuarterlyReviewRequest,
    current_user=Depends(get_current_user),
):
    """
    Execute comprehensive quarterly business review.

    Orchestrates all business agents:
    - FinanceAgent: Financial performance analysis
    - SalesAgent: Sales performance metrics
    - MarketingAgent: Marketing campaign summary
    - GrowthAgent: Growth metrics and trends
    - BusinessAgent: Comprehensive report synthesis

    Returns complete quarterly review with insights and recommendations.
    """
    workflow = get_business_workflow()

    try:
        result = await workflow.run_quarterly_review(
            quarter=request.quarter,
            year=request.year,
            workspace_id=current_user.workspace_id or uuid.uuid4(),
            user_id=current_user.id,
        )

        return WorkflowResponse(
            workflow_id=result.workflow_id,
            workflow_type=result.workflow_type.value,
            status=result.status.value,
            started_at=result.started_at,
            completed_at=result.completed_at,
            final_output=result.final_output,
            recommendations=result.recommendations,
            metrics=result.metrics,
            error_message=result.error_message,
            duration_seconds=result.duration_seconds,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")


@router.get("/workflows/{workflow_id}")
async def get_workflow_status(
    workflow_id: str,
    current_user=Depends(get_current_user),
):
    """
    Get status of business workflow execution.

    Note: Currently returns basic status. Full workflow tracking
    would require database persistence.
    """
    # In production, this would query workflow status from database
    return {
        "workflow_id": workflow_id,
        "status": "in_progress",
        "message": "Workflow tracking requires database persistence",
    }


@router.post("/workflows/growth-planning", response_model=WorkflowResponse)
async def run_growth_planning(
    growth_metric: str,
    current_value: float,
    target_value: float,
    timeframe: str,
    current_user=Depends(get_current_user),
):
    """
    Execute growth planning workflow.

    Orchestrates multiple agents:
    - GrowthAgent: Develops growth strategy
    - MarketingAgent: Plans marketing tactics
    - SalesAgent: Aligns sales approach
    - BusinessAgent: Creates implementation roadmap

    Returns comprehensive growth plan with tactics and milestones.
    """
    workflow = get_business_workflow()

    try:
        result = await workflow.run_growth_planning(
            growth_metric=growth_metric,
            current_value=current_value,
            target_value=target_value,
            timeframe=timeframe,
            workspace_id=current_user.workspace_id or uuid.uuid4(),
            user_id=current_user.id,
        )

        return WorkflowResponse(
            workflow_id=result.workflow_id,
            workflow_type=result.workflow_type.value,
            status=result.status.value,
            started_at=result.started_at,
            completed_at=result.completed_at,
            final_output=result.final_output,
            recommendations=result.recommendations,
            metrics=result.metrics,
            error_message=result.error_message,
            duration_seconds=result.duration_seconds,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")


@router.post("/workflows/finance-analysis", response_model=WorkflowResponse)
async def run_finance_analysis(
    analysis_type: str,
    time_period: str,
    include_forecast: bool = True,
    current_user=Depends(get_current_user),
):
    """
    Execute finance and revenue analysis workflow.

    Orchestrates multiple agents:
    - FinanceAgent: Financial analysis and metrics
    - BusinessAgent: Business performance analysis
    - SalesAgent: Revenue pipeline analysis
    - GrowthAgent: Growth impact on finances (if forecasting)

    Returns comprehensive financial analysis with insights and forecasts.
    """
    workflow = get_business_workflow()

    try:
        result = await workflow.run_finance_analysis(
            analysis_type=analysis_type,
            time_period=time_period,
            include_forecast=include_forecast,
            workspace_id=current_user.workspace_id or uuid.uuid4(),
            user_id=current_user.id,
        )

        return WorkflowResponse(
            workflow_id=result.workflow_id,
            workflow_type=result.workflow_type.value,
            status=result.status.value,
            started_at=result.started_at,
            completed_at=result.completed_at,
            final_output=result.final_output,
            recommendations=result.recommendations,
            metrics=result.metrics,
            error_message=result.error_message,
            duration_seconds=result.duration_seconds,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")


@router.post("/workflows/business-strategy", response_model=WorkflowResponse)
async def run_business_strategy(
    strategy_type: str,
    focus_areas: List[str],
    timeframe: str,
    current_user=Depends(get_current_user),
):
    """
    Execute business strategy workflow.

    Orchestrates all 5 business agents:
    - BusinessAgent: Strategic analysis and planning
    - FinanceAgent: Financial implications
    - GrowthAgent: Growth opportunities
    - MarketingAgent: Market positioning
    - SalesAgent: Sales strategy alignment

    Returns comprehensive business strategy with multi-department alignment.
    """
    workflow = get_business_workflow()

    try:
        result = await workflow.run_business_strategy(
            strategy_type=strategy_type,
            focus_areas=focus_areas,
            timeframe=timeframe,
            workspace_id=current_user.workspace_id or uuid.uuid4(),
            user_id=current_user.id,
        )

        return WorkflowResponse(
            workflow_id=result.workflow_id,
            workflow_type=result.workflow_type.value,
            status=result.status.value,
            started_at=result.started_at,
            completed_at=result.completed_at,
            final_output=result.final_output,
            recommendations=result.recommendations,
            metrics=result.metrics,
            error_message=result.error_message,
            duration_seconds=result.duration_seconds,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")


@router.post("/workflows/content-generation", response_model=WorkflowResponse)
async def run_content_generation(
    content_type: str,
    topic: str,
    target_audience: str,
    length: str = "medium",
    current_user=Depends(get_current_user),
):
    """
    Execute content generation workflow.

    Orchestrates multiple agents:
    - ResearchAgent: Research topic and gather information
    - ContentAgent: Generate content
    - MarketingAgent: Optimize for marketing channels
    - BusinessAgent: Review for business alignment

    Returns generated content with distribution plan.
    """
    workflow = get_business_workflow()

    try:
        result = await workflow.run_content_generation(
            content_type=content_type,
            topic=topic,
            target_audience=target_audience,
            length=length,
            workspace_id=current_user.workspace_id or uuid.uuid4(),
            user_id=current_user.id,
        )

        return WorkflowResponse(
            workflow_id=result.workflow_id,
            workflow_type=result.workflow_type.value,
            status=result.status.value,
            started_at=result.started_at,
            completed_at=result.completed_at,
            final_output=result.final_output,
            recommendations=result.recommendations,
            metrics=result.metrics,
            error_message=result.error_message,
            duration_seconds=result.duration_seconds,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")


@router.post("/workflows/research-analysis", response_model=WorkflowResponse)
async def run_research_analysis(
    research_query: str,
    analysis_type: str,
    data_sources: List[str],
    current_user=Depends(get_current_user),
):
    """
    Execute research and data analysis workflow.

    Orchestrates multiple agents:
    - ResearchAgent: Conduct research
    - AnalyticsAgent: Analyze data and patterns
    - BusinessAgent: Business insights and recommendations

    Returns research findings with data analysis and strategic insights.
    """
    workflow = get_business_workflow()

    try:
        result = await workflow.run_research_analysis(
            research_query=research_query,
            analysis_type=analysis_type,
            data_sources=data_sources,
            workspace_id=current_user.workspace_id or uuid.uuid4(),
            user_id=current_user.id,
        )

        return WorkflowResponse(
            workflow_id=result.workflow_id,
            workflow_type=result.workflow_type.value,
            status=result.status.value,
            started_at=result.started_at,
            completed_at=result.completed_at,
            final_output=result.final_output,
            recommendations=result.recommendations,
            metrics=result.metrics,
            error_message=result.error_message,
            duration_seconds=result.duration_seconds,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")


@router.get("/metrics/summary")
async def get_business_metrics_summary(
    current_user=Depends(get_current_user),
):
    """
    Get summary of business metrics across all departments.

    Returns aggregated metrics for marketing, sales, finance, and growth.
    """
    # In production, this would aggregate from actual data sources
    return {
        "marketing": {
            "active_campaigns": 5,
            "total_reach": 50000,
            "engagement_rate": 0.15,
        },
        "sales": {
            "active_deals": 12,
            "total_pipeline_value": 250000,
            "conversion_rate": 0.25,
        },
        "finance": {
            "monthly_revenue": 125000,
            "monthly_expenses": 75000,
            "profit_margin": 0.40,
        },
        "growth": {
            "monthly_growth_rate": 0.15,
            "user_acquisition": 500,
            "churn_rate": 0.05,
        },
    }
