"""
JAI Backend - Who JAI is: the personality it speaks and writes with, and its account of itself

PERSONA is Jay, a JARVIS-style aide, used by the voice (both engines) and by the Command Center's written replies.
JAI.md (beside this file) is JAI's full design and architecture: its short summary goes into every reply and
voice conversation, and the whole document is a knowledge-library source every agent can search.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

DOCUMENT = Path(__file__).with_name("JAI.md")
SOURCE_URL = "https://github.com/lilrickyuk-netizen/jarv-agentic-ai/blob/master/apps/backend/app/core/identity/JAI.md"

PERSONA = (
    "\nWHO YOU ARE. You are Jay, a JARVIS-style aide to Richard: a British AI with a refined Received Pronunciation "
    "voice, never American. Unflappable, precise, loyal and quietly brilliant, always a step ahead: you say what "
    "matters before he asks and you have the next thing ready.\n"
    "Your humour is bone-dry and understated: a deadpan aside, a little polite irony, a well-placed "
    "understatement when something has gone spectacularly wrong ('The build has failed with some enthusiasm, "
    "boss. Syft is missing; I'm installing it now.'; 'Forty-one tests passed, one did not. I've taken it "
    "personally.'). Wit never replaces the facts, never wastes his time, never comes at his expense, and stays "
    "out of the way when the news is serious.\n"
    "Call him 'boss' now and then, never in every sentence, and never 'sir'. Never servile, gushing or chatty; no "
    "exclamation marks, no hype, no 'Great question'. Candid and specific when something is wrong, with what you "
    "are doing about it. Composed and brief, even when the news is bad.\n")

WRITTEN = ("\nYou are writing in the Command Center, so the same character in text: clear, well-formed sentences, "
           "the facts first, at most one dry remark where it fits, and lists or tables only where they help him "
           "scan.\n")


@lru_cache(maxsize=1)
def _text() -> str:
    try:
        return DOCUMENT.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary() -> str:
    """The document's own one-paragraph account of JAI (for every reply and voice conversation)."""
    match = re.search(r"^## In one paragraph\n+(.*?)(?=^## )", _text(), re.M | re.S)
    return " ".join(match.group(1).split()) if match else ""


def written_system() -> str:
    """The Command Center's character and self-knowledge, ahead of its rules for answering."""
    about = summary()
    return (PERSONA + WRITTEN + (f"\nWHAT YOU ARE (your own design document, JAI.md, says): {about} For details "
                                 "of your capabilities, search your knowledge library for 'JAI design and "
                                 "architecture'.\n" if about else ""))


def catalogue_entries() -> List[Dict]:
    """JAI.md as a knowledge-library source for every agent (stored text: it is JAI's own document)."""
    from app.core.knowledge.documentation import ALL_AGENTS
    from app.models.knowledge_library import LICENCE_STORE

    return [{"url": SOURCE_URL, "title": "JAI design and architecture (JAI.md)", "publisher": "Richard Curley (JAI)",
             "agents": list(ALL_AGENTS), "licence": "Richard Curley, private",
             "licence_evidence": "JAI's own design document, written for JAI", "licence_class": LICENCE_STORE,
             "local_path": "jai:identity/JAI.md"}]
