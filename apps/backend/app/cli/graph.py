"""
Build the artifact graph for existing work, or trace one thing in it.

    docker compose exec -T backend python -m app.cli.graph backfill              # every active workspace
    docker compose exec -T backend python -m app.cli.graph backfill --workspace MYCO
    docker compose exec -T backend python -m app.cli.graph trace --workspace MYCO --key .python-version

Backfill is safe to run more than once: records are matched on their keys, so a second run adds nothing.
Each backfill is written to the audit log. Nothing here changes any project folder.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select


async def _workspaces(db, name):
    from app.models.workspace import Workspace

    query = select(Workspace).where(Workspace.is_archived.is_(False))
    if name:
        query = query.where(func.lower(Workspace.name) == name.lower())
    return (await db.execute(query)).scalars().all()


async def backfill(name) -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.graph import graph_service
    from app.models.operations import AuditLog

    async with AsyncSessionLocal() as db:
        spaces = await _workspaces(db, name)
        if not spaces:
            print(f"No active workspace{' named ' + name if name else ''}.")
            return 1
        for workspace in spaces:
            counts = await graph_service.backfill(db, workspace.id)
            now = datetime.now(timezone.utc)
            db.add(AuditLog(id=uuid4(), workspace_id=workspace.id, actor_type="system", action="graph.backfill",
                            action_category="knowledge", description=f"Artifact graph backfilled for {workspace.name}",
                            target_type="workspace", target_id=str(workspace.id), after_state=counts, success=True,
                            created_at=now, updated_at=now))
            await db.commit()
            print(f"{workspace.name}: {counts['files']} file writes, {counts['commands']} commands recorded")
    return 0


async def trace(name, key) -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.graph import graph_service

    async with AsyncSessionLocal() as db:
        spaces = await _workspaces(db, name)
        if len(spaces) != 1:
            print(f"Expected one active workspace named {name!r}, found {len(spaces)}.")
            return 1
        result = await graph_service.trace(db, spaces[0].id, key)
        print(graph_service.describe(result))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.graph")
    sub = parser.add_subparsers(dest="command", required=True)
    filler = sub.add_parser("backfill", help="record past file writes and commands in the graph")
    filler.add_argument("--workspace")
    tracer = sub.add_parser("trace", help="show what one file, requirement or command is linked to")
    tracer.add_argument("--workspace", required=True)
    tracer.add_argument("--key", required=True)
    args = parser.parse_args()
    if args.command == "backfill":
        return asyncio.run(backfill(args.workspace))
    return asyncio.run(trace(args.workspace, args.key))


if __name__ == "__main__":
    raise SystemExit(main())
