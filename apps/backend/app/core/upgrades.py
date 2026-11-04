"""
JAI Backend - What JAI knows about its own upgrades

Every upgrade Richard installs is a commit in his JAI repository, with a subject that says what it added. The
repository's history is mounted read-only into the backend (JAI_REPO_GIT), so the voice can answer "what upgrades
have you had today?" from the record itself: when each was installed and what it did.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List

from app.core.config import settings

logger = logging.getLogger(__name__)


def repo_git() -> str:
    return str(getattr(settings, "JAI_REPO_GIT", "") or "")


async def recent(days: int = 3, limit: int = 15) -> List[Dict[str, Any]]:
    """The upgrades installed in the last ``days`` days, newest first: {"when", "what"}. Empty when the history is
    not mounted; never raises."""
    git_dir = repo_git()
    if not git_dir or not os.path.isdir(git_dir):
        return []
    try:
        process = await asyncio.create_subprocess_exec(
            "git", "-c", "safe.directory=*", f"--git-dir={git_dir}", "log", f"--since={max(1, days)} days ago",
            f"--max-count={max(1, min(limit, 50))}", "--format=%cI%x09%s",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(process.communicate(), timeout=4)
    except Exception as exc:  # noqa: BLE001 - an addition to the voice's picture, never a reason to fail
        logger.info("upgrade history not read: %s", exc)
        return []
    if process.returncode != 0:
        logger.info("upgrade history not read: %s", err.decode(errors="replace")[:200])
        return []
    found = []
    for line in out.decode(errors="replace").splitlines():
        when, _, what = line.partition("\t")
        if what:
            found.append({"when": when[:16], "what": what[:300]})
    return found
