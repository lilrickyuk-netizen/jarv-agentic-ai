"""
JARV Backend - Verified learning

How JARV learns from experience without learning the wrong thing:

1. Capture. Every agent run and command-center mission is stored as an
   ``ExperienceRecord`` (situation, action, result, outcome) and as an
   experience memory.
2. Extract. Each record carries one lesson. A caller may supply it; otherwise
   it is derived from the record itself, never invented.
3. Cluster. Lessons from similar situations in the same workspace and agent
   share a ``lesson_key`` (semantic similarity on the local embedder).
4. Verify. A lesson only becomes guidance when it passes the self-evolution
   safety guard AND either (a) at least ``MIN_EVIDENCE`` independent
   experiences agree with it, or (b) a human approves it. Unsafe lessons are
   rejected and can never be approved.
5. Apply. Verified lessons are retrieved for relevant tasks and given to the
   agent as labelled guidance, below system and safety rules.
6. Monitor and roll back. Each application records whether the task
   succeeded. A lesson whose success rate falls below ``RETIRE_BELOW`` after
   ``RETIRE_AFTER`` applications is retired automatically. Activation and
   retirement are both versioned ``SelfEvolutionRecord`` entries, so every
   change is reversible and auditable.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jarv_memory import _as_uuid, memory_service
from app.core.memory.embeddings import cosine_similarity, local_hash_embedding
from app.core.safety.evolution_guard import classify_change
from app.core.security import redact_text
from app.models.agent import Agent
from app.models.self_evolution import ExperienceRecord, SelfEvolutionRecord

logger = logging.getLogger(__name__)

MIN_EVIDENCE = 2          # independent agreeing experiences before a lesson is used
AGREEMENT = 0.66          # share of the cluster that must agree with the lesson
CLUSTER_SIMILARITY = 0.5  # situations at least this similar count as the same lesson
RELEVANCE = 0.12          # minimum similarity for a verified lesson to be offered
RETIRE_AFTER = 4          # applications before performance can retire a lesson
RETIRE_BELOW = 0.5        # retire when the observed success rate falls below this

_OUTCOMES = {"success", "failure", "partial"}
_SPACE_RE = re.compile(r"\s+")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(text: Optional[str], limit: int) -> str:
    text = _SPACE_RE.sub(" ", (text or "").strip())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def normalise_outcome(outcome: Optional[str]) -> str:
    value = (outcome or "").strip().lower()
    if value in {"completed", "complete", "succeeded", "ok", "passed", "success"}:
        return "success"
    if value in {"failed", "error", "errored", "timeout", "cancelled", "blocked", "failure"}:
        return "failure"
    if value in _OUTCOMES:
        return value
    return "partial"


def derive_lesson(agent_name: str, situation: str, action: str, result: str, outcome: str) -> str:
    """A lesson stated only in terms of what was observed in this record."""
    topic = _clip(situation, 140)
    did = _clip(action, 160)
    got = _clip(result, 160)
    if outcome == "success":
        return f"For tasks like \"{topic}\", {agent_name} succeeded by: {did}."
    if outcome == "failure":
        return (f"For tasks like \"{topic}\", {agent_name}'s approach ({did}) failed with: {got}. "
                "Check for this cause first or use a different approach.")
    return f"For tasks like \"{topic}\", {agent_name} only partly succeeded by: {did}. Result: {got}."


def _new_key(lesson: str) -> str:
    return hashlib.sha256(_clip(lesson, 2000).lower().encode("utf-8")).hexdigest()[:32]


class LearningService:
    """Experience capture, lesson verification, application, and rollback."""

    # ----- capture -----------------------------------------------------------

    async def record_experience(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID,
        agent_name: str,
        situation: str,
        action: str,
        result: str,
        outcome: str,
        task_id: Optional[UUID] = None,
        lesson: Optional[str] = None,
        experience_type: Optional[str] = None,
        tools_used: Optional[Sequence[str]] = None,
        agent_id: Optional[UUID] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> ExperienceRecord:
        workspace_id = _as_uuid(workspace_id)
        if workspace_id is None:
            raise ValueError("Experiences are always recorded inside a workspace")
        outcome = normalise_outcome(outcome)
        situation, action, result = (redact_text(situation or ""), redact_text(action or ""),
                                     redact_text(result or ""))
        lesson = redact_text(lesson) if lesson else None
        agent_name = (agent_name or "orchestrator").strip()[:100]
        lesson_text = _clip(lesson, 2000) if lesson else derive_lesson(
            agent_name, situation, action, result, outcome)
        unsafe, matched = classify_change(lesson_text)
        key = await self._cluster_key(db, workspace_id, agent_name, situation, lesson_text)
        owner = None
        if agent_id is not None:
            # Attribute to the agent that ran only if it really belongs to this workspace.
            owner = (await db.execute(select(Agent.id).where(
                Agent.id == _as_uuid(agent_id), Agent.workspace_id == workspace_id,
            ))).scalar_one_or_none()
        owner = owner or await memory_service._agent_id(db, workspace_id)

        record = ExperienceRecord(
            id=uuid4(),
            agent_id=owner,
            task_id=_as_uuid(task_id),
            workspace_id=workspace_id,
            agent_name=agent_name,
            experience_type=(experience_type or outcome)[:50],
            title=_clip(f"{agent_name}: {situation}", 480),
            description=_clip(f"{action} -> {outcome}", 2000),
            situation=_clip(situation, 4000) or "(not recorded)",
            action_taken=_clip(action, 4000) or "(not recorded)",
            result=_clip(result, 4000) or "(not recorded)",
            outcome=outcome,
            lesson_learned=lesson_text,
            applicable_contexts=[agent_name],
            confidence_score=0.3,
            times_applied=0,
            success_rate=None,
            is_validated=False,
            is_active=not unsafe,
            lesson_status="rejected" if unsafe else "candidate",
            lesson_key=key,
            created_at=_now(),
            updated_at=_now(),
            meta_data={
                **(meta or {}),
                "polarity": outcome,
                "situation_text": _clip(situation, 600),
                "tools_used": list(tools_used or []),
                "lesson_source": "provided" if lesson else "derived_from_record",
                **({"rejected_reason": f"safety guard: '{matched}'"} if unsafe else {}),
            },
        )
        db.add(record)
        await db.flush()

        try:
            await memory_service.add(
                db,
                content=_clip(f"[{outcome}] {agent_name}: {situation} | {action} | {result}", 1200),
                memory_type="experience",
                category="experience",
                workspace_id=workspace_id,
                task_id=task_id,
                importance=0.65 if outcome == "failure" else 0.5,
                confidence=0.6,
                source_ref=f"experience:{record.id}",
                agent_id=owner,
                meta={"experience_id": str(record.id), "agent": agent_name},
            )
        except Exception as exc:  # noqa: BLE001 - the experience row itself is already stored
            logger.warning(f"experience memory write failed: {exc}")

        if not unsafe:
            await self._maybe_verify(db, workspace_id, key)
        return record

    async def _cluster_key(
        self, db: AsyncSession, workspace_id: UUID, agent_name: str, situation: str, lesson: str,
    ) -> str:
        """Reuse the key of the most similar existing situation, else mint a new one."""
        probe = local_hash_embedding(situation or lesson)
        rows = (await db.execute(
            select(ExperienceRecord.lesson_key, ExperienceRecord.meta_data, ExperienceRecord.situation)
            .where(
                ExperienceRecord.workspace_id == workspace_id,
                ExperienceRecord.agent_name == agent_name,
                ExperienceRecord.lesson_key.is_not(None),
                ExperienceRecord.lesson_status.in_(("candidate", "verified")),
            )
            .order_by(ExperienceRecord.created_at.desc())
            .limit(300)
        )).all()
        best_key, best_score = None, 0.0
        for key, meta, stored_situation in rows:
            text = (meta or {}).get("situation_text") or stored_situation
            score = cosine_similarity(probe, local_hash_embedding(text))
            if score > best_score:
                best_key, best_score = key, score
        return best_key if best_key and best_score >= CLUSTER_SIMILARITY else _new_key(lesson)

    # ----- verify ------------------------------------------------------------

    async def _cluster(self, db: AsyncSession, workspace_id: UUID, key: str) -> List[ExperienceRecord]:
        return list((await db.execute(
            select(ExperienceRecord)
            .where(ExperienceRecord.workspace_id == workspace_id, ExperienceRecord.lesson_key == key)
            .order_by(ExperienceRecord.created_at.asc())
        )).scalars().all())

    async def _maybe_verify(self, db: AsyncSession, workspace_id: UUID, key: str) -> Optional[str]:
        cluster = [r for r in await self._cluster(db, workspace_id, key) if r.lesson_status != "rejected"]
        if not cluster or any(r.lesson_status in ("verified", "retired") for r in cluster):
            return None
        latest = cluster[-1]
        polarity = latest.outcome
        agreeing = [r for r in cluster if r.outcome == polarity]
        independent = {str(r.task_id) if r.task_id else str(r.id) for r in agreeing}
        if len(independent) < MIN_EVIDENCE or len(agreeing) / len(cluster) < AGREEMENT:
            return None
        await self._activate(db, workspace_id, key, cluster, latest,
                             method="evidence", evidence=[str(r.id) for r in agreeing])
        return key

    async def _activate(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        key: str,
        cluster: List[ExperienceRecord],
        canonical: ExperienceRecord,
        *,
        method: str,
        evidence: List[str],
        approver: Optional[str] = None,
    ) -> SelfEvolutionRecord:
        version = await self._next_version(db, key)
        for record in cluster:
            record.lesson_status = "verified"
            record.is_validated = True
            record.is_active = record.id == canonical.id
            record.confidence_score = min(0.95, 0.4 + 0.15 * len(evidence))
            record.updated_at = _now()
        canonical.meta_data = {**(canonical.meta_data or {}), "canonical": True,
                               "verified_by": method, "evidence_ids": evidence,
                               "verified_at": _now().isoformat(),
                               **({"approver": approver} if approver else {})}
        evolution = SelfEvolutionRecord(
            id=uuid4(),
            created_at=_now(),
            updated_at=_now(),
            agent_id=canonical.agent_id,
            evolution_type="lesson_activation",
            title=_clip(f"Verified lesson v{version} for {canonical.agent_name}", 480),
            description=canonical.lesson_learned,
            previous_state={"lesson_key": key, "status": "candidate"},
            new_state={"lesson_key": key, "status": "verified", "lesson": canonical.lesson_learned,
                       "experience_id": str(canonical.id)},
            changes=[{"field": "agent_guidance", "action": "add", "lesson_key": key}],
            trigger=method,
            reasoning=(f"{len(evidence)} agreeing experience(s) in this workspace"
                       if method == "evidence" else f"approved by {approver}"),
            expected_benefit="Agent reuses an approach that verifiably worked, or avoids one that failed.",
            requires_verification=True,
            verification_status="verified",
            status="applied",
            is_applied=True,
            applied_at=_now(),
            meta_data={"workspace_id": str(workspace_id), "lesson_key": key, "version": version,
                       "evidence_ids": evidence, "agent_name": canonical.agent_name},
        )
        db.add(evolution)
        await db.flush()
        return evolution

    async def _next_version(self, db: AsyncSession, key: str) -> int:
        rows = (await db.execute(
            select(SelfEvolutionRecord.meta_data)
            .where(SelfEvolutionRecord.evolution_type.in_(
                ("lesson_activation", "lesson_retirement", "workflow_proposal")))
            .order_by(SelfEvolutionRecord.created_at.desc())
            .limit(500)
        )).scalars().all()
        versions = [int((m or {}).get("version", 0)) for m in rows if (m or {}).get("lesson_key") == key]
        return (max(versions) if versions else 0) + 1

    async def approve_lesson(
        self, db: AsyncSession, experience_id: UUID, workspace_id: UUID, approver: str,
    ) -> ExperienceRecord:
        """Human verification. Unsafe lessons cannot be approved."""
        record = await self._get(db, experience_id, workspace_id)
        unsafe, matched = classify_change(record.lesson_learned)
        if unsafe or record.lesson_status == "rejected":
            raise PermissionError(f"Lesson is blocked by the safety guard ({matched or 'rejected'})")
        if record.lesson_status == "verified":
            return record
        if not record.lesson_key:
            record.lesson_key = _new_key(record.lesson_learned)
        cluster = [r for r in await self._cluster(db, workspace_id, record.lesson_key)
                   if r.lesson_status != "rejected"]
        if record not in cluster:
            cluster.append(record)
        await self._activate(db, workspace_id, record.lesson_key, cluster, record,
                             method="human_approval", evidence=[str(r.id) for r in cluster],
                             approver=approver)
        return record

    async def reject_lesson(
        self, db: AsyncSession, experience_id: UUID, workspace_id: UUID, reason: str,
    ) -> ExperienceRecord:
        record = await self._get(db, experience_id, workspace_id)
        if record.lesson_status == "verified":
            await self.retire(db, workspace_id, record.lesson_key, reason=f"rejected: {reason}")
        for row in await self._cluster(db, workspace_id, record.lesson_key):
            row.lesson_status = "rejected"
            row.is_active = False
            row.meta_data = {**(row.meta_data or {}), "rejected_reason": _clip(reason, 500)}
            row.updated_at = _now()
        await db.flush()
        return record

    async def _get(self, db: AsyncSession, experience_id: UUID, workspace_id: UUID) -> ExperienceRecord:
        record = (await db.execute(
            select(ExperienceRecord).where(
                ExperienceRecord.id == _as_uuid(experience_id),
                ExperienceRecord.workspace_id == _as_uuid(workspace_id),
            )
        )).scalar_one_or_none()
        if record is None:
            raise LookupError("Experience not found in this workspace")
        return record

    # ----- apply ---------------------------------------------------------------

    async def retrieve_lessons(
        self,
        db: AsyncSession,
        *,
        workspace_id: UUID,
        agent_name: str,
        query: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """Verified, active, relevant lessons for this agent in this workspace."""
        workspace_id = _as_uuid(workspace_id)
        if workspace_id is None or not (query or "").strip():
            return []
        rows = (await db.execute(
            select(ExperienceRecord).where(
                ExperienceRecord.workspace_id == workspace_id,
                ExperienceRecord.agent_name == agent_name,
                ExperienceRecord.lesson_status == "verified",
                ExperienceRecord.is_active.is_(True),
            ).limit(200)
        )).scalars().all()
        probe = local_hash_embedding(query)
        scored = []
        for row in rows:
            situation = (row.meta_data or {}).get("situation_text") or row.situation
            relevance = max(cosine_similarity(probe, local_hash_embedding(situation)),
                            cosine_similarity(probe, local_hash_embedding(row.lesson_learned)))
            if relevance >= RELEVANCE:
                scored.append((relevance, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{
            "id": str(row.id),
            "lesson_key": row.lesson_key,
            "lesson": row.lesson_learned,
            "polarity": row.outcome,
            "times_applied": row.times_applied,
            "success_rate": row.success_rate,
            "relevance": round(relevance, 3),
        } for relevance, row in scored[:limit]]

    async def record_application(
        self, db: AsyncSession, *, workspace_id: UUID, lesson_keys: Iterable[str], success: bool,
    ) -> List[str]:
        """Record whether a task that used these lessons succeeded. Returns retired keys."""
        retired: List[str] = []
        workspace_id = _as_uuid(workspace_id)
        for key in {k for k in lesson_keys if k}:
            canonical = (await db.execute(
                select(ExperienceRecord).where(
                    ExperienceRecord.workspace_id == workspace_id,
                    ExperienceRecord.lesson_key == key,
                    ExperienceRecord.lesson_status == "verified",
                    ExperienceRecord.is_active.is_(True),
                ).limit(1)
            )).scalar_one_or_none()
            if canonical is None:
                continue
            meta = dict(canonical.meta_data or {})
            successes = int(meta.get("applied_successes", 0)) + (1 if success else 0)
            canonical.times_applied = (canonical.times_applied or 0) + 1
            canonical.success_rate = successes / canonical.times_applied
            canonical.meta_data = {**meta, "applied_successes": successes,
                                   "last_applied_at": _now().isoformat()}
            canonical.updated_at = _now()
            if canonical.times_applied >= RETIRE_AFTER and canonical.success_rate < RETIRE_BELOW:
                await self.retire(
                    db, workspace_id, key,
                    reason=(f"success rate {canonical.success_rate:.0%} over "
                            f"{canonical.times_applied} applications is below {RETIRE_BELOW:.0%}"),
                )
                retired.append(key)
        await db.flush()
        return retired

    # ----- roll back -------------------------------------------------------

    async def retire(self, db: AsyncSession, workspace_id: UUID, key: str, *, reason: str) -> bool:
        """Withdraw a verified lesson and record the rollback."""
        workspace_id = _as_uuid(workspace_id)
        cluster = await self._cluster(db, workspace_id, key)
        verified = [r for r in cluster if r.lesson_status == "verified"]
        if not verified:
            return False
        for record in verified:
            record.lesson_status = "retired"
            record.is_active = False
            record.meta_data = {**(record.meta_data or {}), "retired_reason": _clip(reason, 500),
                                "retired_at": _now().isoformat()}
            record.updated_at = _now()
        activations = (await db.execute(
            select(SelfEvolutionRecord)
            .where(SelfEvolutionRecord.evolution_type == "lesson_activation",
                   SelfEvolutionRecord.is_rolled_back.is_(False))
            .order_by(SelfEvolutionRecord.created_at.desc()).limit(500)
        )).scalars().all()
        for activation in activations:
            meta = activation.meta_data or {}
            if meta.get("lesson_key") == key and meta.get("workspace_id") == str(workspace_id):
                activation.is_rolled_back = True
                activation.rollback_reason = _clip(reason, 1000)
                activation.rolled_back_at = _now()
                activation.is_successful = False
                activation.updated_at = _now()
        canonical = next((r for r in verified if (r.meta_data or {}).get("canonical")), verified[-1])
        db.add(SelfEvolutionRecord(
            id=uuid4(),
            created_at=_now(),
            updated_at=_now(),
            agent_id=canonical.agent_id,
            evolution_type="lesson_retirement",
            title=_clip(f"Retired lesson for {canonical.agent_name}", 480),
            description=canonical.lesson_learned,
            previous_state={"lesson_key": key, "status": "verified"},
            new_state={"lesson_key": key, "status": "retired"},
            changes=[{"field": "agent_guidance", "action": "remove", "lesson_key": key}],
            trigger="performance_monitor",
            reasoning=_clip(reason, 2000),
            expected_benefit="Stops agents from following guidance that no longer works.",
            requires_verification=False,
            verification_status="verified",
            status="applied",
            is_applied=True,
            applied_at=_now(),
            meta_data={"workspace_id": str(workspace_id), "lesson_key": key,
                       "version": await self._next_version(db, key)},
        ))
        await db.flush()
        return True

    # ----- proposals --------------------------------------------------------

    async def record_proposal(
        self, db: AsyncSession, *, workspace_id: UUID, proposal: str, task_id: Optional[UUID] = None,
    ) -> SelfEvolutionRecord:
        """Version a self-evolution proposal. Unsafe proposals are stored as blocked;
        safe ones are stored as accepted proposals awaiting verification. Nothing is
        marked applied here: a proposal changes behaviour only after it is verified."""
        workspace_id = _as_uuid(workspace_id)
        proposal = redact_text(_clip(proposal, 4000))
        unsafe, matched = classify_change(proposal)
        key = "proposal:" + _new_key(proposal)
        record = SelfEvolutionRecord(
            id=uuid4(),
            created_at=_now(),
            updated_at=_now(),
            agent_id=await memory_service._agent_id(db, workspace_id),
            evolution_type="workflow_proposal",
            title=_clip(f"Self-evolution proposal: {proposal}", 480),
            description=proposal,
            previous_state={},
            new_state={"proposal": proposal},
            changes=[{"field": "workflow", "action": "propose"}],
            trigger="command_center",
            reasoning=f"Blocked by safety guard: '{matched}'" if unsafe else "Passed the safety guard",
            expected_benefit="Recorded for verification before it can change behaviour.",
            requires_verification=True,
            verification_status="rejected" if unsafe else "pending",
            status="blocked" if unsafe else "accepted",
            is_applied=False,
            meta_data={"workspace_id": str(workspace_id), "lesson_key": key,
                       "version": await self._next_version(db, key),
                       "task_id": str(task_id) if task_id else None},
        )
        db.add(record)
        await db.flush()
        return record

    # ----- reporting -------------------------------------------------------

    async def stats(self, db: AsyncSession, workspace_ids: Sequence[UUID]) -> Dict[str, Any]:
        if not workspace_ids:
            return {"total": 0, "by_status": {}, "by_outcome": {}}
        rows = (await db.execute(
            select(ExperienceRecord.lesson_status, ExperienceRecord.outcome, func.count())
            .where(ExperienceRecord.workspace_id.in_(list(workspace_ids)))
            .group_by(ExperienceRecord.lesson_status, ExperienceRecord.outcome)
        )).all()
        by_status: Dict[str, int] = {}
        by_outcome: Dict[str, int] = {}
        for status, outcome, count in rows:
            by_status[status] = by_status.get(status, 0) + count
            by_outcome[outcome] = by_outcome.get(outcome, 0) + count
        return {"total": sum(by_status.values()), "by_status": by_status, "by_outcome": by_outcome}


learning_service = LearningService()
