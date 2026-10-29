"""
JARV Backend - Onboarding analysis and versioned copy, and the knowledge base

Activation friction is measured from what the workspace records: onboarding
flow starts/completions and their weakest steps, support tickets about
signing up, logging in or setting up, activation KPIs below target, and open
launch-checklist items. Onboarding copy and knowledge-base articles are
edited in place with every previous version kept on the record.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business import SupportTicket
from app.models.content import ContentItem, OnboardingFlow
from app.models.workspace import Workspace

FRICTION_WORDS = ("sign up", "signup", "register", "log in", "login", "verify", "verification", "setup", "set up",
                  "install", "onboard", "getting started", "first", "confused", "stuck", "can't find", "cannot find")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def flow_view(f: OnboardingFlow) -> Dict[str, Any]:
    return {"id": str(f.id), "name": f.flow_name, "type": f.flow_type, "audience": f.target_audience,
            "steps": f.steps, "total_steps": f.total_steps, "version": f.version, "active": f.is_active,
            "starts": f.total_starts, "completions": f.total_completions, "completion_rate": f.completion_rate}


async def analyse_activation_friction(db: AsyncSession, workspace_id: UUID, days: int = 30) -> Dict[str, Any]:
    from app.core.company_ops.service import company_ops

    since = _now() - timedelta(days=days)
    findings: List[Dict[str, Any]] = []
    flows = (await db.execute(select(OnboardingFlow).where(OnboardingFlow.workspace_id == workspace_id))).scalars().all()
    for flow in flows:
        if flow.total_starts:
            rate = flow.total_completions / flow.total_starts
            if rate < 0.6:
                findings.append({"severity": "high" if rate < 0.3 else "medium", "source": "onboarding flow",
                                 "finding": f"'{flow.flow_name}' completes {rate:.0%} of {flow.total_starts} starts"})
            stats = (flow.meta_data or {}).get("step_dropoff") or {}
            if stats:
                worst = max(stats.items(), key=lambda kv: kv[1])
                findings.append({"severity": "medium", "source": "onboarding flow",
                                 "finding": f"Most users leave '{flow.flow_name}' at step {worst[0]} ({worst[1]} drop-offs)"})
    tickets = (await db.execute(select(SupportTicket).where(SupportTicket.workspace_id == workspace_id,
                                                            SupportTicket.created_at >= since))).scalars().all()
    related = [t for t in tickets if any(w in f"{t.subject} {t.description}".lower() for w in FRICTION_WORDS)]
    if related:
        themes: Dict[str, int] = {}
        for t in related:
            text = f"{t.subject} {t.description}".lower()
            for w in FRICTION_WORDS:
                if w in text:
                    themes[w] = themes.get(w, 0) + 1
        top = sorted(themes.items(), key=lambda kv: -kv[1])[:5]
        findings.append({"severity": "high" if len(related) >= 5 else "medium", "source": "support tickets",
                         "finding": f"{len(related)} ticket(s) in {days} days about getting started; most mention "
                                    + ", ".join(f"'{w}' ({n})" for w, n in top),
                         "tickets": [t.ticket_number for t in related[:10]]})
    for kpi in await company_ops.kpi_dashboard(db, workspace_id):
        if "activ" in kpi["name"].lower() and kpi["target_met"] is False:
            findings.append({"severity": "high", "source": "KPI",
                             "finding": f"{kpi['name']} is {kpi['value']:g} against target {kpi['target']:g}"})
    ws = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one()
    open_items = [i["title"] for i in (ws.config or {}).get("launch_checklist") or [] if i.get("status") not in ("done", "completed")]
    if open_items:
        findings.append({"severity": "low", "source": "launch checklist",
                         "finding": f"{len(open_items)} launch item(s) still open: {', '.join(open_items[:5])}"})
    findings.sort(key=lambda f: {"high": 0, "medium": 1, "low": 2}[f["severity"]])
    return {"period_days": days, "flows": [flow_view(f) for f in flows], "tickets_considered": len(tickets),
            "findings": findings,
            "measured": bool(flows or tickets),
            "next_step": ("Fix the highest finding first and measure again" if findings else
                          "No friction measured yet: record onboarding starts and completions, or support tickets")}


async def update_onboarding_copy(db: AsyncSession, workspace_id: UUID, flow_id: Any, *, step: Optional[int],
                                 title: Optional[str], copy: Optional[str], description: Optional[str]) -> OnboardingFlow:
    flow = (await db.execute(select(OnboardingFlow).where(OnboardingFlow.id == UUID(str(flow_id)),
                                                          OnboardingFlow.workspace_id == workspace_id))).scalar_one_or_none()
    if flow is None:
        raise LookupError("Onboarding flow not found in this workspace")
    meta = dict(flow.meta_data or {})
    meta["history"] = list(meta.get("history", [])) + [{"version": flow.version, "steps": flow.steps,
                                                         "description": flow.description, "at": _now().isoformat()}][-20:]
    steps = [dict(s) for s in flow.steps or []]
    if step is not None:
        match = next((s for s in steps if int(s.get("order", 0)) == int(step)), None)
        if match is None:
            raise ValueError(f"Step {step} does not exist (the flow has {len(steps)})")
        if title:
            match["title"] = title[:200]
        if copy is not None:
            match["copy"] = copy
    if description:
        flow.description = description
    flow.steps = steps
    flow.version = int(flow.version or 1) + 1
    flow.meta_data = meta
    flow.updated_at = _now()
    await db.flush()
    return flow


async def update_knowledge_base(db: AsyncSession, workspace_id: UUID, *, title: str, body: str,
                                article_id: Optional[str], author: Optional[UUID], publish: bool = False) -> ContentItem:
    row = None
    if article_id:
        row = (await db.execute(select(ContentItem).where(ContentItem.id == UUID(str(article_id)),
                                                          ContentItem.workspace_id == workspace_id))).scalar_one_or_none()
        if row is None:
            raise LookupError("Knowledge base article not found")
    else:
        row = (await db.execute(select(ContentItem).where(ContentItem.workspace_id == workspace_id,
                                                          ContentItem.content_type == "help_article",
                                                          ContentItem.title == title))).scalar_one_or_none()
    now = _now()
    if row is None:
        row = ContentItem(id=uuid4(), workspace_id=workspace_id, title=title[:500], content_type="help_article",
                          category="knowledge_base", slug=f"kb-{re.sub(r'[^a-z0-9]+', '-', title.lower())[:80]}-{uuid4().hex[:6]}",
                          content_body=body, content_format="markdown", excerpt=body[:300],
                          status="published" if publish else "draft", is_published=False, author_id=author,
                          author_name="JARV", tags=["knowledge_base"], meta_data={"version": 1, "history": []},
                          created_at=now, updated_at=now)
        db.add(row)
    else:
        meta = row.meta_data or {}
        history = list(meta.get("history", [])) + [{"version": meta.get("version", 1), "title": row.title,
                                                     "body": row.content_body, "at": now.isoformat()}]
        row.title, row.content_body, row.excerpt = title[:500], body, body[:300]
        row.content_type = "help_article"
        if publish:
            row.status = "published"
        row.meta_data = {**meta, "version": int(meta.get("version", 1)) + 1, "history": history[-20:]}
        row.updated_at = now
    await db.flush()
    return row
