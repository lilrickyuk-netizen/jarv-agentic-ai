"""
JARV Backend - ResearchAgent

Researches a query using the real model router/provider when one is
configured, plus the local execution context (memories, prior step results,
workspace rules) that is actually available at run time.

This agent does NOT fabricate research. It does not invent external web
results: there is no external web/search tool wired into this agent, so
`external_search_used` is always False and that limitation is reported
honestly. When no LLM provider is configured it performs only local/contextual
analysis and says so. There are no hardcoded confidence scores or fake sources.
"""
from typing import Dict, Any, List, Optional, Type
import json
import re
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class ResearchAgentInput(BaseModel):
    """ResearchAgent input"""
    query: str = Field(..., description="Research query")
    sources: List[str] = Field(default_factory=list, description="Specific sources/context to consider")
    depth: str = Field(default="medium", description="shallow, medium, deep")


class ResearchAgentOutput(BaseModel):
    """ResearchAgent output (honest; no fabricated metrics)."""
    query: str
    findings: List[Dict[str, str]]
    sources_consulted: List[str]
    recommendations: List[str]
    related_topics: List[str]
    external_search_used: bool
    provider_used: Optional[str]
    limitations: List[str]


class ResearchAgent(AgentBase):
    """ResearchAgent - real model-backed + local-context research."""

    @property
    def name(self) -> str:
        return "research"

    @property
    def role(self) -> str:
        return "Researches technologies, solutions, and best practices"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ResearchAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ResearchAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def default_tools(self) -> List[str]:
        return ['http_get', 'http_post', 'file_read', 'memory_search']

    # ----- provider detection -------------------------------------------------

    @staticmethod
    def _provider_configured() -> bool:
        """True only if a real LLM API key is configured (honest gate)."""
        try:
            from app.core.config import settings
        except Exception:  # noqa: BLE001
            return False
        for attr in ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
            if getattr(settings, attr, None):
                return True
        return False

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        candidates: List[str] = []
        if fence:
            candidates.append(fence.group(1))
        first, last = text.find("{"), text.rfind("}")
        if first != -1 and last != -1 and last > first:
            candidates.append(text[first:last + 1])
        for cand in candidates:
            try:
                parsed = json.loads(cand)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:  # noqa: BLE001
                continue
        return None

    # ----- local context ------------------------------------------------------

    def _local_context(self, context: AgentContext, sources: List[str]) -> List[str]:
        """What was ACTUALLY available locally (no fabrication)."""
        consulted: List[str] = []
        mem = getattr(context, "memory_context", None) or []
        if mem:
            consulted.append(f"local_memory_context ({len(mem)} item(s))")
        prev = getattr(context, "previous_results", None) or []
        if prev:
            consulted.append(f"previous_step_results ({len(prev)} item(s))")
        rules = getattr(context, "workspace_rules", None) or []
        if rules:
            consulted.append(f"workspace_rules ({len(rules)} rule(s))")
        for s in sources:
            if s:
                consulted.append(f"caller_supplied_source:{s}")
        return consulted

    async def run(self, input_data: Dict[str, Any], context: AgentContext) -> AgentResult:
        try:
            query = (input_data.get("query") or "").strip()
            depth = input_data.get("depth", "medium")
            sources = input_data.get("sources", []) or []

            if not query:
                return self.create_result(
                    success=False,
                    result_data={
                        "query": "",
                        "findings": [],
                        "sources_consulted": [],
                        "recommendations": [],
                        "related_topics": [],
                        "external_search_used": False,
                        "provider_used": None,
                        "limitations": ["No query provided; nothing to research."],
                    },
                    output_text="Research could not run: empty query.",
                    error_message="empty query",
                )

            self.logger.info(f"Researching: {query} (depth: {depth})")

            sources_consulted = self._local_context(context, sources)
            limitations: List[str] = [
                "No external web/search tool is wired into this agent; "
                "external_search_used is False and findings are not verified "
                "against live external sources.",
            ]

            findings: List[Dict[str, str]] = []
            recommendations: List[str] = []
            related_topics: List[str] = []
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            if self._provider_configured():
                llm = await self._llm_research(query, depth, context)
                if llm is not None:
                    findings = llm["findings"]
                    recommendations = llm["recommendations"]
                    related_topics = llm["related_topics"]
                    provider_used = llm["provider_used"]
                    tokens = llm["tokens"]
                    sources_consulted.append(f"model:{provider_used}")
                    limitations.append(
                        "Findings are model-generated analysis and may be "
                        "inaccurate or outdated; verify before acting."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; "
                        "returned local/contextual analysis only."
                    )
            else:
                limitations.append(
                    "No LLM provider API key is configured; performed local/"
                    "contextual analysis only (no model reasoning)."
                )

            # Local/contextual analysis is always recorded honestly so the
            # agent returns structured output grounded in the real input even
            # when no provider answered.
            if not findings:
                findings.append({
                    "type": "local_analysis",
                    "point": f"Query: {query}",
                    "detail": (
                        "No model output available. Local context consulted: "
                        + (", ".join(sources_consulted) if sources_consulted
                           else "none")
                    ),
                })
            if not recommendations:
                recommendations.append(
                    "Configure an LLM provider and/or an external search tool to "
                    "produce verified research; otherwise treat results as "
                    "unverified context only."
                )

            output_text = (
                f"Research on '{query}': {len(findings)} finding(s); "
                f"provider={provider_used or 'none'}; external_search=False; "
                f"{len(limitations)} limitation(s) noted."
            )

            return self.create_result(
                success=True,
                result_data={
                    "query": query,
                    "findings": findings,
                    "sources_consulted": sources_consulted,
                    "recommendations": recommendations,
                    "related_topics": related_topics,
                    "external_search_used": False,
                    "provider_used": provider_used,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(["model_router"] if provider_used else []),
                tokens_used=tokens or {},
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"research task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )

    async def _llm_research(
        self, query: str, depth: str, context: AgentContext
    ) -> Optional[Dict[str, Any]]:
        """Call the real model router. Returns None on any provider failure."""
        try:
            from app.core.providers import get_router, CompletionRequest, Message
        except Exception as e:  # noqa: BLE001
            self.logger.warning(f"providers import failed: {e}")
            return None

        ctx_lines: List[str] = []
        for m in (getattr(context, "memory_context", None) or [])[:5]:
            c = m.get("content") if isinstance(m, dict) else None
            if c:
                ctx_lines.append(f"- memory: {str(c)[:200]}")
        for r in (getattr(context, "previous_results", None) or [])[:5]:
            if isinstance(r, dict):
                ctx_lines.append(f"- prior: {str(r)[:200]}")

        prompt = (
            f"Research request (depth={depth}): {query}\n\n"
            + ("Local context:\n" + "\n".join(ctx_lines) + "\n\n" if ctx_lines else "")
            + "You have NO live web access. Base your analysis on general "
            "knowledge and the local context only. Respond with ONLY a JSON "
            "object: {\"findings\":[{\"point\":\"...\",\"detail\":\"...\"}],"
            "\"recommendations\":[\"...\"],\"related_topics\":[\"...\"]}"
        )

        try:
            router = get_router()
            req = CompletionRequest(
                model=self.config.model,
                messages=[Message(role="user", content=prompt)],
                temperature=self.config.temperature,
                max_tokens=1200,
                system="You are a careful research analyst. Never fabricate "
                       "citations or claim sources you did not access.",
            )
            resp = await router.complete(req)
        except Exception as e:  # noqa: BLE001 - provider unavailable/errored
            self.logger.warning(f"research LLM call failed: {e}")
            return None

        data = self._extract_json(resp.content or "")
        findings: List[Dict[str, str]] = []
        recommendations: List[str] = []
        related: List[str] = []
        if data:
            for f in (data.get("findings") or []):
                if isinstance(f, dict):
                    findings.append({
                        "point": str(f.get("point", "")).strip(),
                        "detail": str(f.get("detail", "")).strip(),
                    })
            recommendations = [str(x).strip() for x in (data.get("recommendations") or []) if str(x).strip()]
            related = [str(x).strip() for x in (data.get("related_topics") or []) if str(x).strip()]
        if not findings:
            # Model answered but not as JSON: keep the raw analysis honestly.
            findings = [{"point": "model_analysis", "detail": (resp.content or "").strip()[:1500]}]

        provider_used = f"{resp.provider}:{resp.model}" if getattr(resp, "provider", None) else resp.model
        return {
            "findings": findings,
            "recommendations": recommendations,
            "related_topics": related,
            "provider_used": provider_used,
            "tokens": dict(resp.usage) if getattr(resp, "usage", None) else {},
        }
