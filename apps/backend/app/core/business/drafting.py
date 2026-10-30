"""
JARV Backend - Grounded business drafting

One engine writes every marketing, content, onboarding, community,
partnership, sales and support draft. Each kind of document has a fixed
section outline. The text is written from the workspace's real facts
(app.core.business.facts) plus the caller's brief:

- with a model provider, by the model, told to use only those facts and to
  mark anything it does not know as "[confirm: ...]";
- without one, by assembling the same outline from the facts themselves
  (commits, completed work, README features, routes, pages, commands, FAQs,
  KPIs); anything the facts do not cover is marked "[confirm: ...]" for
  Richard rather than made up.

Drafts are saved (ContentItem, MarketingCampaign, OnboardingFlow or
CommunityItem), never published or sent: posting publicly or emailing from
Richard's accounts is a hard boundary. A draft can also be written into the
workspace folder under docs/.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.business.facts import Facts, gather
from app.core.security import redact_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DraftKind:
    tool: str
    group: str
    label: str
    sections: Tuple[Tuple[str, str], ...]
    store: str = "content"
    description: str = ""
    sequence: bool = False


def _k(tool, group, label, sections, store="content", description="", sequence=False) -> DraftKind:
    return DraftKind(tool, group, label, tuple(sections), store, description or f"Draft a {label} grounded in the workspace.",
                     sequence)


KINDS: Dict[str, DraftKind] = {k.tool: k for k in [
    # marketing
    _k("create_campaign", "marketing", "marketing campaign plan", [
        ("topic", "Goal"), ("audience", "Audience"), ("pitch", "Positioning"), ("features", "Proof points"),
        ("channels", "Channels and cadence"), ("kpis", "Success measures"), ("cta", "Call to action")], store="campaign"),
    _k("create_post", "marketing", "social post", [("hook", "Hook"), ("features", "What it does"), ("cta", "Call to action")]),
    _k("create_email_sequence", "marketing", "email sequence", [("pitch", "Introduction"), ("features", "Feature focus"),
                                                                ("cta", "Call to action")], sequence=True),
    _k("create_landing_copy", "marketing", "landing page copy", [
        ("hook", "Headline"), ("pitch", "Subheadline"), ("features", "Features"), ("faq", "FAQ"), ("cta", "Call to action")]),
    _k("create_app_store_copy", "marketing", "app store listing", [
        ("hook", "Title and subtitle"), ("pitch", "Description"), ("features", "What you can do"),
        ("changes", "What's new"), ("keywords", "Keywords")]),
    _k("create_press_release", "marketing", "press release", [
        ("hook", "Headline"), ("topic", "Announcement"), ("pitch", "About the product"), ("features", "Highlights"),
        ("confirm:a quote from the founder", "Quote"), ("company", "About the company"), ("cta", "Availability")]),
    _k("create_video_script", "marketing", "video script", [
        ("hook", "Opening (0-5s)"), ("pitch", "Problem and promise"), ("features", "Demo beats"), ("cta", "Close")]),
    # content
    _k("create_technical_blog", "content", "technical blog post", [
        ("topic", "Introduction"), ("stack", "How it is built"), ("changes", "What changed recently"),
        ("routes", "Key interfaces"), ("cta", "Try it")]),
    _k("create_tutorial", "content", "tutorial", [("topic", "What you will build"), ("prereqs", "Prerequisites"),
                                                  ("setup", "Steps"), ("routes", "Using the API"), ("cta", "Next steps")]),
    _k("create_changelog", "content", "changelog", [("changes", "Changes")]),
    _k("create_release_notes", "content", "release notes", [("topic", "Summary"), ("changes", "What's new"),
                                                            ("setup", "Upgrade notes")]),
    _k("create_developer_guide", "content", "developer guide", [
        ("pitch", "Overview"), ("stack", "Architecture"), ("setup", "Local setup"), ("routes", "API reference"),
        ("pages", "App structure"), ("prereqs", "Requirements")]),
    _k("create_api_example", "content", "API example", [("routes", "Endpoints"), ("example", "Example requests")]),
    _k("create_help_article", "content", "help article", [("topic", "Question"), ("readme", "Answer"),
                                                          ("faq", "Related questions")]),
    _k("create_comparison_article", "content", "comparison article", [
        ("topic", "What is compared"), ("pitch", "Our approach"), ("features", "Capabilities"),
        ("confirm:verified facts about the alternatives (with sources)", "Alternatives"), ("cta", "Choosing")]),
    _k("create_implementation_guide", "content", "implementation guide", [
        ("topic", "Goal"), ("prereqs", "Before you start"), ("setup", "Implementation steps"), ("routes", "Integration points"),
        ("confirm:rollout and verification plan", "Rollout")]),
    # onboarding
    _k("create_onboarding_flow", "onboarding", "onboarding flow", [("pitch", "Welcome"), ("setup", "Steps"),
                                                                    ("features", "First wins")], store="onboarding"),
    _k("create_product_tour", "onboarding", "product tour", [("pages", "Tour stops"), ("features", "What to show")],
       store="onboarding"),
    _k("create_setup_checklist", "onboarding", "setup checklist", [("setup", "Checklist")], store="onboarding"),
    _k("create_welcome_email", "onboarding", "welcome email", [("hook", "Subject"), ("pitch", "Welcome"),
                                                               ("setup", "Get started"), ("cta", "Call to action")]),
    _k("create_activation_email", "onboarding", "activation email", [("hook", "Subject"), ("features", "The one thing to try"),
                                                                     ("cta", "Call to action")]),
    _k("create_empty_state_copy", "onboarding", "empty state copy", [("pages", "Screens"), ("cta", "Primary action")]),
    _k("create_first_run_experience", "onboarding", "first-run experience", [
        ("pitch", "First screen"), ("setup", "Guided steps"), ("features", "First success")], store="onboarding"),
    # community
    _k("draft_community_reply", "community", "community reply", [("reply", "Reply"), ("faq", "Related answers")],
       store="community"),
    _k("create_community_update", "community", "community update", [("topic", "Update"), ("changes", "What shipped"),
                                                                     ("objectives", "What's next")], store="community"),
    _k("create_github_discussion_reply", "community", "GitHub discussion reply", [("reply", "Reply"),
                                                                                   ("routes", "Relevant code")],
       store="community"),
    _k("create_discord_announcement", "community", "Discord announcement", [("hook", "Announcement"),
                                                                             ("changes", "Highlights"), ("cta", "Link")],
       store="community"),
    _k("create_forum_reply", "community", "forum reply", [("reply", "Reply"), ("faq", "Related answers")], store="community"),
    _k("create_developer_relations_update", "community", "developer relations update", [
        ("topic", "Summary"), ("changes", "Developer-facing changes"), ("routes", "API surface"),
        ("objectives", "Coming up")], store="community"),
    # partnerships
    _k("create_partner_outreach", "partnership", "partner outreach email", [
        ("partner", "Partner"), ("hook", "Subject"), ("pitch", "Why us"), ("topic", "Proposal"), ("cta", "Ask")]),
    _k("create_partner_follow_up", "partnership", "partner follow-up", [("partner", "Partner"), ("topic", "Follow-up"),
                                                                        ("cta", "Next step")]),
    _k("create_integration_proposal", "partnership", "integration proposal", [
        ("partner", "Partner"), ("topic", "Integration"), ("routes", "Our API surface"), ("features", "Joint value"),
        ("confirm:commercial terms", "Terms")]),
    _k("create_reseller_plan", "partnership", "reseller plan", [
        ("pitch", "Product"), ("audience", "Reseller profile"), ("confirm:margins and pricing", "Commercials"),
        ("setup", "Enablement")]),
    _k("create_affiliate_plan", "partnership", "affiliate plan", [
        ("pitch", "Product"), ("audience", "Affiliate profile"), ("confirm:commission rate and cookie window", "Commission"),
        ("cta", "Tracking link")]),
    _k("create_partner_meeting_brief", "partnership", "partner meeting brief", [
        ("partner", "Partner"), ("topic", "Agenda"), ("pitch", "Our position"), ("kpis", "Numbers to share")]),
    _k("create_partnership_summary", "partnership", "partnership summary", [("pipeline", "Pipeline")]),
    _k("create_api_partnership_plan", "partnership", "API partnership plan", [
        ("partner", "Partner"), ("routes", "API surface"), ("topic", "Use cases"), ("confirm:rate limits and SLAs", "Terms")]),
    # sales
    _k("create_sales_script", "sales", "sales script", [("hook", "Opener"), ("audience", "Discovery questions"),
                                                        ("features", "Value points"), ("faq", "Objection handling"),
                                                        ("cta", "Close")]),
    _k("create_sales_sequence", "sales", "sales outreach sequence", [("pitch", "Opening"), ("features", "Value point"),
                                                                     ("cta", "Ask")], sequence=True),
    _k("create_follow_up_sequence", "sales", "follow-up sequence", [("prospect", "Context"), ("features", "Value point"),
                                                                    ("cta", "Ask")], sequence=True),
    _k("create_prospect_brief", "sales", "prospect brief", [("prospect", "Prospect"), ("pitch", "Fit"),
                                                            ("features", "Relevant capabilities"), ("cta", "Next step")]),
    _k("create_sales_summary", "sales", "sales summary", [("pipeline", "Pipeline"), ("kpis", "Metrics")]),
    # revenue (the revenue section is computed from Stripe or recorded revenue at draft time)
    _k("create_offer_draft", "revenue", "offer", [
        ("topic", "Offer"), ("audience", "Who it is for"), ("revenue", "Current numbers"), ("features", "What is included"),
        ("confirm:price, discount and end date", "Terms"), ("cta", "Call to action")]),
    _k("create_pricing_review", "revenue", "pricing review", [
        ("revenue", "Revenue and subscriptions"), ("kpis", "Metrics"), ("pipeline", "Deals and partners"),
        ("topic", "Question under review"), ("confirm:competitor prices with sources", "Market comparison"),
        ("confirm:the decision and its expected effect", "Recommendation")]),
]}


def _confirm(what: str) -> str:
    return f"[confirm: {what}]"


async def _extra(db: AsyncSession, workspace_id: UUID, inputs: Dict[str, Any],
                 kind: Optional[DraftKind] = None) -> Dict[str, Any]:
    """Records a draft is about: partner, CRM contact/deal, pipelines, revenue."""
    from app.models.business import PartnershipRecord
    from app.models.company_crm import CRMContact, CRMDeal

    out: Dict[str, Any] = {}
    if inputs.get("partner_id"):
        partner = (await db.execute(select(PartnershipRecord).where(
            PartnershipRecord.id == _uuid(inputs["partner_id"]), PartnershipRecord.workspace_id == workspace_id))
        ).scalar_one_or_none()
        if partner is None:
            raise LookupError("Partner not found in this workspace")
        out["partner"] = {"name": partner.partner_name, "type": partner.partner_type, "status": partner.status,
                          "contact": partner.contact_name, "notes": partner.description}
    if inputs.get("deal_id"):
        deal = (await db.execute(select(CRMDeal).where(CRMDeal.id == _uuid(inputs["deal_id"]),
                                                       CRMDeal.workspace_id == workspace_id))).scalar_one_or_none()
        if deal is None:
            raise LookupError("Deal not found in this workspace")
        contact = None
        if deal.contact_id:
            contact = (await db.execute(select(CRMContact).where(CRMContact.id == deal.contact_id))).scalar_one_or_none()
        out["prospect"] = {"deal": deal.title, "stage": deal.stage, "value": deal.value, "notes": deal.notes,
                           "contact": contact.name if contact else None, "company": contact.company if contact else None,
                           "role": contact.title if contact else None}
    partners = (await db.execute(select(PartnershipRecord).where(PartnershipRecord.workspace_id == workspace_id))
                ).scalars().all()
    deals = (await db.execute(select(CRMDeal).where(CRMDeal.workspace_id == workspace_id))).scalars().all()
    if kind is not None and kind.group == "revenue":
        from app.core.business.revenue import revenue_service

        try:
            out["revenue"] = {"revenue": await revenue_service.revenue(db, workspace_id, 30),
                              "subscriptions": await revenue_service.subscriptions(db, workspace_id, 30)}
        except RuntimeError as exc:
            out["revenue"] = {"error": str(exc)}
    out["pipeline"] = {
        "partners": [{"name": p.partner_name, "status": p.status, "value": float(p.estimated_value or 0)} for p in partners],
        "deals": [{"title": d.title, "stage": d.stage, "value": d.value or 0} for d in deals]}
    return out


def _uuid(value: Any) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"'{value}' is not a valid id") from None


def _section(key: str, facts: Facts, inputs: Dict[str, Any], extra: Dict[str, Any], index: int = 0) -> str:
    topic = inputs.get("topic") or inputs.get("brief") or ""
    audience = inputs.get("audience") or ""
    if key.startswith("confirm:"):
        return _confirm(key.split(":", 1)[1])
    if key == "topic":
        return topic or _confirm("what this is about")
    if key == "audience":
        return audience or _confirm("who this is for")
    if key == "hook":
        if topic:
            return f"{facts.product}: {topic}"
        return f"{facts.product}: {facts.description}" if facts.description else _confirm("headline")
    if key == "pitch":
        return facts.description or facts.mission or _confirm(f"one-line description of {facts.product}")
    if key == "company":
        return f"{facts.company}. {facts.mission}".strip(". ") if facts.company or facts.mission else _confirm("company boilerplate")
    if key == "features":
        items = facts.features or facts.completed or [c["subject"] for c in facts.commits[:8]]
        if not items:
            return _confirm("features to highlight")
        if index:
            return items[(index - 1) % len(items)]
        return "\n".join(f"- {i}" for i in items[:8])
    if key == "changes":
        since = inputs.get("since")
        commits = [c for c in facts.commits if not since or c["date"] >= str(since)]
        lines = [f"- {c['subject']} ({c['date']}, {c['hash']})" for c in commits[:30]]
        lines += [f"- {t}" for t in facts.completed[:15] if all(t not in l for l in lines)]
        return "\n".join(lines) or _confirm("changes since the last release (no commits or completed tasks found)")
    if key == "cta":
        return f"Try it: {facts.live_url}" if facts.live_url else _confirm("call-to-action link")
    if key in ("setup", "prereqs"):
        if key == "prereqs":
            return ", ".join(facts.stack) if facts.stack else _confirm("requirements")
        order = ["install", "build", "dev", "start", "run", "test", "lint"]
        steps = [f"{n}. {name.title()}: `{facts.commands[name]}`" for n, name in
                 enumerate([o for o in order if o in facts.commands], start=1)]
        return "\n".join(steps) or _confirm("setup steps (no commands detected)")
    if key == "routes":
        if not facts.routes:
            return _confirm("API endpoints (none found in the code)")
        return "\n".join(f"- `{r['method']} {r['path']}` ({r['file']})" for r in facts.routes[:25])
    if key == "example":
        if not facts.routes:
            return _confirm("API endpoints (none found in the code)")
        base = facts.live_url.rstrip("/") if facts.live_url else "http://localhost:8000"
        blocks = []
        for r in facts.routes[:6]:
            body = " -H 'Content-Type: application/json' -d '{}'" if r["method"] in ("POST", "PUT", "PATCH") else ""
            blocks.append(f"```bash\ncurl -X {r['method']} {base}{r['path']}{body}\n```")
        return "\n\n".join(blocks)
    if key == "pages":
        return "\n".join(f"- {p}" for p in facts.pages[:20]) or _confirm("app screens (no pages found)")
    if key == "stack":
        return ", ".join(facts.stack) or _confirm("technology stack")
    if key == "readme":
        return facts.readme[:1500] or _confirm("the answer")
    if key == "faq":
        return "\n".join(f"**{f['q']}** {f['a']}" for f in facts.faqs[:6]) or _confirm("frequently asked questions")
    if key == "kpis":
        return "\n".join(f"- {k['name']}: {k['value']:g}{k.get('unit') or ''}" for k in facts.kpis[:8]) or _confirm("metrics")
    if key == "objectives":
        items = facts.objectives or facts.roadmap
        return "\n".join(f"- {o}" for o in items[:8]) or _confirm("what is coming next")
    if key == "keywords":
        words = re.findall(r"[a-zA-Z]{5,}", " ".join([facts.description] + facts.features))
        return ", ".join(sorted(set(w.lower() for w in words))[:15]) or _confirm("keywords")
    if key == "channels":
        channels = inputs.get("channels") or []
        return ", ".join(channels) if channels else _confirm("channels and cadence")
    if key == "reply":
        message = inputs.get("message") or ""
        matches = [f for f in facts.faqs if any(w in f["q"].lower() for w in re.findall(r"[a-z]{4,}", message.lower()))]
        if matches:
            return f"Thanks for asking. {matches[0]['a']}"
        return _confirm(f"answer to: {message[:200]}") if message else _confirm("the message being answered")
    if key == "partner":
        partner = extra.get("partner")
        return (f"{partner['name']} ({partner['type']}, {partner['status']})" + (f", contact {partner['contact']}"
                if partner.get("contact") else "")) if partner else (inputs.get("partner_name") or _confirm("partner"))
    if key == "prospect":
        prospect = extra.get("prospect")
        if prospect:
            return ", ".join(f"{k}: {v}" for k, v in prospect.items() if v not in (None, ""))
        return inputs.get("prospect") or _confirm("prospect details")
    if key == "revenue":
        data = extra.get("revenue") or {}
        if data.get("error") or not data:
            return _confirm(f"revenue numbers ({data.get('error') or 'not available'})")
        rev, subs = data["revenue"], data["subscriptions"]
        if rev["source"] == "recorded" and not rev.get("has_data") and not subs.get("has_data"):
            return _confirm("revenue numbers (none recorded yet; connect Stripe or record sales)")
        return (f"- Last {rev['period_days']} days ({rev['source']}): gross {rev['gross']:.2f}, refunds "
                f"{rev['refunds']:.2f}, net {rev['net']:.2f} {rev.get('currency', 'USD')} from {rev['payments']} payment(s)\n"
                f"- MRR {subs['mrr']:.2f}, {subs['active']} active subscription(s), {subs['new']} new, "
                f"{subs['cancelled']} cancelled" + (f", churn {subs['churn_rate']:.1%}" if subs.get("churn_rate") is not None else ""))
    if key == "pipeline":
        pipe = extra.get("pipeline") or {}
        lines = [f"- Partner {p['name']}: {p['status']} ({p['value']:g})" for p in pipe.get("partners", [])]
        lines += [f"- Deal {d['title']}: {d['stage']} ({d['value']:g})" for d in pipe.get("deals", [])]
        return "\n".join(lines) or _confirm("pipeline (no partners or deals recorded)")
    return _confirm(key)


def render_template(kind: DraftKind, facts: Facts, inputs: Dict[str, Any], extra: Dict[str, Any]) -> str:
    title = inputs.get("title") or f"{facts.product} {kind.label}"
    out = [f"# {title}"]
    if kind.sequence:
        count = max(1, min(int(inputs.get("count") or 3), 7))
        for n in range(1, count + 1):
            out.append(f"\n## Email {n}")
            for key, heading in kind.sections:
                out.append(f"\n**{heading}:** {_section(key, facts, inputs, extra, index=n if key == 'features' else 0)}")
        return "\n".join(out)
    for key, heading in kind.sections:
        out.append(f"\n## {heading}\n\n{_section(key, facts, inputs, extra)}")
    return "\n".join(out)


async def _model_text(kind: DraftKind, facts: Facts, inputs: Dict[str, Any], extra: Dict[str, Any],
                      model: Optional[str]) -> Optional[Dict[str, Any]]:
    from app.core.agents.specialists import _helpers as helpers

    if not helpers.provider_configured():
        return None
    outline = "\n".join(f"- {heading}" for _key, heading in kind.sections)
    brief = {k: v for k, v in inputs.items() if k not in ("save_to_workspace",) and v not in (None, "", [])}
    prompt = (f"Write a {kind.label} for {facts.product} in Markdown with these sections:\n{outline}\n"
              + (f"Write {inputs.get('count') or 3} emails, each with a subject and body.\n" if kind.sequence else "")
              + f"Brief: {json.dumps(brief, default=str)}\n"
              + (f"Records: {json.dumps(extra, default=str)[:3000]}\n" if extra else "")
              + f"\nFACTS (use only these; never invent numbers, customers, quotes or features; write "
                f"[confirm: what is needed] where a fact is missing):\n{facts.summary()}")
    reply = await helpers.llm_complete(model or "claude-sonnet-4-6", prompt,
                                       system="You are JARV's writer. Accurate, specific, no hype, no invented facts.",
                                       temperature=0.4, max_tokens=2500)
    return reply


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:120] or "draft"


async def _save_file(db: AsyncSession, workspace_id: UUID, kind: DraftKind, title: str, body: str) -> Optional[str]:
    from app.core.workspaces import fs_inspector
    from app.core.workspaces.lifecycle import join_host
    from app.models.workspace import Workspace

    ws = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one()
    root = (ws.config or {}).get("root_path")
    if not root:
        raise ValueError("This workspace has no folder to save the draft into")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    host = join_host(join_host(join_host(root, "docs"), kind.group), f"{_slug(title)[:80]}-{stamp}.md")
    result = fs_inspector.write_file(host, body)
    if not result.accessible:
        raise PermissionError(result.reason or "Could not write the draft file")
    return host


async def draft(db: AsyncSession, workspace_id: UUID, tool: str, inputs: Dict[str, Any], *,
                owner: Optional[UUID] = None, model: Optional[str] = None) -> Dict[str, Any]:
    kind = KINDS.get(tool)
    if kind is None:
        raise ValueError(f"Unknown draft kind '{tool}'")
    facts = await gather(db, workspace_id)
    extra = await _extra(db, workspace_id, inputs, kind)
    reply = await _model_text(kind, facts, inputs, extra, model)
    if reply and reply.get("text", "").strip():
        body, generated_by = reply["text"].strip(), f"model:{reply.get('provider_used')}"
    else:
        body, generated_by = render_template(kind, facts, inputs, extra), "workspace facts"
    body = redact_text(body)
    title = inputs.get("title") or f"{facts.product} {kind.label}" + (f": {inputs['topic']}" if inputs.get("topic") else "")
    title = title[:480]
    gaps = re.findall(r"\[confirm: ([^\]]+)\]", body)
    meta = {"tool": tool, "generated_by": generated_by, "facts_used": facts.known(), "needs_confirmation": gaps,
            "inputs": {k: v for k, v in inputs.items() if k != "save_to_workspace"}, "version": 1}
    file_path = None
    if inputs.get("save_to_workspace"):
        file_path = await _save_file(db, workspace_id, kind, title, body)
        meta["file"] = file_path
    record_id, record_type = await _store(db, workspace_id, kind, title, body, inputs, meta, owner)
    return {"id": str(record_id), "record_type": record_type, "kind": tool, "title": title, "body": body,
            "generated_by": generated_by, "needs_confirmation": gaps, "facts_used": facts.known(), "file": file_path,
            "status": "draft"}


async def _store(db: AsyncSession, workspace_id: UUID, kind: DraftKind, title: str, body: str,
                 inputs: Dict[str, Any], meta: Dict[str, Any], owner: Optional[UUID]) -> Tuple[UUID, str]:
    from app.models.business import MarketingCampaign
    from app.models.content import CommunityItem, ContentItem, OnboardingFlow

    now = datetime.now(timezone.utc)
    if kind.store == "campaign":
        row = MarketingCampaign(
            id=uuid4(), workspace_id=workspace_id, campaign_name=title[:255],
            campaign_type=str(inputs.get("campaign_type") or "launch")[:50], description=inputs.get("topic") or title,
            start_date=_date(inputs.get("start_date")) or now.date(), end_date=_date(inputs.get("end_date")),
            status="draft", target_audience=inputs.get("audience"), content={"plan": body, "channels": inputs.get("channels") or []},
            created_by=owner, tags=["jarv-draft"], meta_data=meta, created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
        return row.id, "marketing_campaign"
    if kind.store == "onboarding":
        steps = _steps(body)
        row = OnboardingFlow(
            id=uuid4(), workspace_id=workspace_id, flow_name=title[:255], flow_type=kind.tool.replace("create_", "")[:50],
            description=inputs.get("topic") or kind.label, target_audience=inputs.get("audience") or "new users",
            steps=steps, total_steps=len(steps), is_active=False, version="1", total_starts=0, total_completions=0,
            created_by=owner, tags=["jarv-draft"], meta_data={**meta, "body": body}, created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
        return row.id, "onboarding_flow"
    if kind.store == "community":
        if owner is None:
            raise ValueError("Community drafts need the workspace owner as author")
        row = CommunityItem(
            id=uuid4(), workspace_id=workspace_id, title=title[:500], item_type=kind.tool.replace("create_", "").replace(
                "draft_", "")[:50], category=inputs.get("channel") or "community", content=body, content_format="markdown",
            author_id=owner, author_name="JARV (draft for Richard)", status="draft", is_published=False,
            parent_item_id=_uuid(inputs["reply_to"]) if inputs.get("reply_to") else None,
            is_reply=bool(inputs.get("reply_to")), tags=["jarv-draft"], meta_data=meta, created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
        return row.id, "community_item"
    row = ContentItem(
        id=uuid4(), workspace_id=workspace_id, title=title, content_type=kind.tool.replace("create_", "")[:50],
        category=kind.group, slug=f"{_slug(title)[:100]}-{uuid4().hex[:8]}", content_body=body,
        content_format="markdown", excerpt=body[:300], status="draft", is_published=False, author_id=owner,
        author_name="JARV", tags=["jarv-draft", kind.group], meta_data=meta, created_at=now, updated_at=now)
    db.add(row)
    await db.flush()
    return row.id, "content_item"


def _date(value: Any):
    if not value:
        return None
    from datetime import date

    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _steps(body: str) -> List[Dict[str, Any]]:
    """Numbered or bulleted lines of a draft become onboarding steps."""
    steps = []
    for line in body.splitlines():
        text = re.sub(r"^\s*(\d+\.|[-*])\s+", "", line).strip()
        if text != line.strip() and text and not text.startswith("[confirm"):
            steps.append({"order": len(steps) + 1, "title": text[:200], "done": False})
    if not steps:
        steps = [{"order": 1, "title": "Review this draft", "done": False}]
    return steps[:30]
