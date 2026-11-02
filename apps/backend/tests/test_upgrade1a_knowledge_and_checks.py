"""
Upgrade 1a: the specialist agents' source documentation (ingestion, licence gate, versions, hybrid search, the
places it reaches the agents) and the Verifier's hard conformance checks.

The hard-check fixtures reproduce the five defects JARV's Verifier passed in MYCO Phase 0 (commit ce5582f):
Python 3.12.8 against a locked 3.14.7 with an ADR claiming 3.14.7, TypeScript and Vitest below the locked
versions, an ADR still "Open - blocking", a planning file calling the superseded design authoritative, and stray
scripts. Each is found; the corrected copy passes.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.knowledge.ingest import MAX_TOKENS, CHARS_PER_TOKEN, split_passages
from app.core.knowledge.search import fuse, render_passages
from app.core.verification.checks import (check_open_blockers, claimed_versions, pnpm_importers, run_hard_checks,
                                          Repo)
from tests.conftest import AsyncTestingSessionLocal

SPEC = """# MYCO spec

## 40.1 Runtime/platform

| Component | Locked baseline | Decision |
|---|---:|---|
| Node.js | 24.21.0 LTS | Use LTS |
| Python | 3.14.7 | Replaces older 3.13.15 baseline |
| Terraform | 1.16.3 | Do not use 1.17 beta |

## 40.2 Development/build

| Component | Locked baseline |
|---|---:|
| pnpm | 12.5.1 |
| TypeScript | 7.0.2 |
| Vitest | 5.0.1 |
"""

LOCK = """lockfileVersion: '9.0'

importers:

  .:
    devDependencies:
      typescript:
        specifier: {ts}
        version: {ts}

  apps/web:
    devDependencies:
      typescript:
        specifier: {ts}
        version: {ts}
      vitest:
        specifier: {vitest}
        version: {vitest}

packages:

  typescript@{ts}:
    resolution: {{integrity: sha512-x}}
