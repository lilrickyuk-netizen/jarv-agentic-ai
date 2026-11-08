"""
A mission goes to the workspace its brief is about: the one holding the folder it names, else the one it names,
else the one selected. A workspace whose folder JAI cannot reach is moved to the folder the brief names (inside the
approved root only), audit-logged; and a mission carries on from earlier work on the same project in another
workspace.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.core.command import workspace_choice
from app.core.command.resume import last_state, same_project
from app.models.operations import AuditLog
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal

BRIEF = (r"Make the Plexecute launch video with your BRAG Slim skill. Work in C:\Users\lilri\Projects\PLEXECUTE_IMAGES."
         "\n\nFirst read PLEXECUTE.md in that folder.")


def _space(name, root=None):
    return SimpleNamespace(id=uuid4(), name=name, config={"root_path": root} if root else {})


def test_the_folder_a_brief_names_picks_the_workspace_that_holds_it():
    assert workspace_choice.folders_in(BRIEF) == [r"C:\Users\lilri\Projects\PLEXECUTE_IMAGES"]
    projects = _space("Projects", r"C:\Users\lilri\Projects")
    plexecute = _space("Plexecute", r"c:\users\lilri\projects\PLEXECUTE_IMAGES")
    assert workspace_choice.holder([projects, plexecute], r"C:\Users\lilri\Projects\PLEXECUTE_IMAGES\brag") is plexecute
    assert workspace_choice.holder([projects], r"C:\Users\lilri\Projects\MYCO") is projects
    assert workspace_choice.holder([plexecute], r"C:\Users\lilri\Projects\MYCO") is None
    myco = _space("MYCO")
    assert workspace_choice.named([plexecute, myco], "carry on building my co phase 0") is myco


async def _owner(db):
    user = User(id=uuid4(), username=f"u{uuid4().hex[:8]}", email=f"{uuid4().hex[:8]}@t.io", password_hash="t",
                is_active=True, is_admin=False)
    db.add(user)
    await db.flush()
    return user.id


def _ws(owner, name, root=None):
    return Workspace(id=uuid4(), owner_id=owner, name=name, slug=f"{name.lower()}-{uuid4().hex[:8]}",
                     description="", workspace_type="test", authority_level=5, is_active=True,
                     config={"root_path": root} if root else {})


def test_an_unreachable_workspace_is_moved_to_the_folder_the_brief_names(monkeypatch):
    monkeypatch.setattr(workspace_choice, "reachable", lambda folder: "Projects" in folder)
    monkeypatch.setattr(workspace_choice, "exists", lambda folder: folder.endswith("PLEXECUTE_IMAGES"))

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner = await _owner(db)
            centre = _ws(owner, "Command Center")
            plexecute = _ws(owner, "Plexecute", r"C:\Users\lilri\OneDrive\Desktop\PLEXECUTE_IMAGES")
            db.add_all([centre, plexecute])
            await db.flush()
            moved = await workspace_choice.choose(db, BRIEF, centre.id, owner)
            await db.refresh(plexecute)
            logged = (await db.execute(select(AuditLog).where(AuditLog.action == "workspace.folder_moved",
                                                              AuditLog.target_id == str(plexecute.id)))).scalars().all()
            again = await workspace_choice.choose(db, BRIEF, centre.id, owner)
            outside = await workspace_choice.choose(db, r"Plexecute video in D:\Other\place", centre.id, owner)
            plain = await workspace_choice.choose(db, "How is everything going?", centre.id, owner)
            # Read everything while the session is open (the audit log commits, and rows expire with it).
            seen = {"plexecute": plexecute.id, "root": plexecute.config["root_path"], "centre": centre.id}
            await db.rollback()
            return seen, moved, logged, again, outside, plain

    seen, moved, logged, again, outside, plain = asyncio.run(run())
    assert moved.workspace_id == seen["plexecute"] and "Moved the Plexecute workspace" in moved.note
    assert seen["root"] == r"C:\Users\lilri\Projects\PLEXECUTE_IMAGES" and len(logged) == 1
    assert again.workspace_id == seen["plexecute"] and "holds" in again.note  # now it simply holds the folder
    # A folder outside the approved root is never registered: the brief's name still picks the workspace.
    assert outside.workspace_id == seen["plexecute"] and "Moved" not in outside.note
    assert plain.workspace_id == seen["centre"] and plain.note == ""


def test_a_mission_carries_on_from_the_same_project_in_another_workspace():
    assert same_project("Carry on building MYCO Phase 0", "Build MYCO Phase 0", "MYCO")
    assert same_project(r"carry on in C:\Users\lilri\Projects\MYCO", r"Phase 0 in C:\Users\lilri\Projects\MYCO")
    assert not same_project("Carry on building MYCO Phase 0", "Make the Plexecute video", "MYCO")

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner = await _owner(db)
            centre, myco = _ws(owner, "Command Center"), _ws(owner, "MYCO")
            db.add_all([centre, myco])
            await db.flush()
            earlier = Task(id=uuid4(), title="MYCO Phase 0", description="Build MYCO Phase 0", task_type="command",
                           workspace_id=centre.id, status="failed",
                           result={"requirements": [{"id": "R1", "text": "Monorepo", "status": "done",
                                                     "evidence": "pnpm -r build passed"}],
                                   "verification": {"verified": False}})
            db.add(earlier)
            await db.commit()
            found = await last_state(db, myco.id, None, "Carry on building MYCO Phase 0")
            other = await last_state(db, myco.id, None, "Phase 0 of the Plexecute video")
            return earlier.id, found, other

    earlier_id, found, other = asyncio.run(run())
    assert found["task_id"] == str(earlier_id) and found["requirements"][0]["status"] == "done"
    assert other is None
