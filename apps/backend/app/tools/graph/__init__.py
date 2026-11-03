"""
JARV Backend - trace_artifact (Upgrade 3)

What a file, requirement, command or decision is connected to in the workspace's artifact graph: what a file
implements, what verified a requirement, which checks contradict a decision, which mission changed it. Read-only,
confined to the calling workspace. Every agent's toolbox and the Verifier offer it.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.agents.base import AuthorityLevel
from app.tools._scoped import ScopedTool


class _Trace(BaseModel):
    key: str = Field(..., min_length=1, max_length=500,
                     description="A file path (apps/web/package.json), a requirement id (R4), a command, or an ADR")
    depth: int = Field(3, ge=1, le=4)


class TraceArtifactTool(ScopedTool):
    _name = "trace_artifact"
    _description = ("Trace what a file, requirement (R4), command or decision is connected to: what it implements, "
                    "what verified it, which checks contradict it and which mission changed it.")
    _input = _Trace
    _category = "knowledge"
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        from app.core.graph import graph_service

        trace = await graph_service.trace(db, context.workspace_id, data["key"], depth=data["depth"])
        text = graph_service.describe(trace)
        return {"key": data["key"], "nodes": trace["nodes"], "edges": trace["edges"], "lines": text.splitlines()}, (
            f"{len(trace['nodes'])} linked record(s) for {data['key']}")


GRAPH_TOOLS = [TraceArtifactTool]