"""


def _repo(root: Path, *, fixed: bool) -> Path:
    python = "3.14.7" if fixed else "3.12.8"
    ts, vitest = ("7.0.2", "5.0.1") if fixed else ("5.8.2", "3.0.8")
    files = {
        "MYCO_V3_SPEC.md": SPEC,
        "Myco_design.md": "# Old design\n\nSuperseded by MYCO_V3_SPEC.md.\n",
        ".python-version": f"{python}\n",
        ".nvmrc": "24.21.0\n",
        "pyproject.toml": f'[project]\nname = "myco"\nversion = "0.1.0"\nrequires-python = "=={python}"\n',
        "uv.lock": f'version = 1\nrevision = 3\nrequires-python = "=={python}"\n',
        "package.json": json.dumps({"name": "myco", "private": True, "packageManager": "pnpm@12.5.1",
                                    "scripts": {"verify": "python scripts/check_launch.py"},
                                    "devDependencies": {"typescript": ts}}),
        "pnpm-workspace.yaml": 'packages:\n  - "apps/*"\nminimumReleaseAge: 180\n',
        "pnpm-lock.yaml": LOCK.format(ts=ts, vitest=vitest),
        "apps/web/package.json": json.dumps({"name": "@myco/web", "private": True,
                                             "devDependencies": {"typescript": ts, "vitest": vitest}}),
        "infra/versions.tf": 'terraform {\n  required_version = "= 1.16.3"\n}\n',
        "scripts/check_launch.py": "print('checks')\n",
        "docs/adr/0001-template.md": "# ADR template\n\n- **Status:** Proposed | Accepted | Superseded\n",
        "docs/adr/0004-python.md": ("# ADR-0004\n\n- **Status:** Resolved\n\n## Decision\nThe root and agent "
                                    "project Python requirements and `.python-version` have been aligned to exact "
                                    "3.14.7, and `uv.lock` regenerated.\n"),
        "docs/adr/0006-digests.md": ("# ADR-0006\n\n- **Status:** "
                                     + ("Resolved — digests recorded in docs/manifests" if fixed
                                        else "Open — blocking Phase 0 verification") + "\n"),
        "later-phases.md": ("# Later phases\n\nThe phases stay in order. Their exact acceptance gates are "
                            + ("defined in `MYCO_V3_SPEC.md`." if fixed else "authoritative in `Myco_design.md`.")
                            + "\n"),
    }
    if not fixed:
        files["scripts/_inspect_spec_headings.py"] = "print('headings')\n"
        files["scripts/normalize_pnpm_lock.py"] = "print('lock')\n"
    for relative, body in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return root


CONFIG = {"authority_docs": ["MYCO_V3_SPEC.md"], "superseded_docs": ["Myco_design.md"]}


def test_hard_checks_find_the_five_phase0_defects(tmp_path):
    result = run_hard_checks(_repo(tmp_path, fixed=False), CONFIG)
    found = [(f["check"], f["file"]) for f in result["findings"]]
    assert result["pins"]["python"] == "3.14.7" and result["pins"]["typescript"] == "7.0.2"
    # 1. Python below the spec, in every file that pins it, and the ADR that claims otherwise
    for file in (".python-version", "pyproject.toml", "uv.lock"):
        assert ("spec_pins", file) in found, file
    assert ("document_claims", "docs/adr/0004-python.md") in found
    # 2. TypeScript and Vitest below the spec
    details = " ".join(f["detail"] for f in result["findings"] if f["file"] == "apps/web/package.json")
    assert "typescript" in details and "7.0.2" in details and "vitest" in details and "5.0.1" in details
    # 3. an ADR still open and blocking
    assert ("open_blockers", "docs/adr/0006-digests.md") in found
    assert not any(f == "docs/adr/0001-template.md" for _c, f in found)  # a template's status list is not open
    # 4. the superseded design called authoritative
    assert ("superseded_authority", "later-phases.md") in found
    # 5. scripts nothing uses; a referenced script is kept
    assert ("stray_files", "scripts/_inspect_spec_headings.py") in found
    assert ("stray_files", "scripts/normalize_pnpm_lock.py") in found
    assert ("stray_files", "scripts/check_launch.py") not in found
    # what agrees with the spec is not reported
    assert not any(f in (".nvmrc", "infra/versions.tf") for _c, f in found)


def test_a_corrected_copy_passes_every_hard_check(tmp_path):
    result = run_hard_checks(_repo(tmp_path, fixed=True), CONFIG)
    assert result["findings"] == []
    assert set(result["ran"]) == {"lockfile", "open_blockers", "spec_pins", "document_claims", "stray_files",
                                  "superseded_authority"}


def test_lockfile_must_match_the_manifests(tmp_path):
    root = _repo(tmp_path, fixed=True)
    (root / "apps/web/package.json").write_text(json.dumps({"name": "@myco/web", "devDependencies": {
        "typescript": "7.0.2", "vitest": "5.0.1", "zod": "4.1.0"}}))
    findings = run_hard_checks(root, {})["findings"]
    assert [f["check"] for f in findings] == ["lockfile"] and "zod" in findings[0]["detail"]
    assert pnpm_importers(LOCK.format(ts="7.0.2", vitest="5.0.1"))["apps/web"] == {"typescript": "7.0.2",
                                                                                   "vitest": "5.0.1"}


def test_claims_read_the_version_next_to_the_component():
    assert claimed_versions("Pinned runtimes: Node.js 24.21.0, pnpm 12.5.1, and Python 3.14.7 with uv.") == [
        ("node", "24.21.0"), ("pnpm", "12.5.1"), ("python", "3.14.7")]
    assert claimed_versions("Python 3.13.15 -> 3.14.7 was adopted.") == [("python", "3.14.7")]


def test_without_authority_documents_only_safe_checks_run(tmp_path):
    (tmp_path / "main.py").write_text("print(1)\n")
    (tmp_path / "helper.py").write_text("print(2)\n")
    result = run_hard_checks(tmp_path, {})
    assert result["findings"] == [] and "stray_files" not in result["ran"]
    assert check_open_blockers(Repo(tmp_path)) == []


def test_passages_keep_their_own_headings_and_size():
    long_section = "\n\n".join(f"Paragraph {i} " + "word " * 150 for i in range(12))
    markdown = f"Intro text.\n\n## Install\n\nRun it.\n\n### Windows\n\nUse WSL.\n\n## Big\n\n{long_section}\n"
    passages = split_passages(markdown, "Guide")
    paths = [p.heading_path for p in passages]
    assert paths[:3] == ["Guide", "Guide › Install", "Guide › Install › Windows"]
    assert passages[2].content == "Use WSL."
    big = [p for p in passages if p.heading_path == "Guide › Big"]
    assert len(big) > 1 and all(len(p.content) <= MAX_TOKENS * CHARS_PER_TOKEN + 2 for p in big)


def test_reciprocal_rank_fusion_rewards_agreement():
    ranked = fuse(["a", "b", "c"], ["c", "a", "d"])
    assert [item for item, _ in ranked][:2] == ["a", "c"]
    assert ranked[0][1] == pytest.approx(1 / 61 + 1 / 62)
    assert "Read" in render_passages([{"kind": "link", "title": "T", "publisher": "P", "url": "https://x",
                                       "note": "Read it live."}])


def test_embedding_key_comes_from_settings_when_not_in_the_environment(monkeypatch):
    from app.core.config import settings
    from app.core.memory import embeddings

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-from-settings", raising=False)
    assert embeddings.EmbeddingService().api_key is None  # under test, never a real key
    monkeypatch.setattr(settings, "TESTING", False, raising=False)
    service = embeddings.EmbeddingService()
    assert service.api_key == "sk-from-settings" and service.provider == "openai"


def _pg(db) -> bool:
    return db.get_bind().dialect.name == "postgresql"


@pytest.mark.integration
def test_ingest_licence_gate_versions_and_search():
    from sqlalchemy import select

    from app.core.knowledge.ingest import KnowledgeIngestor
    from app.core.knowledge.search import agent_passages, search_passages
    from app.models.knowledge_library import KnowledgeChunk

    ingestor = KnowledgeIngestor()
    tag = uuid4().hex[:8]
    stored = {"url": f"https://docs.example.org/{tag}/python-versions", "title": "Python versions",
              "publisher": "Astral (uv)", "agents": ["verifier"], "licence": "MIT",
              "licence_evidence": "https://docs.example.org/license", "licence_class": "store"}
    linked = {"url": f"https://docs.example.org/{tag}/tsconfig", "title": "TSConfig Reference",
              "publisher": "TypeScript", "agents": ["verifier"], "licence_class": "link_only"}
    text_v1 = ("## Pinning\n\nA .python-version file pins the interpreter; uv reads requires-python from "
               f"pyproject.toml. marker{tag}\n\n## Installing\n\nuv python install fetches managed interpreters.\n")

    async def run():
        async with AsyncTestingSessionLocal() as db:
            if not _pg(db):
                return None
            with pytest.raises(ValueError):
                await ingestor.register(db, {**stored, "url": f"https://docs.example.org/{tag}/x",
                                             "licence_evidence": None})
            with pytest.raises(ValueError):
                await ingestor.register(db, {**stored, "url": f"http://docs.example.org/{tag}/x"})
            source = await ingestor.register(db, stored)
            first = await ingestor.ingest_text(db, source, text_v1)
            again = await ingestor.ingest_text(db, source, text_v1)
            second = await ingestor.ingest_text(db, source, text_v1 + "\n## Removing\n\nuv python uninstall.\n")
            link = await ingestor.register(db, linked)
            link_result = await ingestor.ingest_text(db, link, "<p>should never be stored</p>")
            await db.commit()
            rows = (await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))
                    ).scalars().all()
            link_rows = (await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.source_id == link.id))
                         ).scalars().all()
            hits = await search_passages(db, f"pin python version requires-python marker{tag}", agents=["verifier"])
            link_hits = await search_passages(db, "tsconfig reference strict", agents=["verifier"])
            other_field = await search_passages(db, f"marker{tag}", agents=["marketing"])
            briefs = await agent_passages(db, "verifier", f"python pinning marker{tag}")
            return first, again, second, link_result, rows, link_rows, hits, link_hits, other_field, briefs

    out = asyncio.run(run())
    if out is None:
        pytest.skip("passage search needs PostgreSQL")
    first, again, second, link_result, rows, link_rows, hits, link_hits, other_field, briefs = out
    assert first["status"] == "updated" and first["version"] == 1 and first["passages"] == 2
    assert again["status"] == "unchanged"
    assert second["version"] == 2
    assert sorted((r.version, r.is_active) for r in rows) == [(1, False), (1, False), (2, True), (2, True),
                                                              (2, True)]
    assert link_result["status"] == "link_only" and link_rows == []
    top = hits[0]
    assert top["kind"] == "passage" and top["by_words"] and "Pinning" in top["heading_path"]
    assert top["url"] == stored["url"] and top["version"] == 2
    assert any(h["kind"] == "link" and h["url"] == linked["url"] for h in link_hits)
    assert not any(h.get("url") == stored["url"] for h in other_field)
    assert briefs and {"id", "title", "source_url", "content"} <= set(briefs[0])


class _Router:
    def __init__(self):
        self.first = {}

    async def complete(self, request):
        from app.core.providers import CompletionResponse

        who = "verifier" if (request.system or "").startswith("You are JARV's Verifier Agent") else "mission"
        self.first.setdefault(who, request.messages[0].content)
        if who == "mission":
            name, args = "finish", {"summary": "Phase 0 conforms to the spec.", "success": True}
        else:
            name, args = "verdict", {"verified": True, "unmet": [], "checks": [
                {"requirement": "pins match", "met": True, "evidence": "looked"}]}
        return CompletionResponse(id="r", model="test", content="", usage={"total_tokens": 5}, tool_calls=[
            {"id": f"{who}-1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}])


@pytest.mark.integration
@pytest.mark.parametrize("mission, blocked", [
    ("Bring MYCO Phase 0 into conformance with MYCO_V3_SPEC.md.", True),
    ("Add a short welcome line to CONTRIBUTING.md.", False),
])
def test_a_failed_hard_check_is_unmet_whatever_the_verifier_says(monkeypatch, mission, blocked):
    """The Verifier agent passed MYCO Phase 0 with Python 3.12.8 against a locked 3.14.7. The hard checks run
    before it and are shown to the mission at its start; for a conformance mission every failure keeps the mission
    open. An unrelated mission is not held to defects that were already there and that it did not touch."""
    from app.core.command import agent_executor
    from app.core.command.agent_executor import AgentExecutor
    from app.core.command.tool_runtime import ToolRuntime
    from app.core.workspaces.fs_inspector import SANDBOX_CONTAINER_ROOT
    from app.models.task import Task
    from app.models.user import User
    from app.models.workspace import Workspace

    name = f"conformance-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    shutil.rmtree(folder, ignore_errors=True)
    _repo(folder, fixed=False)
    host = f"/test_workspaces/{name}"
    router = _Router()
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid = uuid4(), uuid4()
            session.add(User(id=uid, username=f"u{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.io",
                             password_hash="$2b$12$x", is_active=True, is_admin=False))
            session.add(Workspace(id=wid, name="MYCO", slug=f"myco-{wid.hex[:8]}", description="d", owner_id=uid,
                                  is_active=True, workspace_type="software", authority_level=4,
                                  config={"root_path": host, **CONFIG}))
            task = Task(id=uuid4(), title="Phase 0", description="d", workspace_id=wid, status="running",
                        priority=5, task_type="command")
            session.add(task)
            await session.commit()
            runtime = ToolRuntime(session, wid, task.id, operator=str(uid), authority_level=4, user_id=uid)
            return await AgentExecutor(runtime, "test-model", host).run(mission, max_continuations=0)

    try:
        result = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert "HARD CHECKS FIND" in router.first["mission"] and ".python-version" in router.first["mission"]
    assert "JARV'S HARD CHECKS" in router.first["verifier"]
    verification = result["verification"]
    assert verification["hard_checks"]["findings"]
    if not blocked:
        assert verification["verified"] is True and result["success"] is True
        return
    assert verification["verified"] is False and result["success"] is False and result["needs_continuation"]
    assert any(".python-version" in item and "3.14.7" in item for item in verification["unmet"])
    assert any("0006-digests.md" in item for item in verification["unmet"])


def test_every_agent_has_source_documentation_with_a_recorded_licence():
    """Upgrade 1b: all 31 agents have official sources; text is stored only with the licence and where it was
    read; no-derivatives or unconfirmed sources are read live instead."""
    from app.core.agents.registry import get_registry
    from app.core.knowledge.documentation import ALL_AGENTS, catalogue

    entries = catalogue()
    assert set(ALL_AGENTS) == set(get_registry().REQUIRED_AGENTS)
    for agent in ALL_AGENTS:
        assert any(agent in e["agents"] and e["licence_class"] == "store" for e in entries), agent
    urls = [e["url"] for e in entries]
    assert len(urls) == len(set(urls))
    for entry in entries:
        assert entry["url"].startswith("https://")
        if entry["licence_class"] == "store":
            assert entry["licence"] and entry["licence_evidence"], entry["url"]
    sre = [e for e in entries if e["url"].startswith("https://sre.google/")]
    assert sre and all(e["licence_class"] == "link_only" for e in sre)  # CC BY-NC-ND: never stored


@pytest.mark.integration
def test_sources_dropped_from_the_catalogue_are_retired():
    from sqlalchemy import select

    from app.core.knowledge.ingest import KnowledgeIngestor
    from app.core.knowledge.search import search_passages
    from app.models.knowledge_library import KnowledgeChunk

    ingestor = KnowledgeIngestor()
    tag = uuid4().hex[:8]
    old = {"url": f"https://docs.example.org/{tag}/moved", "title": "Backup", "publisher": "Example",
           "agents": ["infrastructure"], "licence": "MIT", "licence_evidence": "https://docs.example.org/l",
           "licence_class": "store"}

    async def run():
        async with AsyncTestingSessionLocal() as db:
            if not _pg(db):
                return None
            source = await ingestor.register(db, old)
            await ingestor.ingest_text(db, source, f"## Backups\n\nTake a base backup daily. retire{tag}\n")
            await db.commit()
            before = await search_passages(db, f"retire{tag}", agents=["infrastructure"])
            from app.models.knowledge_library import KnowledgeSource

            others = set((await db.execute(select(KnowledgeSource.url).where(
                KnowledgeSource.url != old["url"]))).scalars().all())
            retired = await ingestor.retire_missing(db, keep=others)  # only this test's source leaves
            after = await search_passages(db, f"retire{tag}", agents=["infrastructure"])
            active = (await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id,
                                                                    KnowledgeChunk.is_active.is_(True)))
                      ).scalars().all()
            return before, retired, after, active

    out = asyncio.run(run())
    if out is None:
        pytest.skip("passage search needs PostgreSQL")
    before, retired, after, active = out
    assert before and [r["url"] for r in retired] == [old["url"]]
    assert after == [] and active == []
