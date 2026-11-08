"""
JAI Backend - The acceptance ledger a builder keeps in the project (.jai/ledger.json)

After Anthropic's harness for long-running agents: the plan for a phase is written once, as a JSON list of items,
each with the exact command that proves it, and is frozen from then on. The builder works through it one item at a
time, setting "passes" when an item's check passes and "blocked" (with the kind of failure and what would unblock
it) when the same check keeps failing. It lives in the project and is committed with it.

JAI reads it (the workspace is mounted read-only): a later mission on the same phase takes its requirements from the
ledger instead of deriving new ones, so the plan is never re-made, and every report names what is blocked and why.

  {"phase": "Phase 0", "items": [{"id": "R1", "text": "...", "depends_on": [], "files": [],
                                  "check": "task verify", "passes": false, "blocked": null}, ...]}
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LEDGER = ".jai/ledger.json"
PHASE = re.compile(r"\bphase\s*(\d+)\b", re.I)
ID = re.compile(r"^R\d+$", re.I)


def phase_of(text: str) -> Optional[str]:
    match = PHASE.search(text or "")
    return f"phase {match.group(1)}" if match else None


def load(workspace_root: Optional[str]) -> Optional[Dict[str, Any]]:
    """The project's ledger, or None when there is none (or it cannot be read)."""
    if not workspace_root:
        return None
    from app.core.workspaces import fs_inspector

    container = fs_inspector.host_to_container(workspace_root)
    if container is None:
        return None
    path = container / ".jai" / "ledger.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if path.exists():
            logger.info(f"ledger {path} not read: {exc}")
        return None
    return data if isinstance(data, dict) and isinstance(data.get("items"), list) else None


def requirements(workspace_root: Optional[str], mission: str) -> Optional[List[Dict[str, Any]]]:
    """The frozen ledger as this mission's requirements, when it is for the same phase as the mission (or neither
    names one): passed items are done (the Verifier still checks them), the rest are open."""
    data = load(workspace_root)
    if data is None:
        return None
    if phase_of(str(data.get("phase") or "")) != phase_of(mission):
        return None
    out = []
    for item in data["items"]:
        if not isinstance(item, dict) or not ID.match(str(item.get("id") or "")):
            continue
        check = str(item.get("check") or "").strip()
        text = str(item.get("text") or "").strip()
        out.append({"id": str(item["id"]).upper(), "text": (f"{text} (check: `{check}`)" if check else text)[:1000],
                    "source": "acceptance ledger", "status": "done" if item.get("passes") is True else "open",
                    "evidence": "the ledger records its check passing" if item.get("passes") is True else ""})
    return out or None


def blocked(workspace_root: Optional[str]) -> List[str]:
    """The ledger's blocked items, as lines for Richard's report: what failed, what kind of failure, what is needed."""
    data = load(workspace_root)
    if data is None:
        return []
    lines = []
    for item in data["items"]:
        info = item.get("blocked") if isinstance(item, dict) else None
        if not info:
            continue
        if isinstance(info, dict):
            lines.append(f"{item.get('id')} [{info.get('class') or 'unclassified'}] "
                         f"{str(info.get('error') or '')[:200]} — needs: {str(info.get('needs') or '?')[:200]}")
        else:
            lines.append(f"{item.get('id')} blocked: {str(info)[:300]}")
    return lines
