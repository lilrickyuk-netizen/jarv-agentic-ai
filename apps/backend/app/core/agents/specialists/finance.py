"""
JARV Backend - FinanceAgent

Produces financial advisory output honestly.

This agent has NO access to real ledgers, budgets, or accounting systems in
standalone execution, so it NEVER invents revenue, cost, ROI, forecast
accuracy, or expense counts. If the caller supplies a real numeric amount, the
agent may perform simple, clearly-labelled arithmetic on THAT value only.
Otherwise, when an LLM provider is configured it produces an advisory draft
(no fabricated figures); when no provider is configured it returns an honest
limitation. No financial transaction is performed.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)

# Threshold above which a caller-supplied amount is flagged for human review.
_LARGE_AMOUNT_THRESHOLD = 100000.0


class FinanceAgentInput(BaseModel):
    """FinanceAgent input"""
    operation: str = Field(..., description="budget, forecast, expense_tracking, reporting")
    time_period: str = Field(...)
    amount: float = Field(default=0.0)
    category: str = Field(default="")


class FinanceAgentOutput(BaseModel):
    """FinanceAgent output (honest; no fabricated financial figures)."""
    operation: str = ""
    time_period: str = ""
    provided_amount: Optional[float] = None
    category: str = ""
    derived: Dict[str, float] = Field(default_factory=dict)
    advisory: str = ""
    advisory_produced: bool = False
    alerts: List[str] = Field(default_factory=list)
    external_action_taken: bool = False
    provider_used: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


class FinanceAgent(AgentBase):
    """
    FinanceAgent - honest financial advisory; arithmetic on provided values only.
    """

    @property
    def name(self) -> str:
        return "finance"

    @property
    def role(self) -> str:
        return "Manages financial tracking, budgets, and reporting"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return FinanceAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return FinanceAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_8_FINANCIAL

    @property
    def default_tools(self) -> list[str]:
        return ['analyze_metrics', 'memory_retrieve', 'file_write']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            operation = input_data.get("operation", "reporting")
            time_period = input_data.get("time_period", "")
            category = input_data.get("category", "")
            instruction = helpers.task_text(input_data, "operation", "category")

            self.logger.info(f"Finance advisory: {operation} for {time_period}")

            # Only treat the caller-supplied amount as real data when it is a
            # usable positive number. Never fabricate any other figure.
            provided_amount: Optional[float] = None
            try:
                raw_amount = input_data.get("amount", 0.0)
                amt = float(raw_amount)
                if amt > 0:
                    provided_amount = amt
            except (TypeError, ValueError):
                provided_amount = None

            limitations: List[str] = [
                "This agent has NO access to real ledgers, budgets, or accounting "
                "systems; no transaction was performed and no revenue/cost/ROI/"
                "forecast figures were measured or invented.",
            ]
            alerts: List[str] = []
            derived: Dict[str, float] = {}

            # Honest arithmetic on the caller-supplied amount ONLY.
            if provided_amount is not None:
                derived["provided_amount"] = provided_amount
                derived["monthly_if_annual"] = round(provided_amount / 12.0, 2)
                derived["with_10pct_buffer"] = round(provided_amount * 1.10, 2)
                limitations.append(
                    "All values under 'derived' are simple arithmetic on the "
                    "caller-supplied amount only, not measured financial results."
                )
                if provided_amount > _LARGE_AMOUNT_THRESHOLD:
                    alerts.append(
                        f"Caller-supplied amount {provided_amount} exceeds the "
                        f"{_LARGE_AMOUNT_THRESHOLD} review threshold; flag for "
                        "human approval."
                    )
            else:
                limitations.append(
                    "No usable numeric amount was provided; no arithmetic was "
                    "performed."
                )

            advisory = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            if helpers.provider_configured():
                amount_line = (
                    f"Caller-supplied amount: {provided_amount}"
                    if provided_amount is not None
                    else "No numeric amount was provided."
                )
                prompt = (
                    f"Provide financial advisory for the operation '{operation}' "
                    f"covering the period '{time_period or '(unspecified)'}'.\n"
                    f"Category: {category or '(none)'}\n"
                    f"{amount_line}\n"
                    f"Context/instruction: {instruction or '(none provided)'}\n\n"
                    "Give qualitative guidance, risks, and next steps. You have NO "
                    "access to real financials, so do NOT invent revenue, cost, "
                    "ROI, forecast accuracy, or expense counts. You may reason only "
                    "about the caller-supplied amount above, clearly labelled as "
                    "an input assumption."
                )
                result = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system="You are a finance advisor. Provide advisory guidance "
                           "only. Never fabricate financial figures or claim a "
                           "transaction occurred.",
                    temperature=self.config.temperature,
                )
                if result is not None and result.get("text"):
                    advisory = result["text"]
                    provider_used = result["provider_used"]
                    tokens = result["tokens"]
                    limitations.append(
                        "The advisory is model-generated and UNVERIFIED; confirm "
                        "all assumptions against real financials before acting."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; no "
                        "advisory could be generated."
                    )
            else:
                limitations.append(helpers.no_provider_limitation())

            advisory_produced = bool(advisory)
            output_text = (
                f"Finance advisory ({operation}, {time_period}); "
                f"derived_values={len(derived)}; alerts={len(alerts)}; "
                f"provider={provider_used or 'none'}; no transaction performed."
            )

            return self.create_result(
                success=True,
                result_data={
                    "operation": operation,
                    "time_period": time_period,
                    "provided_amount": provided_amount,
                    "category": category,
                    "derived": derived,
                    "advisory": advisory,
                    "advisory_produced": advisory_produced,
                    "alerts": alerts,
                    "external_action_taken": False,
                    "provider_used": provider_used,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(["model_router"] if provider_used else []),
                tokens_used=tokens or {},
                requires_approval=(operation == "budget" or len(alerts) > 0),
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"finance task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
