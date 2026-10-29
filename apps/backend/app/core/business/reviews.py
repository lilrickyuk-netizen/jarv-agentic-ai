"""
JARV Backend - App reviews

Reads the public App Store customer-review feed for an app (no credentials
needed), stores new reviews as community messages on the "app_store" channel
(once each), and summarises ratings, sentiment and recent low ratings. Google
Play has no public review feed; its reviews can be ingested through the
community messages API.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.business.community import community_service
from app.core.business.support import sentiment, terms
from app.core.config import settings
from app.models.content import CommunityItem


def feed_url(app_id: str, country: str) -> str:
    return (f"https://itunes.apple.com/{country}/rss/customerreviews/page=1/id={app_id}/"
            "sortby=mostrecent/json")


async def fetch_app_store(app_id: str, country: str) -> List[Dict[str, Any]]:
    if not app_id.isdigit():
        raise ValueError("The App Store app id is the number in the app's store URL (id123456789)")
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(feed_url(app_id, country))
    if response.status_code >= 400:
        raise RuntimeError(f"The App Store feed returned {response.status_code}")
    entries = ((response.json().get("feed") or {}).get("entry")) or []
    if isinstance(entries, dict):
        entries = [entries]
    reviews = []
    for e in entries:
        rating = (e.get("im:rating") or {}).get("label")
        if rating is None:
            continue
        reviews.append({"id": (e.get("id") or {}).get("label"), "author": ((e.get("author") or {}).get("name") or {}).get("label"),
                        "rating": int(rating), "title": (e.get("title") or {}).get("label", ""),
                        "content": (e.get("content") or {}).get("label", ""),
                        "version": (e.get("im:version") or {}).get("label"), "updated": (e.get("updated") or {}).get("label")})
    return reviews


async def check_reviews(db: AsyncSession, workspace_id: UUID, owner: UUID, *, app_store_id: Optional[str],
                        country: Optional[str] = None) -> Dict[str, Any]:
    fetched: List[Dict[str, Any]] = []
    new = 0
    if app_store_id:
        fetched = await fetch_app_store(app_store_id, (country or settings.APP_STORE_COUNTRY or "us").lower())
        existing = {(r.meta_data or {}).get("external_id") for r in (await db.execute(select(CommunityItem).where(
            CommunityItem.workspace_id == workspace_id, CommunityItem.category == "app_store"))).scalars().all()}
        for review in fetched:
            external = f"appstore:{review['id']}"
            if external in existing:
                continue
            item = await community_service.ingest(db, workspace_id, owner, content=review["content"],
                                                  author_name=review["author"] or "App Store user", channel="app_store",
                                                  title=f"{review['rating']}★ {review['title']}"[:500],
                                                  external_id=external)
            item.meta_data = {**(item.meta_data or {}), "rating": review["rating"], "version": review["version"]}
            new += 1
        await db.flush()
    stored = (await db.execute(select(CommunityItem).where(
        CommunityItem.workspace_id == workspace_id,
        CommunityItem.category.in_(("app_store", "google_play", "reviews"))))).scalars().all()
    ratings = [int((r.meta_data or {}).get("rating")) for r in stored if (r.meta_data or {}).get("rating") is not None]
    texts = [f"{r.title} {r.content}" for r in stored]
    low = [r for r in stored if ((r.meta_data or {}).get("rating") or 5) <= 2]
    return {"source": "app_store" if app_store_id else "stored reviews", "fetched": len(fetched), "new": new,
            "reviews": len(stored), "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "distribution": dict(sorted(Counter(ratings).items())), "sentiment": dict(Counter(sentiment(t) for t in texts)),
            "themes": terms([f"{r.title} {r.content}" for r in low] or texts, 8),
            "recent_low_ratings": [{"title": r.title, "content": r.content[:300], "author": r.author_name} for r in low[:10]],
            "notes": [] if app_store_id else ["Give app_store_id to read the App Store feed; Google Play reviews "
                                              "can be added through the community messages API (channel google_play)."]}
