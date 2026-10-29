"""Repair 13 refresh: specialist knowledge that matches how JARV now works.

The infrastructure, rollback, growth and creation briefs described tools JARV
does not use (Kubernetes rollouts, Google Analytics, Unsplash hotlinking); they
now come from the Compose production guide, release-rollback practice,
Plausible's Stats API and the Creative Commons licence elements. Updating the
catalogue versions the briefs in place. The Plausible adapter moved to Stats
API v2, and no-derivatives licences are recognised.
"""
import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from app.core.assets import library
from app.core.business import revenue as revenue_module
from app.core.business.revenue import revenue_service
from app.core.config import settings
from app.core.knowledge.catalog import specialist_knowledge
from app.core.knowledge.service import knowledge_service
from app.models.agent_knowledge import AgentKnowledge
from tests.conftest import AsyncTestingSessionLocal


def test_catalogue_covers_every_agent_with_current_sources():
    from app.core.agents.registry import get_registry

    entries = {e["agent_name"]: e for e in specialist_knowledge()}
    assert set(entries) == set(get_registry().REQUIRED_AGENTS)
    for entry in entries.values():
        assert entry["url"].startswith("https://") and entry["content"].strip() and entry["keywords"]
    assert entries["infrastructure"]["url"] == "https://docs.docker.com/compose/how-tos/production/"
    assert "kubernetes" not in entries["infrastructure"]["content"].lower()
    assert entries["rollback"]["source_title"].startswith("Reliable releases and rollbacks")
    assert "schema" in entries["rollback"]["content"]
    assert entries["growth"]["publisher"] == "Plausible Analytics" and "goals" in entries["growth"]["content"]
    assert entries["creation"]["publisher"] == "Creative Commons" and "ND" in entries["creation"]["content"]
    assert "unsplash" not in json.dumps(entries).lower()


@pytest.mark.integration
def test_updated_briefs_become_new_versions_and_are_retrieved():
    catalogue = specialist_knowledge()
    stale = [dict(e) for e in catalogue]
    for entry in stale:
        if entry["agent_name"] == "rollback":
            entry["content"] = "Rollback is available only while the Deployment revision history is retained."

    async def run():
        async with AsyncTestingSessionLocal() as db:
            await knowledge_service.ingest(db, stale)
            await db.flush()
            refreshed = await knowledge_service.ingest(db, catalogue)
            again = await knowledge_service.ingest(db, catalogue)
            await db.commit()
            rows = (await db.execute(select(AgentKnowledge).where(AgentKnowledge.agent_name == "rollback")
                                     .order_by(AgentKnowledge.version))).scalars().all()
            found = await knowledge_service.retrieve(db, agent_name="rollback",
                                                     query="roll back the release after a schema change")
            return refreshed, again, rows, found

    refreshed, again, rows, found = asyncio.run(run())
    assert refreshed["updated"] == 1 and refreshed["inserted"] == 0
    assert again == {"inserted": 0, "updated": 0, "unchanged": len(catalogue)}
    active = [r for r in rows if r.is_active]
    assert len(active) == 1 and "schema" in active[0].content
    assert active[0].previous_version_id == rows[-2].id and not rows[-2].is_active
    assert found and found[0]["version"] == active[0].version and "schema" in found[0]["content"]


def test_no_derivatives_licences_allow_unmodified_use_only():
    as_is = library.check_licence("CC BY-ND 4.0", commercial=True, modify=False)
    edited = library.check_licence("cc-by-nd", commercial=True, modify=True)
    nc_nd = library.check_licence("CC BY-NC-ND 4.0", commercial=True, modify=False)
    assert as_is["allowed"] is True and "use unmodified: no adaptations" in as_is["conditions"]
    assert as_is["modification_allowed"] is False
    assert edited["allowed"] is False and "adaptations" in edited["reason"]
    assert nc_nd["allowed"] is False and "commercial" in nc_nd["reason"]
    assert library.check_licence("CC BY 4.0", modify=True)["allowed"] is True


def test_plausible_analytics_uses_stats_api_v2(monkeypatch):
    monkeypatch.setattr(settings, "PLAUSIBLE_API_KEY", "plausible-test-key")
    monkeypatch.setattr(settings, "PLAUSIBLE_SITE_ID", "myco.example")
    monkeypatch.setattr(settings, "PLAUSIBLE_URL", "https://plausible.test")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request, body))
        if body.get("dimensions") == ["event:page"]:
            return httpx.Response(200, json={"results": [{"metrics": [420, 900], "dimensions": ["/pricing"]},
                                                         {"metrics": [300, 610], "dimensions": ["/"]}]})
        return httpx.Response(200, json={"results": [{"metrics": [1200, 1500, 4100, 41, 95], "dimensions": []}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(revenue_module.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    result = asyncio.run(revenue_service.analytics(None, None, 30))
    request, body = seen[0]
    assert request.method == "POST" and str(request.url) == "https://plausible.test/api/v2/query"
    assert request.headers["authorization"] == "Bearer plausible-test-key"
    assert body["site_id"] == "myco.example" and body["metrics"][0] == "visitors"
    assert isinstance(body["date_range"], list) and len(body["date_range"]) == 2
    assert result["source"] == "plausible"
    assert (result["visitors"], result["visits"], result["pageviews"], result["bounce_rate"]) == (1200, 1500, 4100, 41)
    assert result["top_pages"][0] == {"page": "/pricing", "visitors": 420, "pageviews": 900}
