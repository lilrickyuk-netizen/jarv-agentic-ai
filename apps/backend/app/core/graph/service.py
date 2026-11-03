"""
JAI Backend - The Artifact Intelligence Graph (Upgrade 3)

Ties each requirement to the files, commands, checks and decisions behind it, so JAI answers "what proves this?"
and "what did this change touch?" from records, not from a summary.

How it fills:
* ToolRuntime calls ``record_file`` after every successful file write and ``record_command`` after every command,
  in the same transaction as their FileChange and CommandRun rows: file (or decision) node, command node, and their
  ``changed_by`` / ``run_in`` edges to the mission. Nothing new is asked of the agents.
* The mission records its numbered requirements (``required_by`` the mission).
* The Verifier's verdict adds ``verifies`` edges (its check for a requirement, with the evidence it gave) and, where
  the evidence names a file or command this mission touched, ``implements`` / ``verifies`` edges from them. Hard-check
  failures add ``contradicts`` edges from the check to the file or decision that disagrees with the specification.
* ``backfill`` builds the graph once for existing workspaces from their FileChange and CommandRun rows.

``trace`` walks the edges in both directions (up to four steps) inside one workspace only.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact_graph import ArtifactEdge, ArtifactNode

logger = logging.getLogger(__name__)

MAX_DEPTH = 4
MAX_TRACE_NODES = 200
_ADR = re.compile(r"(^|/)(adr|decisions)/|(^|/)adr[-_ ]?\d+", re.IGNORECASE)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


class GraphService:
    def __init__(self) -> None:
        self._roots: Dict[UUID, Optional[str]] = {}

    # ------------------------------------------------------------------ keys

    async def _root(self, db: AsyncSession, workspace_id: UUID) -> Optional[str]:
        if workspace_id not in self._roots:
            from app.models.workspace import Workspace

            workspace = await db.get(Workspace, workspace_id)
            root = ((workspace.config or {}).get("root_path") if workspace is not None else None) or None
            self._roots[workspace_id] = str(root).replace("\\", "/").rstrip("/") if root else None
        return self._roots[workspace_id]

    async def file_key(self, db: AsyncSession, workspace_id: UUID, path: str) -> str:
        """A path as the workspace sees it: relative to its folder, forward slashes."""
        norm = str(path or "").replace("\\", "/").strip()
        root = await self._root(db, workspace_id)
        if root and norm.lower().startswith(root.lower() + "/"):
            norm = norm[len(root) + 1:]
        while norm.startswith("./"):
            norm = norm[2:]
        return norm.lstrip("/") or norm

    @staticmethod
    def file_kind(key: str) -> str:
        return "decision" if _ADR.search(key) else "file"

    # ---------------------------------------------------------------- writes

    async def node(self, db: AsyncSession, workspace_id: UUID, kind: str, key: str, *, title: str = "",
                   attrs: Optional[Dict[str, Any]] = None, sha: Optional[str] = None,
                   task_id: Optional[UUID] = None) -> ArtifactNode:
        key = key[:4000]
        found = (await db.execute(select(ArtifactNode).where(
            ArtifactNode.workspace_id == workspace_id, ArtifactNode.kind == kind,
            ArtifactNode.key == key))).scalar_one_or_none()
        if found is None:
            found = ArtifactNode(workspace_id=workspace_id, kind=kind, key=key, title=(title or key)[:2000],
                                 attrs=dict(attrs or {}), content_sha256=sha, task_id=task_id)
            db.add(found)
        else:
            if title:
                found.title = title[:2000]
            if attrs:
                found.attrs = {**(found.attrs or {}), **attrs}
            if sha:
                found.content_sha256 = sha
            if task_id is not None:
                found.task_id = task_id
        await db.flush()
        return found

    async def link(self, db: AsyncSession, workspace_id: UUID, source: ArtifactNode, target: ArtifactNode,
                   relation: str, *, task_id: Optional[UUID] = None,
                   evidence: Optional[Dict[str, Any]] = None) -> ArtifactEdge:
        found = (await db.execute(select(ArtifactEdge).where(
            ArtifactEdge.source_id == source.id, ArtifactEdge.target_id == target.id,
            ArtifactEdge.relation == relation,
            ArtifactEdge.task_id.is_(None) if task_id is None else ArtifactEdge.task_id == task_id)
        )).scalar_one_or_none()
        if found is None:
            found = ArtifactEdge(workspace_id=workspace_id, source_id=source.id, target_id=target.id,
                                 relation=relation, task_id=task_id, evidence=dict(evidence or {}))
            db.add(found)
        elif evidence:
            found.evidence = {**(found.evidence or {}), **evidence}
        await db.flush()
        return found

    async def mission(self, db: AsyncSession, workspace_id: UUID, task_id: UUID) -> ArtifactNode:
        return await self.node(db, workspace_id, "mission", f"mission:{task_id}", title=f"Mission {str(task_id)[:8]}",
                               task_id=task_id)

    async def record_file(self, db: AsyncSession, workspace_id: UUID, task_id: Optional[UUID], path: str,
                          content: Optional[str] = None, *, operation: str = "write_file") -> Optional[ArtifactNode]:
        key = await self.file_key(db, workspace_id, path)
        if not key:
            return None
        kind = self.file_kind(key)
        node = await self.node(db, workspace_id, kind, key, title=key,
                               attrs={"last_operation": operation},
                               sha=_sha(content) if content is not None else None, task_id=task_id)
        if task_id is not None:
            await self.link(db, workspace_id, node, await self.mission(db, workspace_id, task_id), "changed_by",
                            task_id=task_id, evidence={"operation": operation,
                                                       "sha256": node.content_sha256})
        return node

    async def record_command(self, db: AsyncSession, workspace_id: UUID, task_id: Optional[UUID], command: str,
                             exit_code: Optional[int], *, cwd: Optional[str] = None) -> Optional[ArtifactNode]:
        command = " ".join(str(command or "").split())
        if not command:
            return None
        node = await self.node(db, workspace_id, "command", command[:500], title=command[:500],
                               attrs={"last_exit_code": exit_code}, task_id=task_id)
        if task_id is not None:
            await self.link(db, workspace_id, node, await self.mission(db, workspace_id, task_id), "run_in",
                            task_id=task_id, evidence={"exit_code": exit_code, "cwd": cwd})
        return node

    async def record_requirements(self, db: AsyncSession, workspace_id: UUID, task_id: UUID,
                                  requirements: Sequence[Dict[str, Any]]) -> List[ArtifactNode]:
        mission = await self.mission(db, workspace_id, task_id)
        nodes = []
        for r in requirements:
            node = await self.node(db, workspace_id, "requirement", f"{task_id}:{r['id']}",
                                   title=f"{r['id']}: {r['text']}"[:2000],
                                   attrs={"id": r["id"], "source": r.get("source"), "status": r.get("status")},
                                   task_id=task_id)
            await self.link(db, workspace_id, node, mission, "required_by", task_id=task_id,
                            evidence={"source": r.get("source")})
            nodes.append(node)
        return nodes

    async def record_verification(self, db: AsyncSession, workspace_id: UUID, task_id: UUID,
                                  requirements: Sequence[Dict[str, Any]], checks: Sequence[Dict[str, Any]],
                                  hard_findings: Sequence[Dict[str, Any]] = ()) -> Dict[str, int]:
        """The Verifier's evidence and the hard checks as edges. Returns counts of what was written."""
        counts = {"verifies": 0, "implements": 0, "contradicts": 0}
        touched = await self._touched(db, workspace_id, task_id)
        for r in requirements:
            pattern = re.compile(rf"\b{re.escape(r['id'])}\b", re.IGNORECASE)
            met = [c for c in checks if c.get("met") is True and str(c.get("evidence") or "").strip()
                   and (pattern.search(str(c.get("requirement") or ""))
                        or r["text"][:60].lower() in str(c.get("requirement") or "").lower())]
            if not met:
                continue
            requirement = await self.node(db, workspace_id, "requirement", f"{task_id}:{r['id']}",
                                          title=f"{r['id']}: {r['text']}"[:2000], task_id=task_id)
            for check in met:
                evidence = str(check.get("evidence"))[:1000]
                check_node = await self.node(db, workspace_id, "check", f"verifier:{task_id}:{r['id']}",
                                             title=f"Independent check of {r['id']}", attrs={"met": True},
                                             task_id=task_id)
                await self.link(db, workspace_id, check_node, requirement, "verifies", task_id=task_id,
                                evidence={"evidence": evidence})
                counts["verifies"] += 1
                for node in touched:
                    if node.key and node.key in evidence:
                        relation = "verifies" if node.kind == "command" else "implements"
                        await self.link(db, workspace_id, node, requirement, relation, task_id=task_id,
                                        evidence={"named_in": evidence[:300]})
                        counts[relation] += 1
        for finding in hard_findings:
            check_node = await self.node(db, workspace_id, "check", f"hard:{finding['check']}:{finding['file']}",
                                         title=f"Hard check {finding['check']} on {finding['file']}",
                                         attrs={"detail": finding.get("detail"), "passing": False}, task_id=task_id)
            target = await self.node(db, workspace_id, self.file_kind(finding["file"]), finding["file"],
                                     title=finding["file"])
            await self.link(db, workspace_id, check_node, target, "contradicts", task_id=task_id,
                            evidence={"detail": str(finding.get("detail"))[:1000]})
            counts["contradicts"] += 1
        return counts

    async def _touched(self, db: AsyncSession, workspace_id: UUID, task_id: UUID) -> List[ArtifactNode]:
        """Files, decisions and commands this mission wrote or ran."""
        mission = (await db.execute(select(ArtifactNode).where(
            ArtifactNode.workspace_id == workspace_id, ArtifactNode.kind == "mission",
            ArtifactNode.key == f"mission:{task_id}"))).scalar_one_or_none()
        if mission is None:
            return []
        sources = select(ArtifactEdge.source_id).where(
            ArtifactEdge.target_id == mission.id, ArtifactEdge.relation.in_(("changed_by", "run_in")))
        return list((await db.execute(select(ArtifactNode).where(ArtifactNode.id.in_(sources)))).scalars().all())

    # ----------------------------------------------------------------- reads

    async def trace(self, db: AsyncSession, workspace_id: UUID, key: str, *,
                    depth: int = MAX_DEPTH) -> Dict[str, Any]:
        """Everything within ``depth`` steps of the nodes matching ``key`` (exact, a path suffix, or a
        requirement id such as R3), in this workspace only."""
        key = str(key or "").strip().replace("\\", "/")
        if not key:
            return {"nodes": [], "edges": []}
        start = list((await db.execute(select(ArtifactNode).where(
            ArtifactNode.workspace_id == workspace_id,
            or_(ArtifactNode.key == key, ArtifactNode.key.endswith("/" + key.lstrip("/")),
                ArtifactNode.key.endswith(":" + key))))).scalars().all())
        nodes: Dict[UUID, ArtifactNode] = {n.id: n for n in start}
        edges: Dict[UUID, ArtifactEdge] = {}
        frontier: Set[UUID] = set(nodes)
        for _ in range(max(1, min(depth, MAX_DEPTH))):
            if not frontier or len(nodes) >= MAX_TRACE_NODES:
                break
            found = (await db.execute(select(ArtifactEdge).where(
                ArtifactEdge.workspace_id == workspace_id,
                or_(ArtifactEdge.source_id.in_(frontier), ArtifactEdge.target_id.in_(frontier))))).scalars().all()
            new_ids: Set[UUID] = set()
            for edge in found:
                edges[edge.id] = edge
                for nid in (edge.source_id, edge.target_id):
                    if nid not in nodes:
                        new_ids.add(nid)
            if new_ids:
                for node in (await db.execute(select(ArtifactNode).where(
                        ArtifactNode.workspace_id == workspace_id, ArtifactNode.id.in_(new_ids)))).scalars().all():
                    nodes[node.id] = node
            frontier = new_ids
        return {
            "nodes": [{"id": str(n.id), "kind": n.kind, "key": n.key, "title": n.title, "attrs": n.attrs}
                      for n in list(nodes.values())[:MAX_TRACE_NODES]],
            "edges": [{"from": str(e.source_id), "to": str(e.target_id), "relation": e.relation,
                       "task_id": str(e.task_id) if e.task_id else None, "evidence": e.evidence}
                      for e in edges.values() if e.source_id in nodes and e.target_id in nodes],
        }

    @staticmethod
    def describe(trace: Dict[str, Any], limit: int = 40) -> str:
        """A trace as plain lines: 'file apps/web/package.json —implements→ requirement R4: ...'."""
        by_id = {n["id"]: n for n in trace.get("nodes", [])}
        lines = []
        for e in trace.get("edges", [])[:limit]:
            a, b = by_id.get(e["from"]), by_id.get(e["to"])
            if a and b:
                lines.append(f"{a['kind']} {a['title'][:120]} —{e['relation']}→ {b['kind']} {b['title'][:120]}")
        return "\n".join(lines) or "Nothing is recorded for that yet."

    # --------------------------------------------------------------- backfill

    async def backfill(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, int]:
        """Build the graph from the workspace's FileChange and CommandRun rows (missions that set task_id in
        meta_data). Idempotent: nodes and edges are matched on their keys, so a second run adds nothing."""
        from app.models.execution import CommandRun, FileChange
        from app.models.task import Task

        tasks = {str(t) for t in (await db.execute(select(Task.id).where(
            Task.workspace_id == workspace_id))).scalars().all()}
        counts = {"files": 0, "commands": 0}
        for change in (await db.execute(select(FileChange).where(FileChange.success.is_(True)))).scalars().all():
            meta = change.meta_data or {}
            if str(meta.get("task_id")) not in tasks:
                continue
            await self.record_file(db, workspace_id, UUID(str(meta["task_id"])),
                                   meta.get("host_path") or change.file_path, change.new_content,
                                   operation=change.operation or "write_file")
            counts["files"] += 1
        for run in (await db.execute(select(CommandRun))).scalars().all():
            meta = run.meta_data or {}
            if str(meta.get("task_id")) not in tasks:
                continue
            await self.record_command(db, workspace_id, UUID(str(meta["task_id"])), run.command, run.exit_code,
                                      cwd=run.working_directory)
            counts["commands"] += 1
        return counts


graph_service = GraphService()
