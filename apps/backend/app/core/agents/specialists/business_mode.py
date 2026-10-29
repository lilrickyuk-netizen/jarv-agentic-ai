"""
JARV Backend - Business agents on real tools (Repair 12e-4a)

The marketing, content, onboarding, community, partnerships and sales agents
work through the business tools (``app.tools.business``) via their toolbox:
every draft is grounded in the workspace's facts and saved; every pipeline or
moderation change is authority-checked, logged as a ToolRun and audited;
nothing is published or sent without a rule or Richard's approval.

- Tool loop: with a model provider, the agent plans and acts with its tools.
- Direct: without one, the agent runs the tool that matches its request (for
  example a marketing "email" campaign drafts an email sequence).

Both need a database session and a workspace. The unit-test suite opts in per
test (``metadata["business_enabled"]``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.agents.specialists.tool_mode import RECALL, _lines

COMMON = ["decide_next_best_actions", "summarise_feedback", "create_decision_log"] + RECALL


def _group(name: str) -> List[str]:
    if name == "revenue_ops":
        from app.tools.revenue import REVENUE_TOOLS

        return [t._name for t in REVENUE_TOOLS]
    if name == "assets":
        from app.tools.assets_library import ASSET_TOOLS

        return [t._name for t in ASSET_TOOLS]
    from app.tools.business import TOOLS_BY_GROUP

    return list(TOOLS_BY_GROUP.get(name, []))


@dataclass(frozen=True)
class BusinessMode:
    groups: Tuple[str, ...]
    extra: Tuple[str, ...]
    instructions: str
    brief: Callable[[Dict[str, Any]], str]
    direct: Callable[[Dict[str, Any]], Tuple[str, Dict[str, Any]]]

    def tools(self) -> List[str]:
        out: List[str] = []
        for group in self.groups:
            out += _group(group)
        return list(dict.fromkeys(out + list(self.extra) + COMMON))


_GROUND = ("Every draft tool already grounds the text in the workspace's real facts; give it a precise brief "
           "(topic, audience, tone) and read what it returns. Keep [confirm: ...] markers for anything the facts "
           "do not cover; never invent customers, numbers, quotes or features. Nothing is published or sent: "
           "posting publicly or emailing from Richard's accounts is a hard boundary.")


def _marketing(d):
    tool = {"email": "create_email_sequence", "social": "create_post", "content": "create_landing_copy",
            "ads": "create_campaign", "press": "create_press_release", "video": "create_video_script",
            "app_store": "create_app_store_copy"}.get(str(d.get("campaign_type") or "").lower(), "create_campaign")
    return tool, {"topic": d.get("message"), "audience": d.get("target_audience"), "channels": d.get("channels") or [],
                  "campaign_type": d.get("campaign_type")}


def _content(d):
    tool = {"blog": "create_technical_blog", "tutorial": "create_tutorial", "changelog": "create_changelog",
            "release_notes": "create_release_notes", "guide": "create_developer_guide", "api": "create_api_example",
            "help": "create_help_article", "comparison": "create_comparison_article",
            "implementation": "create_implementation_guide", "case_study": "create_technical_blog",
            "whitepaper": "create_technical_blog"}.get(str(d.get("content_type") or "").lower(), "create_technical_blog")
    return tool, {"topic": d.get("topic"), "audience": d.get("target_audience")}


def _onboarding(d):
    custom = d.get("customization") or {}
    tool = custom.get("tool") if custom.get("tool") in _group("onboarding") else "create_onboarding_flow"
    return tool, {"topic": d.get("product"), "audience": d.get("user_type")}


def _community(d):
    action = str(d.get("action") or "post").lower()
    if action == "respond":
        return "draft_community_reply", {"message": d.get("content"), "channel": d.get("platform")}
    if action == "analyze":
        return "summarise_community_feedback", {}
    if action == "moderate":
        return "read_community_messages", {"status": "new"}
    tool = {"github": "create_github_discussion_reply", "discord": "create_discord_announcement",
            "forum": "create_community_update"}.get(str(d.get("platform") or "").lower(), "create_community_update")
    return tool, {"topic": d.get("content"), "audience": d.get("target_audience")}


def _partnerships(d):
    op = str(d.get("operation") or "identify").lower()
    criteria = d.get("criteria") or {}
    if op == "identify":
        return "create_partner_shortlist", {"partner_type": d.get("partner_type") or "technology",
                                            "candidates": criteria.get("candidates") or [],
                                            "criteria": {k: float(v) for k, v in (criteria.get("weights") or {}).items()}}
    tool = {"reach_out": "create_partner_outreach", "negotiate": "create_partner_meeting_brief",
            "finalize": "create_partnership_summary", "integrate": "create_integration_proposal"}.get(op,
                                                                                                  "create_partner_outreach")
    return tool, {"topic": criteria.get("proposal") or criteria.get("topic"), "partner_id": criteria.get("partner_id"),
                  "partner_name": criteria.get("partner_name")}


def _sales(d):
    op = str(d.get("operation") or "lead").lower()
    contact = d.get("contact_info") or {}
    if op in ("lead", "close"):
        return "update_sales_pipeline", {
            "deal_id": contact.get("deal_id"), "title": contact.get("deal") or contact.get("company") or contact.get("name"),
            "stage": "closed_won" if op == "close" else (d.get("stage") if d.get("stage") in (
                "prospecting", "qualified", "proposal", "negotiation") else "prospecting"),
            "value": d.get("deal_value") or None, "contact_name": contact.get("name"),
            "contact_email": contact.get("email"), "company": contact.get("company")}
    tool = {"proposal": "create_prospect_brief", "follow_up": "create_follow_up_sequence",
            "script": "create_sales_script", "summary": "create_sales_summary"}.get(op, "create_prospect_brief")
    return tool, {"deal_id": contact.get("deal_id"), "prospect": ", ".join(f"{k}: {v}" for k, v in contact.items())}


_NUMBERS = ("Work from measured numbers only: every revenue, subscription, conversion and payment figure comes from "
            "a tool result, which names its source (Stripe or recorded revenue). Record KPIs with "
            "update_revenue_operations_loop. Nothing here moves money, changes prices or charges a customer; "
            "pricing and offers are drafted for Richard, and spending beyond the approved budget is a hard boundary.")


def _days(d) -> int:
    raw = str(d.get("time_period") or d.get("timeframe") or "30").lower().rstrip("d").strip()
    return max(1, min(365, int(raw))) if raw.isdigit() else 30


def _finance(d):
    op = str(d.get("operation") or "reporting").lower()
    tool = {"revenue": "check_revenue_metrics", "subscriptions": "check_subscription_metrics",
            "failed_payments": "check_failed_payments", "payments": "check_payment_events",
            "conversion": "check_conversion_metrics"}.get(op)
    if op == "pricing":
        return "create_pricing_review", {"topic": d.get("category") or "current pricing"}
    if tool == "check_payment_events":
        return tool, {}
    return tool or "update_revenue_operations_loop", {"days": _days(d)}


def _growth(d):
    metric = str(d.get("growth_metric") or "acquisition").lower()
    tool = {"revenue": "check_revenue_metrics", "mrr": "check_subscription_metrics",
            "retention": "check_subscription_metrics", "churn": "check_subscription_metrics",
            "traffic": "check_analytics"}.get(metric, "check_conversion_metrics")
    return tool, {"days": _days(d)}


def _business(d):
    kind = str(d.get("report_type") or "metrics").lower()
    if kind in ("pricing", "offer"):
        return ("create_pricing_review" if kind == "pricing" else "create_offer_draft"), {
            "topic": ", ".join(d.get("metrics") or []) or kind}
    tool = {"revenue": "check_revenue_metrics", "subscriptions": "check_subscription_metrics",
            "conversion": "check_conversion_metrics"}.get(kind, "update_revenue_operations_loop")
    return tool, {"days": _days(d)}


def _creation(d):
    spec = d.get("specifications") or {}
    url = spec.get("url") or spec.get("source_url")
    if url:
        return "download_asset", {"url": url, "licence": spec.get("licence") or spec.get("license"),
                                  "author": spec.get("author"), "source_page": spec.get("source_page"),
                                  "folder": spec.get("folder") or "assets", "filename": spec.get("filename"),
                                  "commercial": spec.get("commercial", True)}
    if spec.get("licence") or spec.get("license"):
        return "check_licence", {"licence": spec.get("licence") or spec.get("license"),
                                 "commercial": spec.get("commercial", True)}
    return None, {}


MODES: Dict[str, BusinessMode] = {
    "marketing": BusinessMode(("marketing",), ("create_kpi_dashboard",),
                              "Plan and draft marketing from the product's real features and changes. " + _GROUND,
                              lambda d: _lines([("Campaign type", d.get("campaign_type")), ("Audience", d.get("target_audience")),
                                                ("Message", d.get("message")), ("Channels", ", ".join(d.get("channels") or []))]),
                              _marketing),
    "content": BusinessMode(("content",), (),
                            "Write technical and help content from the code, commits and docs. " + _GROUND,
                            lambda d: _lines([("Content type", d.get("content_type")), ("Topic", d.get("topic")),
                                              ("Audience", d.get("target_audience")), ("Length", d.get("length"))]),
                            _content),
    "onboarding": BusinessMode(("onboarding",), ("update_knowledge_base",),
                               "Design onboarding from the real setup steps and pages; measure friction first with "
                               "analyse_activation_friction. " + _GROUND,
                               lambda d: _lines([("User type", d.get("user_type")), ("Product", d.get("product"))]),
                               _onboarding),
    "community": BusinessMode(("community",), (),
                              "Keep the community healthy: read new messages, moderate them by the rules (never "
                              "delete), and draft replies and updates. " + _GROUND,
                              lambda d: _lines([("Action", d.get("action")), ("Platform", d.get("platform")),
                                                ("Content", d.get("content"))]),
                              _community),
    "partnerships": BusinessMode(("partnership",), (),
                                 "Build partnerships: shortlist real candidates against clear criteria, keep the "
                                 "partner pipeline current, and draft outreach and proposals. Making a partnership "
                                 "active is a binding commitment and waits for Richard. " + _GROUND,
                                 lambda d: _lines([("Operation", d.get("operation")), ("Partner type", d.get("partner_type")),
                                                   ("Criteria", d.get("criteria"))]),
                                 _partnerships),
    "sales": BusinessMode(("sales",), (),
                          "Run the sales pipeline: keep deals current with update_sales_pipeline and draft scripts, "
                          "sequences and briefs from the real product facts. " + _GROUND,
                          lambda d: _lines([("Operation", d.get("operation")), ("Contact", d.get("contact_info")),
                                            ("Deal value", d.get("deal_value")), ("Stage", d.get("stage"))]),
                          _sales),
    "finance": BusinessMode(("revenue_ops", "revenue"), ("create_kpi_dashboard",),
                            "Run revenue operations: measure revenue, MRR, churn, failed payments and conversion, "
                            "record them, and set the next actions. " + _NUMBERS,
                            lambda d: _lines([("Operation", d.get("operation")), ("Period", d.get("time_period")),
                                              ("Category", d.get("category"))]),
                            _finance),
    "growth": BusinessMode(("revenue_ops", "revenue"), ("create_kpi_dashboard",),
                           "Find the growth constraint in the funnel and plan experiments against it: measure with "
                           "check_conversion_metrics and check_analytics, then create_revenue_experiment with a "
                           "baseline. " + _NUMBERS,
                           lambda d: _lines([("Metric", d.get("growth_metric")), ("Current", d.get("current_value")),
                                             ("Target", d.get("target_value")), ("Timeframe", d.get("timeframe"))]),
                           _growth),
    "business": BusinessMode(("revenue_ops", "revenue"), ("create_kpi_dashboard",),
                             "Report on the business from measured numbers and draft pricing reviews and offers "
                             "grounded in them. " + _NUMBERS,
                             lambda d: _lines([("Report", d.get("report_type")), ("Period", d.get("time_period")),
                                               ("Metrics", ", ".join(d.get("metrics") or []))]),
                             _business),
    "creation": BusinessMode(("assets",), (),
                             "Source assets legally: find candidates with web_search, confirm the licence with "
                             "check_licence, then download_asset with the licence, author and source page. Never "
                             "use an asset whose licence is unknown or forbids the use. Finish with "
                             "generate_asset_manifest and update_asset_licence_file.",
                             lambda d: _lines([("Asset type", d.get("asset_type")), ("Style", d.get("style")),
                                               ("Specifications", d.get("specifications"))]),
                             _creation),
}


def tools_for(agent_name: str) -> List[str]:
    return MODES[agent_name].tools()


def business_enabled(context: Any) -> bool:
    from app.core.config import settings

    if context.db_session is None or context.workspace_id is None:
        return False
    return bool(context.metadata.get("business_enabled", not settings.TESTING))


async def run(agent: Any, input_data: Dict[str, Any], context: Any):
    """AgentResult from the tool loop or the matching tool; None when neither applies."""
    mode = MODES[agent.name]
    if agent.tools_enabled(context):
        outcome = await agent.use_tools(context, mode.brief(input_data) or str(input_data),
                                        instructions=mode.instructions, max_steps=14)
        return agent.result_from_tools(outcome, mode="tools")
    if not business_enabled(context):
        return None
    from app.core.agents.toolbox import AgentToolbox

    toolbox = AgentToolbox(agent, context)
    try:
        await toolbox.prepare()
    except RuntimeError as exc:
        agent.logger.warning(f"{agent.name}: business tools unavailable: {exc}")
        return None
    tool, args = mode.direct(input_data)
    if tool is None:
        return None
    result = await toolbox.call(tool, {k: v for k, v in args.items() if v not in (None, "", [], {})})
    data = result.get("data") or {}
    if agent.name == "community" and tool == "read_community_messages" and result.get("success"):
        decisions = []
        for message in data.get("messages", []):
            moderated = await toolbox.call("moderate_community_item_with_rules", {"item_id": message["id"]})
            decisions.append({"item": message["id"], **{k: (moderated.get("data") or {}).get(k)
                                                        for k in ("decision", "reasons")}})
        data = {**data, "moderation": decisions}
    trail = toolbox.summary()
    success = bool(result.get("success"))
    return agent.create_result(
        success=success,
        result_data={**data, "mode": "business", "tool": tool, "tool_calls": trail["calls"],
                     "blocked_actions": trail["blocked"], "approval_needed": trail["approval_needed"]},
        output_text=result.get("output") or result.get("summary") or f"{tool}: {'done' if success else 'failed'}",
        tools_used=sorted({c["name"] for c in trail["calls"]}),
        requires_approval=bool(trail["approval_needed"]),
        error_message=None if success else (result.get("error") or result.get("reason")))
