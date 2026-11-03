"""
Tell JAI which documents govern a workspace, and run its hard conformance checks on demand.

    docker compose exec -T backend python -m app.cli.conformance set --workspace MYCO \
        --authority MYCO_V3_SPEC.md --superseded Myco_design.md
    docker compose exec -T backend python -m app.cli.conformance check --workspace MYCO

``set`` stores ``authority_docs`` and ``superseded_docs`` in the workspace's config and writes an audit entry.
``check`` reads the workspace folder and prints every finding; it never changes the folder. The same checks run
at the start of each mission and inside every verification.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select


async def _workspace(db, name: str):
    from app.models.workspace import Workspace

    rows = (await db.execute(select(Workspace).where(func.lower(Workspace.name) == name.lower(),
                                                     Workspace.is_archived.is_(False)))).scalars().all()
    if len(rows) != 1:
        raise SystemExit(f"Expected one active workspace named {name!r}, found {len(rows)}.")
    return rows[0]


async def set_docs(name: str, authority, superseded) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.operations import AuditLog

    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, name)
        config = dict(workspace.config or {})
        before = {"authority_docs": config.get("authority_docs"), "superseded_docs": config.get("superseded_docs")}
        config["authority_docs"] = list(authority)
        config["superseded_docs"] = list(superseded or [])
        workspace.config = config
        now = datetime.now(timezone.utc)
        db.add(AuditLog(id=uuid4(), workspace_id=workspace.id, actor_type="user", action="workspace.authority_docs",
                        action_category="workspace", description=f"Authority documents for {workspace.name} set",
                        target_type="workspace", target_id=str(workspace.id), before_state=before,
                        after_state={"authority_docs": config["authority_docs"],
                                     "superseded_docs": config["superseded_docs"]},
                        success=True, created_at=now, updated_at=now))
        await db.commit()
        print(f"{workspace.name}: authority {config['authority_docs']}, superseded {config['superseded_docs']}")
    return 0


async def check(name: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.verification.checks import render_findings, run_hard_checks
    from app.core.workspaces import fs_inspector

    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, name)
        config = dict(workspace.config or {})
    root = config.get("root_path")
    folder = fs_inspector.host_to_container(root) if root else None
    if folder is None or not folder.is_dir():
        print(f"{name}: the workspace folder {root!r} is not reachable from JAI.")
        return 2
    result = await asyncio.to_thread(run_hard_checks, folder, config)
    print(f"{name}: {result['files_scanned']} files, checks: {', '.join(result['ran'])}")
    print(render_findings(result, limit=200))
    return 1 if result["findings"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.conformance")
    sub = parser.add_subparsers(dest="command", required=True)
    setter = sub.add_parser("set", help="store the workspace's authority and superseded documents")
    setter.add_argument("--workspace", required=True)
    setter.add_argument("--authority", action="append", required=True)
    setter.add_argument("--superseded", action="append", default=[])
    checker = sub.add_parser("check", help="run the hard checks on the workspace folder")
    checker.add_argument("--workspace", required=True)
    args = parser.parse_args()
    if args.command == "set":
        return asyncio.run(set_docs(args.workspace, args.authority, args.superseded))
    return asyncio.run(check(args.workspace))


if __name__ == "__main__":
    raise SystemExit(main())
