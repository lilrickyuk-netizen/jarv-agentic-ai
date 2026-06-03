"""
JARV Backend - Cost Estimation Tool

Tool for estimating infrastructure costs.
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime
import logging

from sqlalchemy import select, and_

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.core.database import AsyncSessionLocal
from app.models.operations import InfrastructureResource

logger = logging.getLogger(__name__)


# ===== COST ESTIMATE TOOL =====

class CostEstimateInput(BaseModel):
    """Input schema for cost estimate tool"""
    resource_type: Optional[str] = Field(None, description="Type of resource to estimate (None for all)")
    provider: Optional[str] = Field(None, description="Cloud provider (aws, azure, gcp)")
    region: Optional[str] = Field(None, description="Region for cost estimation")
    config: Optional[dict] = Field(None, description="Resource configuration")
    time_period: str = Field(default="monthly", description="Time period (hourly, daily, monthly, annual)")
    usage_hours: int = Field(default=730, ge=1, description="Expected usage hours (default: 1 month)")
    include_data_transfer: bool = Field(default=True, description="Include data transfer costs")
    include_storage: bool = Field(default=True, description="Include storage costs")
    include_projected: bool = Field(default=False, description="Include projected costs")
    growth_rate_percent: float = Field(default=0.0, ge=0.0, le=100.0, description="Growth rate percentage")


class CostEstimateOutput(BaseModel):
    """Output schema for cost estimate tool"""
    resource_type: str = Field(..., description="Type of resource")
    provider: str = Field(..., description="Cloud provider")
    hourly_cost: float = Field(..., description="Estimated hourly cost")
    monthly_cost: float = Field(..., description="Estimated monthly cost")
    annual_cost: float = Field(..., description="Estimated annual cost")
    breakdown: dict = Field(..., description="Cost breakdown by component")
    currency: str = Field(..., description="Currency")


class CostEstimateTool(ToolBase):
    """Tool for estimating infrastructure costs"""

    @property
    def name(self) -> str:
        return "cost_estimate"

    @property
    def description(self) -> str:
        return "Estimate costs for infrastructure resources across cloud providers."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CostEstimateInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CostEstimateOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "infrastructure"

    def _estimate_compute_cost(
        self,
        resource_type: str,
        provider: str,
        config: dict,
    ) -> float:
        """Estimate compute costs based on resource type and config"""
        # Simplified cost estimation - in real implementation would use provider pricing APIs
        base_rates = {
            "aws": {
                "vm": 0.10,
                "container": 0.05,
                "database": 0.15,
                "storage": 0.023,
            },
            "azure": {
                "vm": 0.12,
                "container": 0.06,
                "database": 0.18,
                "storage": 0.025,
            },
            "gcp": {
                "vm": 0.09,
                "container": 0.04,
                "database": 0.14,
                "storage": 0.020,
            },
        }

        base_rate = base_rates.get(provider, {}).get(resource_type, 0.10)

        # Apply multipliers based on config
        multiplier = 1.0

        # Instance size multiplier
        if "instance_size" in config:
            size_multipliers = {
                "small": 1.0,
                "medium": 2.0,
                "large": 4.0,
                "xlarge": 8.0,
            }
            multiplier *= size_multipliers.get(config["instance_size"], 1.0)

        # CPU/Memory multipliers
        if "cpu_cores" in config:
            multiplier *= config["cpu_cores"]
        if "memory_gb" in config:
            multiplier *= (config["memory_gb"] / 4.0)  # Base 4GB

        return base_rate * multiplier

    def _estimate_storage_cost(
        self,
        config: dict,
    ) -> float:
        """Estimate storage costs"""
        storage_gb = config.get("storage_gb", 0)
        storage_type = config.get("storage_type", "standard")

        # Cost per GB per month
        storage_rates = {
            "standard": 0.023,
            "ssd": 0.10,
            "premium": 0.20,
        }

        rate = storage_rates.get(storage_type, 0.023)
        monthly_storage = storage_gb * rate

        # Convert to hourly
        return monthly_storage / 730

    def _estimate_data_transfer_cost(
        self,
        config: dict,
    ) -> float:
        """Estimate data transfer costs"""
        data_transfer_gb = config.get("data_transfer_gb_per_month", 0)

        # Cost per GB transferred
        transfer_rate = 0.09  # Simplified rate

        monthly_transfer = data_transfer_gb * transfer_rate

        # Convert to hourly
        return monthly_transfer / 730

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute cost estimation"""
        try:
            resource_type = input_data.get("resource_type")
            provider = input_data.get("provider", "aws")
            region = input_data.get("region", "us-east-1")
            config = input_data.get("config", {})
            time_period = input_data.get("time_period", "monthly")
            usage_hours = input_data.get("usage_hours", 730)
            include_data_transfer = input_data.get("include_data_transfer", True)
            include_storage = input_data.get("include_storage", True)
            include_projected = input_data.get("include_projected", False)
            growth_rate_percent = input_data.get("growth_rate_percent", 0.0)

            # If no resource_type specified, get all resources
            if resource_type is None:
                # Query all resources to get total cost
                async with AsyncSessionLocal() as db:
                    query = select(InfrastructureResource).where(
                        InfrastructureResource.is_active == True
                    )
                    if context.workspace_id:
                        query = query.where(InfrastructureResource.workspace_id == context.workspace_id)
                    else:
                        query = query.where(InfrastructureResource.workspace_id.is_(None))

                    result = await db.execute(query)
                    resources = result.scalars().all()

                    # Calculate total costs
                    total_hourly = sum(float(r.hourly_cost or 0) for r in resources)
                    total_monthly = sum(float(r.monthly_cost or 0) for r in resources)
                    total_annual = total_monthly * 12

                    # Create breakdown by resource type
                    cost_breakdown = {}
                    for r in resources:
                        res_type = r.resource_type
                        if res_type not in cost_breakdown:
                            cost_breakdown[res_type] = {"count": 0, "monthly_cost": 0.0}
                        cost_breakdown[res_type]["count"] += 1
                        cost_breakdown[res_type]["monthly_cost"] += float(r.monthly_cost or 0)
            else:
                # Calculate component costs for specific resource type
                compute_hourly = self._estimate_compute_cost(resource_type, provider, config)
                storage_hourly = self._estimate_storage_cost(config) if include_storage else 0.0
                transfer_hourly = self._estimate_data_transfer_cost(config) if include_data_transfer else 0.0

                # Total hourly cost
                total_hourly = compute_hourly + storage_hourly + transfer_hourly

                # Calculate monthly and annual costs
                total_monthly = total_hourly * 730  # Average hours per month
                total_annual = total_monthly * 12

                # Cost breakdown
                cost_breakdown = {
                    "compute": {
                        "hourly": round(compute_hourly, 4),
                        "monthly": round(compute_hourly * 730, 2),
                    },
                    "storage": {
                        "hourly": round(storage_hourly, 4),
                        "monthly": round(storage_hourly * 730, 2),
                    } if include_storage else None,
                    "data_transfer": {
                        "hourly": round(transfer_hourly, 4),
                        "monthly": round(transfer_hourly * 730, 2),
                    } if include_data_transfer else None,
                }

                # Remove None values
                cost_breakdown = {k: v for k, v in cost_breakdown.items() if v is not None}

            # Add projected costs if requested
            if include_projected and growth_rate_percent > 0:
                growth_multiplier = 1 + (growth_rate_percent / 100)
                projected_monthly = total_monthly * growth_multiplier
                projected_annual = total_annual * growth_multiplier
            else:
                projected_monthly = None
                projected_annual = None

            logger.info(
                f"Cost estimated for {resource_type or 'all resources'}: "
                f"${total_monthly:.2f}/month"
            )

            result_data = {
                "resource_type": resource_type,
                "provider": provider,
                "region": region,
                "total_cost": round(total_monthly, 2),
                "hourly_cost": round(total_hourly, 4),
                "monthly_cost": round(total_monthly, 2),
                "annual_cost": round(total_annual, 2),
                "breakdown": cost_breakdown,  # For backward compatibility
                "cost_breakdown": cost_breakdown,
                "currency": "USD",
                "time_period": time_period,
                "usage_hours": usage_hours,
            }

            # Add projected costs if available
            if projected_monthly is not None:
                result_data["projected_monthly_cost"] = round(projected_monthly, 2)
                result_data["projected_annual_cost"] = round(projected_annual, 2)

            # Add cost optimization suggestions
            result_data["cost_optimization_suggestions"] = [
                "Consider using reserved instances for long-term resources",
                "Enable auto-scaling to optimize resource usage",
                "Review and terminate unused resources",
            ]

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=(
                    f"Estimated cost: ${total_hourly:.4f}/hour, "
                    f"${total_monthly:.2f}/month, "
                    f"${total_annual:.2f}/year"
                ),
            )

        except Exception as e:
            logger.error(f"Error estimating cost: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to estimate cost: {str(e)}",
            )
