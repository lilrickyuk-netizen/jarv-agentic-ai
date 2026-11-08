"""
JAI knows who it is: Jay's personality in the voice and the Command Center's written replies, and JAI.md (its own
design and architecture) summarised in every reply and stored as knowledge for every agent.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import identity
from app.core.voice import live
from tests.conftest import AsyncTestingSessionLocal


def test_jai_has_its_design_document_and_a_one_paragraph_account_of_itself():
    text = identity.DOCUMENT.read_text(encoding="utf-8")
    for heading in ("## How a mission runs", "## The engineering sandbox", "## Skills", "## Memory and knowledge",
                    "## Authority and safety", "## What needs Richard"):
        assert heading in text
    about = identity.summary()
    assert "31 specialist agents" in about and "boundary operator" in about and "\n" not in about


def test_jay_is_dry_witted_in_the_voice_and_in_writing():
    assert "bone-dry" in identity.PERSONA and "never 'sir'" in identity.PERSONA
    written = identity.written_system()
    assert identity.PERSONA in written and "Command Center" in written and identity.summary() in written
    spoken = live.spoken_instructions([], brain=True)
    assert "bone-dry" in spoken and "WHAT YOU ARE" in spoken and "31 specialist agents" in spoken


def test_every_agent_can_find_jais_design_in_the_knowledge_library():
    from app.core.knowledge.documentation import ALL_AGENTS, catalogue

    entry = next(e for e in catalogue() if e["url"] == identity.SOURCE_URL)
    assert set(entry["agents"]) == set(ALL_AGENTS) and entry["licence_class"] == "store"
    assert entry["local_path"] == "jai:identity/JAI.md"


@pytest.mark.integration
def test_jais_design_is_stored_and_found_by_search():
    from app.core.knowledge.ingest import KnowledgeIngestor
    from app.core.knowledge.search import search_passages

    async def run():
        async with AsyncTestingSessionLocal() as db:
            if db.get_bind().dialect.name != "postgresql":
                return None
            results = await KnowledgeIngestor().install(db, identity.catalogue_entries(), agents=["sales"])
            hits = await search_passages(db, "parallel waves specialists integration engineer Verifier",
                                         agents=["sales"])
            return results, hits

    out = asyncio.run(run())
    if out is None:
        pytest.skip("passage search needs PostgreSQL")
    results, hits = out
    assert results[0]["status"] in ("updated", "unchanged") and results[0]["passages"] >= 5
    assert hits and hits[0]["url"] == identity.SOURCE_URL
