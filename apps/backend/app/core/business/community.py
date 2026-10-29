"""
JARV Backend - Community inbox and moderation (persisted)

Community messages (from the API, webhooks or tools) are CommunityItem rows
of type "message". Moderation follows the workspace's community_moderation
rule (banned words, link limit) plus built-in spam and abuse signals; it can
approve, flag for Richard, or hide an item, and records why. It never deletes
anything. Replies and announcements are drafts (see drafting.py): posting
publicly from Richard's accounts is a hard boundary.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import redact_text
from app.models.content import CommunityItem
from app.models.workspace_rules import WorkspaceRule

SPAM_WORDS = ("buy now", "free money", "crypto giveaway", "click here", "work from home", "earn $", "casino",
              "viagra", "loan offer", "dm me for", "guaranteed profit")
ABUSE_WORDS = ("idiot", "stupid", "kill yourself", "moron", "shut up")
_LINK = re.compile(r"https?://", re.I)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def view(item: CommunityItem) -> Dict[str, Any]:
    meta = item.meta_data or {}
    return {"id": str(item.id), "title": item.title, "type": item.item_type, "channel": item.category,
            "content": item.content, "author": item.author_name, "status": item.status, "is_moderated": item.is_moderated,
            "moderation_notes": item.moderation_notes, "reply_to": str(item.parent_item_id) if item.parent_item_id else None,
            "url": meta.get("url"), "created_at": item.created_at.isoformat() if item.created_at else None}


class CommunityService:
    async def item(self, db: AsyncSession, workspace_id: UUID, item_id: Any) -> CommunityItem:
        try:
            key = item_id if isinstance(item_id, UUID) else UUID(str(item_id))
        except (TypeError, ValueError):
            raise ValueError(f"'{item_id}' is not a valid id") from None
        row = (await db.execute(select(CommunityItem).where(CommunityItem.id == key,
                                                            CommunityItem.workspace_id == workspace_id))).scalar_one_or_none()
        if row is None:
            raise LookupError("Community item not found in this workspace")
        return row

    async def ingest(self, db: AsyncSession, workspace_id: UUID, owner: UUID, *, content: str, author_name: str,
                     channel: str = "forum", title: Optional[str] = None, url: Optional[str] = None,
                     external_id: Optional[str] = None) -> CommunityItem:
        now = _now()
        row = CommunityItem(
            id=uuid4(), workspace_id=workspace_id, title=(title or content[:80])[:500], item_type="message",
            category=channel[:100], content=redact_text(content), content_format="text", author_id=owner,
            author_name=author_name[:255], status="new", is_published=True, is_moderated=False, is_reply=False,
            tags=[channel], meta_data={"url": url, "external_id": external_id, "external_author": True},
            created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
        return row

    async def read(self, db: AsyncSession, workspace_id: UUID, *, status: Optional[str] = None,
                   channel: Optional[str] = None, limit: int = 50) -> List[CommunityItem]:
        query = select(CommunityItem).where(CommunityItem.workspace_id == workspace_id, CommunityItem.item_type == "message")
        if status:
            query = query.where(CommunityItem.status == status)
        if channel:
            query = query.where(CommunityItem.category == channel)
        return list((await db.execute(query.order_by(CommunityItem.created_at.desc()).limit(limit))).scalars().all())

    async def rules(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, Any]:
        row = (await db.execute(select(WorkspaceRule).where(WorkspaceRule.workspace_id == workspace_id,
                                                            WorkspaceRule.rule_type == "community_moderation",
                                                            WorkspaceRule.is_active.is_(True)))).scalars().first()
        content = (row.rule_content if row else {}) or {}
        return {"banned_words": [w.lower() for w in content.get("banned_words") or []],
                "max_links": int(content.get("max_links") or 2), "rule": row.rule_name if row else None}

    async def moderate(self, db: AsyncSession, workspace_id: UUID, item_id: Any, moderator: UUID) -> Dict[str, Any]:
        item = await self.item(db, workspace_id, item_id)
        rules = await self.rules(db, workspace_id)
        text = f"{item.title} {item.content}".lower()
        reasons: List[str] = []
        banned = [w for w in rules["banned_words"] if w in text]
        if banned:
            reasons.append(f"banned words: {', '.join(banned)}")
        links = len(_LINK.findall(text))
        if links > rules["max_links"]:
            reasons.append(f"{links} links (limit {rules['max_links']})")
        spam = [w for w in SPAM_WORDS if w in text]
        if spam:
            reasons.append(f"spam signals: {', '.join(spam)}")
        abuse = [w for w in ABUSE_WORDS if w in text]
        if abuse:
            reasons.append(f"abusive language: {', '.join(abuse)}")
        letters = [c for c in item.content if c.isalpha()]
        if len(letters) > 30 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
            reasons.append("mostly capital letters")
        if banned or abuse or (spam and links):
            decision = "hidden"
        elif reasons:
            decision = "flagged"
        else:
            decision = "approved"
        item.status = decision
        item.is_published = decision == "approved"
        item.is_moderated, item.moderated_by, item.moderated_at = True, moderator, _now()
        item.moderation_notes = "; ".join(reasons) or "no rule matched"
        item.meta_data = {**(item.meta_data or {}), "moderation_rule": rules["rule"] or "built-in signals"}
        item.updated_at = _now()
        await db.flush()
        return {"item": view(item), "decision": decision, "reasons": reasons, "rule": rules["rule"]}


community_service = CommunityService()
