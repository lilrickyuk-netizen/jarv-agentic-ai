"""
JARV Backend - Customer support (persisted)

A local ticket inbox (SupportTicket rows; the conversation is kept on the
ticket), fed by the API, the email inbox (IMAP, when configured) or tools.
Tickets are categorised and prioritised by rules (the model refines them when
one is configured); bugs with high severity are escalated to the debugging
agent as a task. Replies are drafted from the FAQ and the workspace's facts.
A reply is only sent when a workspace rule allows that category at the
draft's confidence, or Richard approves it, and only through the configured
mail adapter, to that one customer.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import redact_text
from app.models.business import SupportTicket
from app.models.content import CommunityItem, ContentItem
from app.models.task import Task
from app.models.workspace_rules import WorkspaceRule

CATEGORY_WORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("billing", ("invoice", "charge", "charged", "refund", "payment", "billing", "subscription", "card", "price")),
    ("bug", ("error", "crash", "crashes", "broken", "bug", "exception", "not working", "doesn't work", "fails",
             "failed", "500", "stack trace", "freeze")),
    ("account", ("login", "log in", "sign in", "password", "account", "2fa", "verification code", "locked out",
                 "sign up", "signup")),
    ("feature_request", ("feature", "would be great", "could you add", "please add", "request", "wish", "suggestion")),
    ("question", ("how do", "how to", "how can", "can i", "is it possible", "where is", "what is", "?")),
)
URGENT_WORDS = ("urgent", "asap", "immediately", "outage", "down", "data loss", "lost data", "security", "breach",
                "can't access", "cannot access", "production")
POSITIVE = ("love", "great", "thanks", "thank you", "awesome", "excellent", "helpful", "amazing", "perfect")
NEGATIVE = ("hate", "terrible", "awful", "angry", "frustrated", "disappointed", "useless", "worst", "annoying", "slow")
_WORD = re.compile(r"[a-z][a-z0-9'-]{3,}")
_STOP = {"that", "this", "with", "have", "from", "your", "when", "what", "there", "they", "would", "could", "about",
         "just", "into", "will", "been", "were", "them", "then", "than", "which", "also", "only", "please", "thanks"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def categorise_text(subject: str, body: str) -> Dict[str, Any]:
    text = f"{subject} {body}".lower()
    scores = {cat: [w for w in words if w in text] for cat, words in CATEGORY_WORDS}
    category = max(scores, key=lambda c: (len(scores[c]), -[k for k, _ in CATEGORY_WORDS].index(c)))
    if not scores[category]:
        category = "other"
    urgent = [w for w in URGENT_WORDS if w in text]
    severity = "critical" if any(w in text for w in ("data loss", "lost data", "breach", "security")) else \
        "high" if urgent else "medium" if category in ("bug", "billing", "account") else "low"
    priority = {"critical": "urgent", "high": "high", "medium": "medium", "low": "low"}[severity]
    return {"category": category, "priority": priority, "severity": severity,
            "matched": scores.get(category, []) + urgent}


def sentiment(text: str) -> str:
    low = text.lower()
    pos, neg = sum(w in low for w in POSITIVE), sum(w in low for w in NEGATIVE)
    return "positive" if pos > neg else "negative" if neg > pos else "neutral"


def terms(texts: Sequence[str], limit: int = 12) -> List[Tuple[str, int]]:
    counts = Counter(w for t in texts for w in _WORD.findall(t.lower()) if w not in _STOP)
    return counts.most_common(limit)


def view(t: SupportTicket) -> Dict[str, Any]:
    meta = t.meta_data or {}
    return {"id": str(t.id), "number": t.ticket_number, "subject": t.subject, "description": t.description,
            "customer": t.customer_name, "email": t.customer_email, "category": t.category, "priority": t.priority,
            "severity": t.severity, "status": t.status, "messages": meta.get("messages", []),
            "last_draft": meta.get("last_draft"), "escalation_task_id": meta.get("escalation_task_id"),
            "source": meta.get("source"), "created_at": t.created_at.isoformat() if t.created_at else None}


class SupportService:
    async def _ticket(self, db: AsyncSession, workspace_id: UUID, ticket_id: Any) -> SupportTicket:
        try:
            key = ticket_id if isinstance(ticket_id, UUID) else UUID(str(ticket_id))
            clause = SupportTicket.id == key
        except (TypeError, ValueError):
            clause = SupportTicket.ticket_number == str(ticket_id)
        row = (await db.execute(select(SupportTicket).where(clause, SupportTicket.workspace_id == workspace_id))
               ).scalar_one_or_none()
        if row is None:
            raise LookupError("Ticket not found in this workspace")
        return row

    async def create_ticket(self, db: AsyncSession, workspace_id: UUID, *, subject: str, description: str,
                            customer_email: Optional[str] = None, customer_name: Optional[str] = None,
                            category: Optional[str] = None, priority: Optional[str] = None, source: str = "manual",
                            external_id: Optional[str] = None) -> SupportTicket:
        if external_id:
            existing = (await db.execute(select(SupportTicket).where(SupportTicket.workspace_id == workspace_id))
                        ).scalars().all()
            for row in existing:
                if (row.meta_data or {}).get("external_id") == external_id:
                    return row
        count = (await db.execute(select(func.count()).select_from(SupportTicket).where(
            SupportTicket.workspace_id == workspace_id))).scalar_one()
        auto = categorise_text(subject, description)
        now = _now()
        ticket = SupportTicket(
            id=uuid4(), workspace_id=workspace_id, ticket_number=f"{workspace_id.hex[:6].upper()}-{count + 1:05d}",
            subject=redact_text(subject)[:500], description=redact_text(description), customer_email=customer_email,
            customer_name=customer_name, category=category or auto["category"], priority=priority or auto["priority"],
            severity=auto["severity"], status="new", tags=[auto["category"]],
            meta_data={"source": source, "external_id": external_id, "sentiment": sentiment(description),
                       "categorised_by": "caller" if category else f"rules ({', '.join(auto['matched']) or 'no match'})",
                       "messages": [{"kind": "inbound", "from": customer_email or customer_name or "customer",
                                     "at": now.isoformat(), "body": redact_text(description)[:20000]}]},
            created_at=now, updated_at=now)
        db.add(ticket)
        await db.flush()
        await self._escalate(db, workspace_id, ticket)
        return ticket

    async def categorise(self, db: AsyncSession, workspace_id: UUID, ticket_id: Any,
                         category: Optional[str] = None, priority: Optional[str] = None) -> SupportTicket:
        ticket = await self._ticket(db, workspace_id, ticket_id)
        auto = categorise_text(ticket.subject, ticket.description)
        ticket.category = category or auto["category"]
        ticket.priority = priority or auto["priority"]
        ticket.severity = auto["severity"]
        ticket.meta_data = {**(ticket.meta_data or {}), "categorised_by": "caller" if category else
                            f"rules ({', '.join(auto['matched']) or 'no match'})"}
        ticket.updated_at = _now()
        await db.flush()
        await self._escalate(db, workspace_id, ticket)
        return ticket

    async def _escalate(self, db: AsyncSession, workspace_id: UUID, ticket: SupportTicket) -> None:
        """A high-severity bug becomes a pending task for the debugging agent (once)."""
        meta = ticket.meta_data or {}
        if ticket.category != "bug" or ticket.severity not in ("high", "critical") or meta.get("escalation_task_id"):
            return
        now = _now()
        task = Task(id=uuid4(), title=f"Investigate support ticket {ticket.ticket_number}: {ticket.subject}"[:500],
                    description=ticket.description[:4000], task_type="bug_report", workspace_id=workspace_id,
                    status="pending", priority=8 if ticket.severity == "critical" else 7,
                    context={"agent": "debugging_agent", "support_ticket_id": str(ticket.id)},
                    meta_data={"source": "support escalation"}, created_at=now, updated_at=now)
        db.add(task)
        ticket.meta_data = {**meta, "escalation_task_id": str(task.id)}
        ticket.status = "escalated"
        await db.flush()

    async def list(self, db: AsyncSession, workspace_id: UUID, *, status: Optional[str] = None,
                   category: Optional[str] = None, limit: int = 50) -> List[SupportTicket]:
        query = select(SupportTicket).where(SupportTicket.workspace_id == workspace_id)
        if status:
            query = query.where(SupportTicket.status == status)
        if category:
            query = query.where(SupportTicket.category == category)
        return list((await db.execute(query.order_by(SupportTicket.created_at.desc()).limit(limit))).scalars().all())

    async def sync_inbox(self, db: AsyncSession, workspace_id: UUID, limit: int = 50) -> Dict[str, Any]:
        from app.core.business import mailer

        messages = await mailer.read_unseen(limit)
        created = []
        for m in messages:
            ticket = await self.create_ticket(db, workspace_id, subject=m["subject"], description=m["body"] or m["subject"],
                                              customer_email=m["from_email"], customer_name=m["from_name"],
                                              source="email", external_id=m["message_id"] or None)
            created.append(ticket.ticket_number)
        return {"read": len(messages), "tickets": created}

    async def faq_matches(self, db: AsyncSession, workspace_id: UUID, text: str, limit: int = 3
                          ) -> List[Tuple[float, ContentItem]]:
        words = {w for w in _WORD.findall(text.lower()) if w not in _STOP}
        rows = (await db.execute(select(ContentItem).where(ContentItem.workspace_id == workspace_id,
                                                           ContentItem.content_type.in_(("faq", "help_article"))))
                ).scalars().all()
        scored = []
        for row in rows:
            q_words = {w for w in _WORD.findall(f"{row.title} {row.content_body[:400]}".lower()) if w not in _STOP}
            if q_words and words:
                score = len(words & q_words) / len(q_words | set(list(words)[:30]))
                if score > 0:
                    scored.append((round(min(1.0, score * 2.5), 2), row))
        return sorted(scored, key=lambda s: -s[0])[:limit]

    async def draft_reply(self, db: AsyncSession, workspace_id: UUID, ticket_id: Any, *, tone: str = "friendly",
                          model: Optional[str] = None) -> Dict[str, Any]:
        from app.core.agents.specialists import _helpers as helpers
        from app.core.business.facts import gather

        ticket = await self._ticket(db, workspace_id, ticket_id)
        matches = await self.faq_matches(db, workspace_id, f"{ticket.subject} {ticket.description}")
        facts = await gather(db, workspace_id)
        name = (ticket.customer_name or "there").split(" ")[0]
        body, by = None, "faq"
        if helpers.provider_configured():
            reply = await helpers.llm_complete(
                model or "claude-sonnet-4-6",
                f"Customer ticket ({ticket.category}, {ticket.priority}):\nSubject: {ticket.subject}\n{ticket.description}\n\n"
                f"Relevant FAQ:\n" + "\n".join(f"Q: {r.title}\nA: {r.content_body}" for _s, r in matches)
                + f"\n\nProduct facts:\n{facts.summary(3000)}\n\nWrite a {tone} reply from the {facts.product} team. "
                  "Answer only from the FAQ and facts; if they do not answer it, say we are checking and will reply. "
                  "Never promise refunds, dates or features. Plain text.",
                system="You write accurate, kind customer support replies.", temperature=0.3, max_tokens=700)
            if reply and reply.get("text", "").strip():
                body, by = reply["text"].strip(), f"model:{reply.get('provider_used')}"
        if body is None:
            if matches:
                answer = matches[0][1].content_body
            elif ticket.category == "bug":
                answer = ("Thanks for reporting this. I've passed it to our engineers with the details you sent, "
                          "and we'll update you as soon as we know more.")
            elif ticket.category == "feature_request":
                answer = "Thanks for the suggestion. I've added it to our product feedback so the team can review it."
            else:
                answer = "Thanks for getting in touch. We're looking into this and will reply with an answer shortly."
            body = f"Hi {name},\n\n{answer}\n\nBest regards,\nThe {facts.product} team"
        confidence = matches[0][0] if matches else (0.5 if ticket.category in ("bug", "feature_request") else 0.3)
        draft = {"kind": "draft", "at": _now().isoformat(), "body": redact_text(body), "generated_by": by,
                 "confidence": confidence, "faq_ids": [str(r.id) for _s, r in matches]}
        meta = ticket.meta_data or {}
        ticket.meta_data = {**meta, "messages": list(meta.get("messages", [])) + [draft], "last_draft": draft}
        if ticket.status == "new":
            ticket.status = "open"
        ticket.updated_at = _now()
        await db.flush()
        return draft

    async def reply_rule(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, Any]:
        row = (await db.execute(select(WorkspaceRule).where(WorkspaceRule.workspace_id == workspace_id,
                                                            WorkspaceRule.rule_type == "support_reply",
                                                            WorkspaceRule.is_active.is_(True)))).scalars().first()
        content = (row.rule_content if row else {}) or {}
        return {"auto_send_categories": list(content.get("auto_send_categories") or []),
                "min_confidence": float(content.get("min_confidence") or 0.8), "rule": row.rule_name if row else None}

    async def send_reply(self, db: AsyncSession, workspace_id: UUID, ticket_id: Any, *, approved: bool,
                         body: Optional[str] = None) -> Dict[str, Any]:
        from app.core.business import mailer

        ticket = await self._ticket(db, workspace_id, ticket_id)
        draft = (ticket.meta_data or {}).get("last_draft")
        text = body or (draft or {}).get("body")
        if not text:
            raise ValueError("There is no drafted reply to send; draft one first")
        if not ticket.customer_email:
            raise ValueError("The ticket has no customer email address")
        rule = await self.reply_rule(db, workspace_id)
        confidence = float((draft or {}).get("confidence") or 0) if body is None else 0.0
        allowed = ticket.category in rule["auto_send_categories"] and confidence >= rule["min_confidence"]
        if not (allowed or approved):
            raise PermissionError(
                f"No reply rule allows sending a {ticket.category} reply at confidence {confidence:.2f} "
                f"(rule: {rule['rule'] or 'none'}); Richard must approve this reply")
        sent = await mailer.send_email(ticket.customer_email, f"Re: {ticket.subject} [{ticket.ticket_number}]", text,
                                       (ticket.meta_data or {}).get("external_id"))
        now = _now()
        meta = ticket.meta_data or {}
        ticket.meta_data = {**meta, "messages": list(meta.get("messages", [])) + [
            {"kind": "sent", "at": now.isoformat(), "body": text, "to": sent["to"], "message_id": sent["message_id"],
             "authorised_by": "rule" if allowed else "richard"}]}
        ticket.first_response_at = ticket.first_response_at or now
        ticket.status = "waiting_customer"
        ticket.updated_at = now
        await db.flush()
        return {**sent, "authorised_by": "rule" if allowed else "richard"}

    async def update_faq(self, db: AsyncSession, workspace_id: UUID, *, question: str, answer: str,
                         faq_id: Optional[str] = None, author: Optional[UUID] = None) -> ContentItem:
        row = None
        if faq_id:
            row = (await db.execute(select(ContentItem).where(ContentItem.id == UUID(str(faq_id)),
                                                              ContentItem.workspace_id == workspace_id,
                                                              ContentItem.content_type == "faq"))).scalar_one_or_none()
            if row is None:
                raise LookupError("FAQ entry not found")
        else:
            row = (await db.execute(select(ContentItem).where(ContentItem.workspace_id == workspace_id,
                                                              ContentItem.content_type == "faq",
                                                              ContentItem.title == question))).scalar_one_or_none()
        now = _now()
        if row is None:
            row = ContentItem(id=uuid4(), workspace_id=workspace_id, title=question[:500], content_type="faq",
                              category="support", slug=f"faq-{re.sub(r'[^a-z0-9]+', '-', question.lower())[:80]}-{uuid4().hex[:6]}",
                              content_body=answer, content_format="markdown", status="published", is_published=False,
                              author_id=author, author_name="JARV", tags=["faq"], meta_data={"version": 1, "history": []},
                              created_at=now, updated_at=now)
            db.add(row)
        else:
            meta = row.meta_data or {}
            history = list(meta.get("history", [])) + [{"version": meta.get("version", 1), "question": row.title,
                                                         "answer": row.content_body, "at": now.isoformat()}]
            row.title, row.content_body = question[:500], answer
            row.meta_data = {**meta, "version": int(meta.get("version", 1)) + 1, "history": history[-20:]}
            row.updated_at = now
        await db.flush()
        return row

    async def feedback_summary(self, db: AsyncSession, workspace_id: UUID, days: int = 30,
                               include_community: bool = True) -> Dict[str, Any]:
        since = _now() - timedelta(days=days)
        tickets = (await db.execute(select(SupportTicket).where(SupportTicket.workspace_id == workspace_id,
                                                                SupportTicket.created_at >= since))).scalars().all()
        items = []
        if include_community:
            items = (await db.execute(select(CommunityItem).where(
                CommunityItem.workspace_id == workspace_id, CommunityItem.created_at >= since,
                CommunityItem.status != "draft"))).scalars().all()
        texts = [f"{t.subject} {t.description}" for t in tickets] + [f"{i.title} {i.content}" for i in items]
        return {
            "period_days": days, "tickets": len(tickets), "community_messages": len(items),
            "by_category": dict(Counter(t.category for t in tickets)),
            "by_status": dict(Counter(t.status for t in tickets)),
            "sentiment": dict(Counter(sentiment(t) for t in texts)),
            "top_terms": terms(texts),
            "bugs": [{"number": t.ticket_number, "subject": t.subject, "severity": t.severity}
                     for t in tickets if t.category == "bug"][:15],
            "feature_requests": [t.subject for t in tickets if t.category == "feature_request"][:15]
            + [i.title for i in items if categorise_text(i.title, i.content)["category"] == "feature_request"][:10],
            "unanswered": [t.ticket_number for t in tickets if t.status in ("new", "open", "escalated")][:20],
        }


support_service = SupportService()
