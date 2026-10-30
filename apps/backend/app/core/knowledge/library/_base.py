"""Building blocks for library topics."""
from __future__ import annotations

from typing import Dict, List

from app.core.knowledge.library.sources import SOURCES


def topic(agent: str, key: str, title: str, content: str, keywords: List[str], source: str) -> Dict:
    data = SOURCES[source]
    return {"agent_name": agent, "knowledge_key": key, "title": title, "content": " ".join(content.split()),
            "keywords": keywords, "url": data["url"], "source_title": data["title"],
            "publisher": data["publisher"], "license": data.get("license")}
