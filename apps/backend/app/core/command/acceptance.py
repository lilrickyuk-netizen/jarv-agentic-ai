"""
JAI Backend - The acceptance mission: proof that a whole mission works before an upgrade is kept

Run by an installer after an upgrade, on the real machine: a small but complete software mission in its own
workspace (Projects/_jai_acceptance), done the way every mission is done (requirements, the Orchestrator's plan,
the environment engineer, the specialists, the integration engineer and the independent Verifier, in the OpenHands
sandbox, with JAI's model through its gateway). It passes only when JAI's own result says verified AND the
project's acceptance command passes in a fresh clone run here, outside the mission. The installer keeps the upgrade
only if it passes.

    python -m app.core.command.acceptance        exit 0 when it passed, 1 when it did not
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

FOLDER = "_jai_acceptance"
SLUG = "jai-acceptance"
MISSION = (
    "Create a small Python project in this workspace: a package `calc` (calc/__init__.py) with add(a, b) and "
    "sub(a, b); pytest tests for both in tests/test_calc.py; a pyproject.toml for the package; and a Taskfile.yml "
    "whose `verify` task runs the tests with uv (`uv run --with pytest pytest -q`). Initialise a git repository and "
    "commit the work. Done when `task verify` passes in a fresh clone of the repository in /tmp.")
TIMEOUT_SECONDS = 45 * 60


def _host_folder() -> str:
    from app.core.config import settings

    root = str(settings.WORKSPACE_HOST_ROOT).rstrip("\\/")
    return f"{root}\\{FOLDER}" if ("\\" in root or ":" in root[:3]) else f"{root}/{FOLDER}"


def _fresh_clone_verify(folder: Path) -> Dict[str, Any]:
    """The project's acceptance command in a fresh clone, run here, outside the mission."""
    with tempfile.TemporaryDirectory(prefix="jai-acceptance-") as tmp:
        clone = Path(tmp) / "clone"
        steps = [["git", "clone", "-q", str(folder), str(clone)], ["task", "verify"]]
        for argv in steps:
            done = subprocess.run(argv, cwd=None if argv[0] == "git" else clone, capture_output=True, text=True,
                                  timeout=600)
            if done.returncode != 0:
                return {"passed": False, "command": " ".join(argv),
                        "output": (done.stdout + done.stderr)[-1500:]}
        return {"passed": True, "command": "git clone && task verify", "output": done.stdout[-500:]}


async def run() -> Dict[str, Any]:
    from sqlalchemy import select

    from app.core.command import sandbox_engine
    from app.core.command.mission_org import mission_executor
    from app.core.command.tool_runtime import ToolRuntime
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.core.workspaces import fs_inspector
    from app.models.task import Task
    from app.models.user import User
    from app.models.workspace import Workspace

    if not await sandbox_engine.available():
        return {"passed": False, "why": "The engineering sandbox is not running or has no token."}
    host = _host_folder()
    folder = fs_inspector.host_to_container(host)
    if folder is None:
        return {"passed": False, "why": f"{host} is not inside JAI's workspaces."}
    shutil.rmtree(folder, ignore_errors=True)  # JAI's own acceptance folder, made fresh each time
    folder.mkdir(parents=True)
    started = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.is_active.is_(True))
                                 .order_by(User.is_admin.desc(), User.created_at.asc()))).scalars().first()
        if user is None:
            return {"passed": False, "why": "No user to own the acceptance workspace."}
        workspace = (await db.execute(select(Workspace).where(Workspace.slug == SLUG))).scalars().first()
        if workspace is None:
            workspace = Workspace(id=uuid4(), name="JAI acceptance", slug=SLUG, owner_id=user.id,
                                  description="Where each upgrade proves a whole mission works before it is kept.",
                                  workspace_type="software", authority_level=5, is_active=True,
                                  config={"root_path": host})
            db.add(workspace)
        else:
            workspace.config = {**(workspace.config or {}), "root_path": host}
        task = Task(id=uuid4(), title="JAI acceptance mission", description=MISSION, workspace_id=workspace.id,
                    status="running", priority=5, task_type="acceptance_check", started_at=started)
        db.add(task)
        await db.commit()
        runtime = ToolRuntime(db, workspace.id, task.id, operator=str(user.id), authority_level=5, user_id=user.id)
        try:
            result = await asyncio.wait_for(
                mission_executor(runtime, settings.DEFAULT_MODEL, host).run(MISSION, max_continuations=2),
                timeout=TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            result = {"success": False, "answer": f"Did not finish within {TIMEOUT_SECONDS // 60} minutes."}
        engine = ((result.get("metrics") or {}).get("team") or {}).get("engine")
        task.status = "completed" if result.get("success") else "failed"
        task.completed_at = datetime.now(timezone.utc)
        task.result = {k: v for k, v in result.items() if k != "messages"}
        await db.commit()
    clone = await asyncio.to_thread(_fresh_clone_verify, folder)
    team = [(p.get("id"), p.get("status"), p.get("step")) for p in (result.get("team") or {}).get("packages", [])]
    passed = bool(result.get("success")) and engine == "openhands" and clone["passed"]
    return {"passed": passed, "jai_verified": bool(result.get("success")), "engine": engine,
            "fresh_clone": clone, "team": team, "minutes": round((datetime.now(timezone.utc) - started).seconds / 60, 1),
            "cost_usd": ((result.get("metrics") or {}).get("usage") or {}).get("cost_usd"),
            "unmet": ((result.get("verification") or {}).get("unmet") or [])[:8],
            "answer": str(result.get("answer") or "")[:1500]}


def main() -> int:
    outcome = asyncio.run(run())
    print(json.dumps(outcome, indent=2, default=str))
    return 0 if outcome.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
