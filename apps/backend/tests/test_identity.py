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


def test_a_question_about_jai_itself_is_answered_from_its_design_document_not_a_mission():
    # Richard's own words by voice on 8 November, which started a mission instead of an answer.
    for question in ("Do you know what upgrades you've had in the last 72 hours?", "What capabilities you've got.",
                     "What are you?", "What skill packs do you have?", "How do you work?"):
        assert identity.asks_about_me(question), question
    for work in ("Carry on building MYCO Phase 0", "Use your BRAG Slim skill to make a Plexecute video",
                 "How is the mission going?", "Make the Plexecute launch video with your BRAG Slim skill. " * 10):
        assert not identity.asks_about_me(work), work
    whole = identity.capabilities()
    assert "134 skills" in whole and "Six pinned" in whole and "## Honest limits" in whole
    spoken = live.spoken_instructions([], brain=True)
    assert "what_i_am" in spoken and "A question is never a mission" in spoken
    start = next(t for t in live.TOOLS if t["name"] == "start_mission")
    assert "never for a question about JAI itself" in start["description"]


def test_a_written_question_about_jai_gets_the_whole_document(monkeypatch):
    from app.core.command.service import CommandService

    seen = {}

    class Router:
        async def complete(self, request):
            seen["system"] = request.system

            class Response:
                content, usage = "Six skill packs, boss.", {"total_tokens": 1}
            return Response()

    monkeypatch.setattr("app.core.command.service.get_router", lambda: Router())
    service = CommandService()
    asyncio.run(service._run_answer("What capabilities have you got?", {}, [], []))
    assert "HE IS ASKING ABOUT YOU" in seen["system"] and "134 skills" in seen["system"]
    asyncio.run(service._run_answer("How is MYCO going?", {}, [], []))
    assert "HE IS ASKING ABOUT YOU" not in seen["system"]


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
