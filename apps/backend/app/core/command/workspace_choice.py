"""
JAI Backend - A mission goes to the workspace its brief is about, not to whichever one was selected

Richard writes briefs like "Work in C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES" or "carry on building MYCO". JAI
reads the brief and chooses:

1. A folder the brief names: the workspace whose folder holds it (the deepest one).
2. Otherwise a workspace the brief names ("MYCO", "Plexecute"; letters only, the longest name wins).
3. Otherwise the workspace that was selected, or JAI's default.

When the brief names a folder that no workspace holds, and also names a workspace whose own folder JAI cannot
reach (outside the approved root, or none registered), that workspace is moved to the named folder, provided the
folder exists inside the approved root. The move is audit-logged and reported with the mission. A folder outside
the approved root is never registered.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# A Windows folder as Richard types it: C:\Users\lilri\Projects\PLEXECUTE_IMAGES (up to a space, quote or the end).
FOLDER = re.compile(r"[A-Za-z]:\\[^\s\"'<>|?*]+")


@dataclass
class Choice:
    workspace_id: Optional[UUID]
    note: str = ""  # what JAI did, for the mission's record and Richard
    moved_from: Optional[str] = None


def _letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _root(workspace: Any) -> str:
    config = workspace.config if isinstance(workspace.config, dict) else {}
    return str(config.get("root_path") or "")


def _parts(path: str) -> List[str]:
    return [p.lower() for p in PureWindowsPath(path.rstrip(".,;:)\\")).parts]


def folders_in(text: str) -> List[str]:
    return [m.group(0).rstrip(".,;:)") for m in FOLDER.finditer(text or "")]


def holder(spaces: List[Any], folder: str):
    """The workspace whose folder holds ``folder`` (the deepest match), or None."""
    target = _parts(folder)
    best, depth = None, -1
    for workspace in spaces:
        root = _root(workspace)
        if not root:
            continue
        mine = _parts(root)
        if target[:len(mine)] == mine and len(mine) > depth:
            best, depth = workspace, len(mine)
    return best


def named(spaces: List[Any], text: str):
    heard = _letters(text)
    found = [w for w in spaces if len(_letters(w.name)) >= 4 and _letters(w.name) in heard]
    return max(found, key=lambda w: len(_letters(w.name)), default=None)


def reachable(folder: str) -> bool:
    from app.core.workspaces.fs_inspector import host_to_container

    return bool(folder) and host_to_container(folder) is not None


def exists(folder: str) -> bool:
    from app.core.workspaces.fs_inspector import host_to_container

    container = host_to_container(folder)
    return container is not None and container.is_dir()


async def choose(db: AsyncSession, text: str, given: Optional[UUID], owner: Optional[UUID]) -> Choice:
    """The workspace this brief is about (see the module's account), or ``given`` when it names none."""
    from app.models.workspace import Workspace

    query = select(Workspace).where(Workspace.is_archived == False)  # noqa: E712
    if owner is not None:
        query = query.where(Workspace.owner_id == owner)
    spaces = list((await db.execute(query)).scalars().all())
    if not spaces:
        return Choice(given)
    by_name = named(spaces, text)
    for folder in folders_in(text):
        found = holder(spaces, folder)
        if found is not None:
            return Choice(found.id, "" if found.id == given else
                          f"Working in the {found.name} workspace: it holds {folder}.")
        if by_name is not None and not reachable(_root(by_name)) and exists(folder):
            old = _root(by_name)
            by_name.config = {**(by_name.config if isinstance(by_name.config, dict) else {}), "root_path": folder}
            await db.flush()
            from app.core.audit import AuditLogger

            await AuditLogger.log_system_event(
                db, action="workspace.folder_moved", result="ok", resource_type="workspace",
                resource_id=by_name.id, user_id=owner,
                details={"workspace": by_name.name, "from": old or None, "to": folder,
                         "why": "the brief names this folder; the old one is outside JAI's approved root"})
            return Choice(by_name.id, f"Moved the {by_name.name} workspace to {folder} (the brief names it; "
                                      f"{old or 'no folder'} is outside the folders I can reach).", old or None)
    if by_name is not None:
        return Choice(by_name.id, "" if by_name.id == given else f"Working in the {by_name.name} workspace: "
                                                                  "the brief names it.")
    return Choice(given)
