"""
Upgrade 4: No AI Slop as JAI's final editorial pass. The skill file is a short one in the skill's own layout, made
in the test (the real pack is mounted only in the running system); the model is a recorded fake.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core.business import editorial

SKILL = """---
name: no-ai-slop
description: Edit drafts into sharper, more human writing.
---

# No AI slop

## Editing principles

- **Keep the user's meaning.** Don't invent claims, examples, stats, or opinions.

## Words to cut

Banned outright: delve, leverage, robust, game changer, ever-evolving.

Often-empty phrases: it's worth noting, at the end of the day, let's dive in. Cut them when they delay the point.

## Patterns to cut

**Binary contrasts.** "This is not X. It's Y." State Y directly.

## Workflow

1. Read the full draft before editing.
"""


@pytest.fixture
def pack(tmp_path, monkeypatch):
    from app.core.config import settings

    folder = tmp_path / "no-ai-slop" / "skills" / "no-ai-slop"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL)
    monkeypatch.setattr(settings, "SKILL_PACKS_DIR", str(tmp_path))
    editorial._parsed.cache_clear()
    return folder


def test_without_the_pack_nothing_changes(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SKILL_PACKS_DIR", str(tmp_path))
    assert editorial.rules() == "" and editorial.findings("We leverage robust tools.") == []


def test_the_writer_gets_the_editors_rules_and_the_check_needs_no_model(pack):
    rules = editorial.rules()
    assert "Banned outright" in rules and "Binary contrasts" in rules and "Workflow" not in rules
    found = editorial.findings("Let's dive in. We leverage a robust engine. It's not just fast, but cheap — "
                               "and simple — and done — today.")
    patterns = {f["pattern"] for f in found}
    assert {"banned word 'leverage'", "banned word 'robust'", "empty phrase 'let's dive in'",
            "binary contrast"} <= patterns
    assert any(p.startswith("em dashes") for p in patterns)
    assert editorial.findings("Plexecute sends you one reminder at 7am and logs the streak.") == []


def test_a_flagged_draft_is_revised_once_and_kept_only_when_every_fact_survives(pack):
    calls = []
    draft = "We leverage a robust planner that saves 40 minutes a day. [confirm: price] See https://plexecute.app"

    def model(reply):
        async def complete(model, prompt, **kwargs):
            calls.append((model, prompt, kwargs["system"]))
            return {"text": reply}
        return complete

    good = asyncio.run(editorial.revise(draft, complete=model(
        "The planner saves 40 minutes a day. [confirm: price] See https://plexecute.app")))
    assert good["revised"] is True and good["findings_before"] == 2 and good["findings_after"] == 0
    assert calls[0][0] == "gpt-6-luna" and "leverage" in calls[0][1] and "Banned outright" in calls[0][2]

    lost = asyncio.run(editorial.revise(draft, complete=model("The planner saves time. See https://plexecute.app")))
    assert lost["revised"] is False and lost["text"] == draft and "fact" in lost["reason"]

    clean = asyncio.run(editorial.revise("The planner saves 40 minutes a day.", complete=model("unused")))
    assert clean["revised"] is False and len(calls) == 2  # nothing flagged, no model call
