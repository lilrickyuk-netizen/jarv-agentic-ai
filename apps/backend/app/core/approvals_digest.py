"""
JAI Backend - One daily digest of what waits for Richard, grouped by kind of action

Anthropic's usage data shows irreversible actions are under 1% of what agents do, so a boundary operator should see
a handful of real decisions a day, grouped and previewed, not a stream of interruptions. Every hard boundary still
pauses its own action the moment it is reached (nothing here approves anything); the digest gathers what is waiting
into one Live Operations Feed item each morning, and GET /api/approvals/digest returns the same at any time.

Classes: money (spend, payments, budgets), public (publishing, posting, deploying, pushing, sending), irreversible
(deleting, destroying, irreversible database changes), credentials (passwords, keys, sign-ins, security settings),
and other.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

CLASSES = ("money", "public", "irreversible", "credentials", "other")
_PATTERNS = (
    ("credentials", re.compile(r"(password|secret|credential|api key|private key|seed phrase|wallet|sign[- ]?in|"
                               r"log[- ]?in|security setting|2fa|token)", re.I)),
    ("money", re.compile(r"(spend|payment|pay |bank|budget|purchase|buy |subscription|invoice|card)", re.I)),
    ("irreversible", re.compile(r"(delete|destroy|drop |truncate|irreversible|wipe|remove production|rollback)",
                                re.I)),
    ("public", re.compile(r"(publish|post|deploy|release|push|send|email|outreach|tweet|launch|go live)", re.I)),
)
WAITING_TASK_STATES = ("blocked", "waiting_on_approval")


def classify(text: str) -> str:
    for name, pattern in _PATTERNS:
        if pattern.search(text or ""):
            return name
    return "other"


async def waiting(db: AsyncSession, owner: Optional[UUID] = None) -> List[Dict[str, Any]]:
    """Everything waiting for Richard: blocked mission actions and pending approval requests."""
    from app.models.approval import Approval
    from app.models.task import Task
    from app.models.workspace import Workspace

    items: List[Dict[str, Any]] = []
    query = select(Task, Workspace.name).join(Workspace, Workspace.id == Task.workspace_id).where(
        Task.status.in_(WAITING_TASK_STATES))
    if owner is not None:
        query = query.where(Workspace.owner_id == owner)
    for task, workspace in (await db.execute(query.order_by(Task.created_at).limit(200))).all():
        meta = task.meta_data if isinstance(task.meta_data, dict) else {}
        ctx = task.context if isinstance(task.context, dict) else {}
        reason = str(meta.get("blocked_reason") or ctx.get("safety_reason") or "")
        kind = str(meta.get("boundary_type") or "")
        items.append({"kind": "mission action", "id": str(task.id), "workspace": workspace,
                      "what": " ".join(str(task.title or task.description or "").split())[:200],
                      "why": reason[:300], "class": classify(f"{kind} {reason} {task.title or ''}"),
                      "since": task.created_at.isoformat() if task.created_at else None,
                      "where": "/dashboard/approvals"})
    query = select(Approval).where(Approval.status == "pending")
    if owner is not None:
        query = query.where(Approval.user_id == owner)
    for approval in (await db.execute(query.order_by(Approval.created_at).limit(200))).scalars().all():
        text = f"{approval.approval_type} {approval.action_description}"
        items.append({"kind": "approval request", "id": str(approval.id), "workspace": None,
                      "what": " ".join(str(approval.action_description or "").split())[:200],
                      "why": str(approval.approval_type or ""), "class": classify(text),
                      "since": approval.created_at.isoformat() if approval.created_at else None,
                      "where": "/dashboard/approvals"})
    return items


def digest(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped = {name: [i for i in items if i["class"] == name] for name in CLASSES}
    lines = []
    for name in CLASSES:
        for item in grouped[name]:
            lines.append(f"[{name}] {item['what']}" + (f" — {item['why']}" if item["why"] else ""))
    return {"total": len(items), "by_class": {k: len(v) for k, v in grouped.items()}, "items": grouped,
            "summary": ("Nothing is waiting for you." if not items else
                        f"{len(items)} decision{'s' if len(items) != 1 else ''} waiting: "
                        + ", ".join(f"{len(v)} {k}" for k, v in grouped.items() if v) + "."),
            "lines": lines}


async def post(db: AsyncSession, workspace_id: UUID, owner: Optional[UUID] = None) -> Dict[str, Any]:
    """Build the digest and put it in the Live Operations Feed (only when something is waiting)."""
    from app.models.company_operations import LiveOperationsFeedItem

    result = digest(await waiting(db, owner))
    if result["total"]:
        now = datetime.now(timezone.utc)
        db.add(LiveOperationsFeedItem(
            id=uuid4(), workspace_id=workspace_id, item_type="approval_digest", severity="warning",
            title=f"Approvals digest: {result['summary']}", message="\n".join(result["lines"][:40]) or result["summary"],
            requires_action=True, created_at=now, updated_at=now))
        await db.flush()
    return result
