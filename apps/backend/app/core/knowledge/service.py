"""Durable ingestion, versioning, and retrieval for specialist knowledge."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.registry import get_registry
from app.models.agent_knowledge import AgentKnowledge


_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,}")


class KnowledgeService:
    """Manage immutable knowledge versions and active retrieval records."""

    @staticmethod
    def _validate_entry(entry: Dict[str, Any]) -> None:
        required = (
            "agent_name", "knowledge_key", "title", "content", "keywords",
            "url", "source_title", "publisher",
        )
        missing = [name for name in required if not entry.get(name)]
        if missing:
            raise ValueError(f"Knowledge entry is missing fields: {', '.join(missing)}")
        if not get_registry().is_implemented(entry["agent_name"]):
            raise ValueError(f"Unknown or unimplemented agent: {entry['agent_name']}")
        parsed = urlparse(entry["url"])
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Knowledge sources must use an absolute HTTPS URL")
        if not isinstance(entry["keywords"], list) or not entry["keywords"]:
            raise ValueError("Knowledge entries require searchable keywords")

    @staticmethod
    def _digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def ingest(
        self,
        db: AsyncSession,
        entries: Iterable[Dict[str, Any]],
        *,
        verified_at: Optional[datetime] = None,
    ) -> Dict[str, int]:
        """Install or advance verified knowledge versions idempotently."""
        now = verified_at or datetime.now(timezone.utc)
        inserted = updated = unchanged = 0
        seen = set()
        for entry in entries:
            self._validate_entry(entry)
            identity = (entry["agent_name"], entry["knowledge_key"])
            if identity in seen:
                raise ValueError(f"Duplicate knowledge entry for {identity}")
            seen.add(identity)
            digest = self._digest(entry["content"])
            current = (await db.execute(select(AgentKnowledge).where(
                AgentKnowledge.agent_name == identity[0],
                AgentKnowledge.knowledge_key == identity[1],
                AgentKnowledge.is_active.is_(True),
            ).order_by(AgentKnowledge.version.desc()).limit(1))).scalar_one_or_none()
            same_record = current is not None and all((
                current.content_sha256 == digest,
                current.title == entry["title"],
                current.keywords == entry["keywords"],
                current.source_url == entry["url"],
                current.source_title == entry["source_title"],
                current.source_publisher == entry["publisher"],
                current.source_license == entry.get("license"),
                current.source_author == entry.get("author"),
                current.source_author_url == entry.get("author_url"),
            ))
            if same_record:
                unchanged += 1
                continue
            if current is not None:
                current.is_active = False
                version = current.version + 1
                previous_id = current.id
                updated += 1
            else:
                version = 1
                previous_id = None
                inserted += 1
            db.add(AgentKnowledge(
                agent_name=entry["agent_name"], knowledge_key=entry["knowledge_key"],
                title=entry["title"], content=entry["content"],
                keywords=entry["keywords"], source_url=entry["url"],
                source_title=entry["source_title"],
                source_publisher=entry["publisher"],
                source_license=entry.get("license"),
                source_author=entry.get("author"),
                source_author_url=entry.get("author_url"),
                verified_at=now, content_sha256=digest, version=version,
                is_active=True, previous_version_id=previous_id,
            ))
        await db.flush()
        return {"inserted": inserted, "updated": updated, "unchanged": unchanged}

    async def revise(
        self,
        db: AsyncSession,
        *,
        agent_name: str,
        knowledge_key: str,
        title: str,
        content: str,
        keywords: List[str],
        source_url: str,
        source_title: str,
        source_publisher: str,
        verified_at: datetime,
        source_license: Optional[str] = None,
        source_author: Optional[str] = None,
        source_author_url: Optional[str] = None,
    ) -> AgentKnowledge:
        """Create a new explicitly source-verified version of one brief."""
        entry = {
            "agent_name": agent_name, "knowledge_key": knowledge_key,
            "title": title, "content": content, "keywords": keywords,
            "url": source_url, "source_title": source_title,
            "publisher": source_publisher,
            "license": source_license, "author": source_author,
            "author_url": source_author_url,
        }
        self._validate_entry(entry)
        if not source_title.strip() or not content.strip():
            raise ValueError("Updated knowledge requires source title and content")
        current = (await db.execute(select(AgentKnowledge).where(
            AgentKnowledge.agent_name == agent_name,
            AgentKnowledge.knowledge_key == knowledge_key,
            AgentKnowledge.is_active.is_(True),
        ).order_by(AgentKnowledge.version.desc()).limit(1))).scalar_one_or_none()
        digest = self._digest(content)
        if current is not None and current.content_sha256 == digest:
            raise ValueError("Updated content is identical to the active version")
        if current is not None:
            current.is_active = False
            version = current.version + 1
            previous_id = current.id
        else:
            version = 1
            previous_id = None
        revised = AgentKnowledge(
            agent_name=agent_name, knowledge_key=knowledge_key, title=title,
            content=content, keywords=keywords, source_url=source_url,
            source_title=source_title, source_publisher=source_publisher,
            source_license=source_license, source_author=source_author,
            source_author_url=source_author_url,
            verified_at=verified_at, content_sha256=digest, version=version,
            is_active=True, previous_version_id=previous_id,
        )
        db.add(revised)
        await db.flush()
        return revised

    async def retrieve(
        self,
        db: AsyncSession,
        *,
        agent_name: str,
        query: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """Rank active source-verified briefs for one agent and task."""
        if not get_registry().is_implemented(agent_name):
            raise ValueError(f"Unknown or unimplemented agent: {agent_name}")
        if not query.strip():
            return []
        rows = (await db.execute(select(AgentKnowledge).where(
            AgentKnowledge.agent_name == agent_name,
            AgentKnowledge.is_active.is_(True),
        ).order_by(AgentKnowledge.knowledge_key, AgentKnowledge.version.desc()))).scalars().all()
        query_terms = set(_WORD_RE.findall(query.lower()))
        ranked = []
        for row in rows:
            searchable = " ".join([
                row.title, row.content, " ".join(row.keywords),
                row.source_title, row.source_publisher,
            ]).lower()
            terms = set(_WORD_RE.findall(searchable))
            overlap = len(query_terms & terms)
            phrase_bonus = 2 if query.lower().strip() in searchable else 0
            score = (overlap + phrase_bonus) / max(len(query_terms), 1)
            ranked.append((score, row))
        ranked.sort(key=lambda pair: (pair[0], pair[1].version), reverse=True)
        return [{
            "id": str(row.id), "agent_name": row.agent_name,
            "knowledge_key": row.knowledge_key, "title": row.title,
            "content": row.content, "keywords": list(row.keywords),
            "source_url": row.source_url, "source_title": row.source_title,
            "source_publisher": row.source_publisher,
            "source_license": row.source_license,
            "source_author": row.source_author,
            "source_author_url": row.source_author_url,
            "verified_at": row.verified_at.isoformat(),
            "content_sha256": row.content_sha256, "version": row.version,
            "relevance_score": score,
        } for score, row in ranked[:limit]]

    async def list_versions(
        self,
        db: AsyncSession,
        *,
        agent_name: str,
        knowledge_key: str,
    ) -> List[AgentKnowledge]:
        """Return the complete version history for a specialist brief."""
        return list((await db.execute(select(AgentKnowledge).where(
            AgentKnowledge.agent_name == agent_name,
            AgentKnowledge.knowledge_key == knowledge_key,
        ).order_by(AgentKnowledge.version))).scalars().all())


knowledge_service = KnowledgeService()