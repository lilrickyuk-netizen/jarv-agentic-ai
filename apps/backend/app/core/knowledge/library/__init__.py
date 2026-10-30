"""
JARV Backend - Specialist knowledge library

Each agent's field knowledge beyond its core brief: several topics per agent,
each an original synthesis of one authoritative public source that was read
when the topic was written (see sources.py). Topics are installed and
versioned by the knowledge service like the core briefs, retrieved by task
relevance, and available to agents mid-task through consult_specialist_knowledge.
"""
from __future__ import annotations

from typing import Dict, List

from app.core.knowledge.library import business, engineering, extended, growth, operations, orchestration


def library_entries() -> List[Dict]:
    entries: List[Dict] = []
    for module in (engineering, operations, orchestration, business, growth, extended):
        entries.extend(dict(entry) for entry in module.ENTRIES)
    return entries
