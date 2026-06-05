"""
JARV Backend - AnalyticsAgent

Performs REAL, honest analytics on metrics/data that are actually supplied.

This agent does NOT invent metric values, correlations, predictions, or
visualizations. If structured metric data is provided in the input it
summarizes the genuine values. If an LLM provider is configured it may add a
labelled, unverified model insight. If neither metrics nor a provider are
available it returns an honest limited result and says so.
"""
from typing import Dict, Any, List, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists._helpers import (
    provider_configured,
    llm_complete,
    no_provider_limitation,
    task_text,
)

logger = logging.getLogger(__name__)


class AnalyticsAgentInput(BaseModel):
    """AnalyticsAgent input"""
    data_sources: list[str] = Field(..., description="Data sources to analyze")
    metrics: list[str] = Field(default_factory=list)
    time_range: str = Field(default="30d")
    analysis_type: str = Field(default="descriptive")


class AnalyticsAgentOutput(BaseModel):
    """AnalyticsAgent output (honest; every field has a default, no invented numbers)."""
    analysis_completed: bool = False
    analysis_type: str = ""
    data_sources_provided: int = 0
    metrics_provided: int = 0
    metric_summary: List[Dict[str, Any]] = Field(default_factory=list)
    numeric_summary: Dict[str, float] = Field(default_factory=dict)
    model_insight: str = ""
    provider_used: str = ""
    insights: List[Dict[str, Any]] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class AnalyticsAgent(AgentBase):
    """
    AnalyticsAgent - summarizes only REAL supplied metrics; never invents data.
    """

    @property
    def name(self) -> str:
        return "analytics"

    @property
    def role(self) -> str:
        return "Analyzes data, creates insights, and generates reports"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return AnalyticsAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return AnalyticsAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def default_tools(self) -> list[str]:
        return ['analyze_metrics', 'memory_retrieve', 'file_write']

    @staticmethod
    def _coerce_number(value: Any) -> Any:
        """Return a float if the value is numeric, else None (no fabrication)."""
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip().rstrip("%"))
            except (ValueError, AttributeError):
                return None
        return None

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            sources = list(input_data.get("data_sources", []) or [])
            metrics = list(input_data.get("metrics", []) or [])
            analysis_type = (input_data.get("analysis_type") or "descriptive").strip()

            self.logger.info(
                f"Analytics: type={analysis_type} sources={len(sources)} metrics={len(metrics)}"
            )

            tools_used: List[str] = []
            limitations: List[str] = [
                "This agent only summarizes metric data that is actually supplied; "
                "it does NOT invent metric values, correlations, predictions, or "
                "visualizations.",
            ]

            # Real summary of any supplied structured metric data. We look at the
            # 'metrics' list plus any numeric values present in input or context
            # metadata under a 'metrics'/'data' key.
            metric_summary: List[Dict[str, Any]] = []
            numeric_summary: Dict[str, float] = {}

            # 1) metrics provided as name strings.
            for m in metrics:
                metric_summary.append({"metric": str(m), "value_supplied": False})

            # 2) structured numeric data passed via input_data / context.metadata.
            candidate_dicts: List[Dict[str, Any]] = []
            for key in ("metrics_data", "data", "values"):
                v = input_data.get(key)
                if isinstance(v, dict):
                    candidate_dicts.append(v)
            meta = getattr(context, "metadata", None) or {}
            for key in ("metrics", "metrics_data", "data"):
                v = meta.get(key)
                if isinstance(v, dict):
                    candidate_dicts.append(v)

            for d in candidate_dicts:
                for k, raw in d.items():
                    num = self._coerce_number(raw)
                    if num is not None:
                        numeric_summary[str(k)] = num
                        metric_summary.append({"metric": str(k), "value": num, "value_supplied": True})

            if numeric_summary:
                tools_used.append("analyze_metrics")
                vals = list(numeric_summary.values())
                numeric_summary["_count"] = float(len(vals))
                numeric_summary["_sum"] = float(sum(vals))
                numeric_summary["_min"] = float(min(vals))
                numeric_summary["_max"] = float(max(vals))
                numeric_summary["_mean"] = float(sum(vals) / len(vals))

            have_data = bool(metric_summary) or bool(numeric_summary)

            # Optional labelled model insight.
            model_insight = ""
            provider_used = ""
            tokens: Dict[str, int] = {}
            instruction = task_text(input_data, "analysis_type")
            if provider_configured():
                desc_parts = []
                if sources:
                    desc_parts.append(f"data_sources={sources}")
                if metrics:
                    desc_parts.append(f"metrics={metrics}")
                if numeric_summary:
                    real_vals = {k: v for k, v in numeric_summary.items() if not k.startswith("_")}
                    desc_parts.append(f"supplied_values={real_vals}")
                llm = await llm_complete(
                    self.config.model,
                    f"Analysis request ({analysis_type}): {instruction}\n"
                    + ("Context: " + "; ".join(desc_parts) + "\n" if desc_parts else "")
                    + "Give a brief analytical insight. Only reason about the "
                    "values explicitly supplied above; do NOT invent numbers.",
                    system="You are a data analyst. Never fabricate metric values "
                           "or trends that were not supplied.",
                    temperature=self.config.temperature,
                )
                if llm is not None:
                    model_insight = llm["text"]
                    provider_used = llm["provider_used"]
                    tokens = llm["tokens"]
                    tools_used.append("model_router")
                    limitations.append(
                        "model_insight is model-generated and UNVERIFIED."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; no "
                        "model insight was produced."
                    )
            else:
                limitations.append(no_provider_limitation())

            if not have_data:
                limitations.append(
                    "No structured metric values were supplied (only source/metric "
                    "names, if any); numeric summary is empty."
                )

            insights: List[Dict[str, Any]] = []
            if numeric_summary:
                insights.append({
                    "type": "numeric_summary",
                    "metrics_counted": int(numeric_summary.get("_count", 0)),
                    "mean": numeric_summary.get("_mean"),
                    "min": numeric_summary.get("_min"),
                    "max": numeric_summary.get("_max"),
                })
            if model_insight:
                insights.append({"type": "model_insight", "unverified": True,
                                 "text": model_insight[:1500]})

            output_text = (
                f"Analytics[{analysis_type}]: sources={len(sources)} "
                f"metrics={len(metrics)} numeric_values={len([k for k in numeric_summary if not k.startswith('_')])} "
                f"provider={provider_used or 'none'} "
                f"(no values invented)."
            )

            return self.create_result(
                success=True,
                result_data={
                    "analysis_completed": True,
                    "analysis_type": analysis_type,
                    "data_sources_provided": len(sources),
                    "metrics_provided": len(metrics),
                    "metric_summary": metric_summary,
                    "numeric_summary": numeric_summary,
                    "model_insight": model_insight,
                    "provider_used": provider_used,
                    "insights": insights,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=sorted(set(tools_used)),
                tokens_used=tokens or {},
            )

        except Exception as e:
            self.logger.error(f"analytics task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
