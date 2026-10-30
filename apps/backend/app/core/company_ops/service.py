"""
JARV Backend - Company operations service

Every method reads and writes the real company tables for one workspace:
OperatingPlan / OperatingPlanVersion, DailyOperatingLoop, WeeklyExecutionPlan,
AIStandup, KPIRecord, RiskRegisterItem, DecisionLogItem and
LiveOperationsFeedItem. Standups, daily loops and next-best-actions are
computed from the workspace's actual tasks, approvals, incidents, risks, KPIs
and plans; nothing is invented. Callers own the transaction (flush only).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.boundary import BoundaryApproval
from app.models.company_operations import (
    AIStandup,
    DecisionLogItem,
    KPIRecord,
    LiveOperationsFeedItem,
    RiskRegisterItem,
)
from app.models.operating_plan import (
    DailyOperatingLoop,
    OperatingPlan,
    OperatingPlanVersion,
    WeeklyExecutionPlan,
)
from app.models.operations import Incident
from app.models.task import Task

logger = logging.getLogger(__name__)

LEVELS = {"very_low": 1, "low": 2, "medium": 3, "high": 4, "very_high": 5, "critical": 5}
DONE = {"done", "completed", "complete", "achieved"}
SEVERITIES = {"info", "success", "warning", "error", "critical"}
DEFAULT_LOOP_ACTIVITIES = ["standup", "next_best_actions", "kpi_snapshot", "risk_review", "plan_progress"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _day(value: Any, default: Optional[date] = None) -> date:
    if value is None or value == "":
        if default is None:
            raise ValueError("A date is required")
        return default
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f"'{value}' is not a date (use YYYY-MM-DD)") from None


def _decimal(value: Any, what: str) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{what} must be a number") from None


def _level(value: Any, what: str) -> int:
    if isinstance(value, (int, float)) and 1 <= int(value) <= 5:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit() and 1 <= int(value) <= 5:
        return int(value)
    key = str(value or "").strip().lower().replace(" ", "_")
    if key not in LEVELS:
        raise ValueError(f"{what} must be one of {', '.join(k for k in LEVELS if k != 'critical')} or 1-5")
    return LEVELS[key]


def _items(values: Optional[Sequence[Any]], field: str = "title") -> List[Dict[str, Any]]:
    """Normalise objectives/milestones/deliverables: strings become {title, status: open}."""
    out: List[Dict[str, Any]] = []
    for value in values or []:
        if isinstance(value, str) and value.strip():
            out.append({field: value.strip(), "status": "open"})
        elif isinstance(value, dict) and (value.get(field) or value.get("title") or value.get("name")):
            item = dict(value)
            item[field] = str(item.get(field) or item.get("title") or item.get("name")).strip()
            item["status"] = str(item.get("status") or "open").lower()
            out.append(item)
    return out


def _progress(items: Sequence[Dict[str, Any]]) -> tuple[int, int, float]:
    total = len(items)
    done = sum(1 for i in items if str(i.get("status", "")).lower() in DONE)
    return done, total, round(100.0 * done / total, 1) if total else 0.0


def _merge(existing: List[Dict[str, Any]], changes: Optional[Sequence[Any]], field: str = "title") -> List[Dict[str, Any]]:
    """Apply changes by title: update matching items, append new ones, drop items marked remove."""
    if changes is None:
        return existing
    result = [dict(i) for i in existing]
    for raw, change in zip([c for c in changes if _items([c], field)], _items(changes, field)):
        if isinstance(raw, dict) and "status" not in raw:
            change.pop("status", None)  # an update without a status keeps the item's current status
        key = change[field].lower()
        match = next((i for i in result if str(i.get(field, "")).lower() == key), None)
        if change.get("remove"):
            result = [i for i in result if str(i.get(field, "")).lower() != key]
        elif match is not None:
            match.update({k: v for k, v in change.items() if k != "remove"})
        else:
            result.append({"status": "open", **{k: v for k, v in change.items() if k != "remove"}})
    return result


def plan_view(plan: OperatingPlan) -> Dict[str, Any]:
    return {"id": str(plan.id), "name": plan.plan_name, "type": plan.plan_type, "status": plan.status,
            "is_active": plan.is_active, "version": plan.current_version, "description": plan.description,
            "start_date": plan.start_date.isoformat(), "end_date": plan.end_date.isoformat(),
            "objectives": plan.objectives, "strategies": plan.strategies, "milestones": plan.milestones,
            "completion_percentage": plan.completion_percentage,
            "objectives_completed": plan.objectives_completed, "objectives_total": plan.objectives_total}


def loop_view(loop: DailyOperatingLoop) -> Dict[str, Any]:
    return {"id": str(loop.id), "date": loop.loop_date.isoformat(), "status": loop.status,
            "activities": loop.activities, "completed_activities": loop.completed_activities,
            "tasks_completed": loop.tasks_completed, "issues_resolved": loop.issues_resolved,
            "blockers": loop.blockers, "highlights": loop.highlights or [], "concerns": loop.concerns or [],
            "summary": loop.summary,
            "started_at": _aware(loop.started_at).isoformat() if loop.started_at else None,
            "completed_at": _aware(loop.completed_at).isoformat() if loop.completed_at else None}


def weekly_view(plan: WeeklyExecutionPlan) -> Dict[str, Any]:
    return {"id": str(plan.id), "week_start": plan.week_start_date.isoformat(),
            "week_end": plan.week_end_date.isoformat(), "week": plan.week_number, "year": plan.year,
            "status": plan.status, "objectives": plan.objectives, "priorities": plan.priorities,
            "deliverables": plan.deliverables, "completion_percentage": plan.completion_percentage,
            "objectives_completed": plan.objectives_completed, "review_notes": plan.review_notes,
            "lessons_learned": plan.lessons_learned or []}


def standup_view(row: AIStandup) -> Dict[str, Any]:
    return {"id": str(row.id), "date": row.standup_date.isoformat(),
            "agent_id": str(row.agent_id) if row.agent_id else None,
            "yesterday": row.yesterday_accomplishments, "today": row.today_plans, "blockers": row.blockers,
            "needs_help_with": row.needs_help_with or [], "tasks_completed": row.tasks_completed,
            "tasks_in_progress": row.tasks_in_progress, "tasks_planned": row.tasks_planned,
            "mood": row.mood, "confidence_level": row.confidence_level}


def kpi_view(row: KPIRecord) -> Dict[str, Any]:
    return {"id": str(row.id), "name": row.kpi_name, "type": row.kpi_type, "category": row.category,
            "value": float(row.value), "unit": row.unit,
            "target": float(row.target_value) if row.target_value is not None else None,
            "target_met": row.target_met, "period_start": row.period_start.isoformat(),
            "period_end": row.period_end.isoformat(), "period_type": row.period_type, "notes": row.notes}


def risk_view(row: RiskRegisterItem) -> Dict[str, Any]:
    return {"id": str(row.id), "title": row.risk_title, "description": row.risk_description,
            "category": row.risk_category, "probability": row.probability, "impact": row.impact,
            "score": row.risk_score, "mitigation_strategy": row.mitigation_strategy,
            "mitigation_actions": row.mitigation_actions or [], "status": row.status,
            "is_mitigated": row.is_mitigated, "identified": row.identified_date.isoformat(),
            "review_date": row.review_date.isoformat() if row.review_date else None,
            "closed_date": row.closed_date.isoformat() if row.closed_date else None}


def decision_view(row: DecisionLogItem) -> Dict[str, Any]:
    return {"id": str(row.id), "title": row.decision_title, "description": row.decision_description,
            "type": row.decision_type, "problem": row.problem_statement,
            "alternatives": row.alternatives_considered or [], "rationale": row.rationale,
            "impact": row.impact_assessment, "stakeholders": row.stakeholders or [],
            "date": row.decision_date.isoformat(), "status": row.status, "is_reversed": row.is_reversed,
            "reversal_reason": row.reversal_reason}


def feed_view(row: LiveOperationsFeedItem) -> Dict[str, Any]:
    return {"id": str(row.id), "type": row.item_type, "severity": row.severity, "title": row.title,
            "message": row.message, "is_read": row.is_read, "is_archived": row.is_archived,
            "requires_action": row.requires_action, "action_taken": row.action_taken,
            "created_at": _aware(row.created_at).isoformat() if row.created_at else None}


class CompanyOpsService:
    # ----- shared -----------------------------------------------------------------------

    async def _one(self, db: AsyncSession, model, row_id: Any, workspace_id: UUID):
        try:
            key = row_id if isinstance(row_id, UUID) else UUID(str(row_id))
        except (TypeError, ValueError):
            raise ValueError(f"'{row_id}' is not a valid id") from None
        row = (await db.execute(select(model).where(model.id == key, model.workspace_id == workspace_id))
               ).scalar_one_or_none()
        if row is None:
            raise LookupError(f"{model.__name__} not found in this workspace")
        return row

    async def post_feed(self, db: AsyncSession, workspace_id: UUID, *, item_type: str, title: str, message: str,
                        severity: str = "info", requires_action: bool = False, task_id: Optional[UUID] = None,
                        agent_id: Optional[UUID] = None, meta: Optional[Dict[str, Any]] = None
                        ) -> LiveOperationsFeedItem:
        severity = severity if severity in SEVERITIES else "info"
        now = _now()
        row = LiveOperationsFeedItem(
            id=uuid4(), workspace_id=workspace_id, item_type=item_type[:50], severity=severity,
            title=title[:500], message=message, related_agent_id=agent_id, related_task_id=task_id,
            requires_action=requires_action, meta_data=meta or {}, created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
        return row

    async def update_feed(self, db: AsyncSession, workspace_id: UUID, item_ids: Sequence[Any], *,
                          mark_read: Optional[bool] = None, archive: Optional[bool] = None,
                          action_taken: Optional[str] = None, actor: Optional[UUID] = None
                          ) -> List[LiveOperationsFeedItem]:
        rows = [await self._one(db, LiveOperationsFeedItem, i, workspace_id) for i in item_ids]
        for row in rows:
            if mark_read is not None:
                row.is_read = mark_read
            if archive is not None:
                row.is_archived = archive
            if action_taken:
                row.action_taken, row.action_taken_at, row.action_taken_by = action_taken, _now(), actor
                row.requires_action = False
                row.is_read = True
            row.updated_at = _now()
        await db.flush()
        return rows

    # ----- operating plans --------------------------------------------------------------

    async def create_operating_plan(self, db: AsyncSession, workspace_id: UUID, *, name: str, plan_type: str,
                                    start: Any, end: Any, description: Optional[str] = None,
                                    objectives: Optional[Sequence[Any]] = None,
                                    strategies: Optional[Sequence[Any]] = None,
                                    milestones: Optional[Sequence[Any]] = None, activate: bool = True,
                                    created_by: Optional[UUID] = None) -> OperatingPlan:
        start_date, end_date = _day(start), _day(end)
        if end_date < start_date:
            raise ValueError("The plan's end date is before its start date")
        objs, strats, miles = _items(objectives), _items(strategies), _items(milestones)
        done, total, pct = _progress(objs)
        now = _now()
        plan = OperatingPlan(
            id=uuid4(), workspace_id=workspace_id, plan_name=name[:255], plan_type=plan_type[:50],
            description=description, start_date=start_date, end_date=end_date, objectives=objs,
            strategies=strats, milestones=miles, status="active" if activate else "draft", is_active=activate,
            current_version=1, completion_percentage=pct, objectives_completed=done, objectives_total=total,
            created_by=created_by, meta_data={}, created_at=now, updated_at=now)
        if activate:
            await self._deactivate_plans(db, workspace_id, plan_type)
        db.add(plan)
        db.add(OperatingPlanVersion(id=uuid4(), plan_id=plan.id, version_number=1,
                                    version_description="Initial plan", objectives=objs, strategies=strats,
                                    milestones=miles, changed_by=created_by, change_summary="created",
                                    created_at=now, updated_at=now))
        await db.flush()
        return plan

    async def _deactivate_plans(self, db: AsyncSession, workspace_id: UUID, plan_type: str,
                                keep: Optional[UUID] = None) -> None:
        rows = (await db.execute(select(OperatingPlan).where(
            OperatingPlan.workspace_id == workspace_id, OperatingPlan.plan_type == plan_type,
            OperatingPlan.is_active.is_(True)))).scalars().all()
        for row in rows:
            if row.id != keep:
                row.is_active = False
                if row.status == "active":
                    row.status = "superseded"

    async def update_operating_plan(self, db: AsyncSession, workspace_id: UUID, plan_id: Any, *,
                                    change_summary: str, objectives: Optional[Sequence[Any]] = None,
                                    strategies: Optional[Sequence[Any]] = None,
                                    milestones: Optional[Sequence[Any]] = None, status: Optional[str] = None,
                                    description: Optional[str] = None, end: Any = None, activate: Optional[bool] = None,
                                    changed_by: Optional[UUID] = None) -> OperatingPlan:
        plan = await self._one(db, OperatingPlan, plan_id, workspace_id)
        plan.objectives = _merge(list(plan.objectives or []), objectives)
        plan.strategies = _merge(list(plan.strategies or []), strategies)
        plan.milestones = _merge(list(plan.milestones or []), milestones)
        if description is not None:
            plan.description = description
        if end:
            end_date = _day(end)
            if end_date < plan.start_date:
                raise ValueError("The plan's end date is before its start date")
            plan.end_date = end_date
        if status:
            plan.status = status[:50]
        if activate is not None:
            if activate:
                await self._deactivate_plans(db, workspace_id, plan.plan_type, keep=plan.id)
            plan.is_active = activate
        plan.objectives_completed, plan.objectives_total, plan.completion_percentage = _progress(plan.objectives)
        if plan.objectives_total and plan.objectives_completed == plan.objectives_total and plan.status == "active":
            plan.status = "completed"
        plan.current_version += 1
        now = _now()
        plan.updated_at = now
        db.add(OperatingPlanVersion(id=uuid4(), plan_id=plan.id, version_number=plan.current_version,
                                    version_description=change_summary[:2000], objectives=plan.objectives,
                                    strategies=plan.strategies, milestones=plan.milestones, changed_by=changed_by,
                                    change_summary=change_summary[:2000], created_at=now, updated_at=now))
        await db.flush()
        return plan

    async def plan_versions(self, db: AsyncSession, workspace_id: UUID, plan_id: Any) -> List[Dict[str, Any]]:
        plan = await self._one(db, OperatingPlan, plan_id, workspace_id)
        rows = (await db.execute(select(OperatingPlanVersion).where(OperatingPlanVersion.plan_id == plan.id)
                                 .order_by(OperatingPlanVersion.version_number))).scalars().all()
        return [{"version": r.version_number, "summary": r.change_summary,
                 "objectives": r.objectives, "milestones": r.milestones} for r in rows]

    async def active_plan(self, db: AsyncSession, workspace_id: UUID) -> Optional[OperatingPlan]:
        return (await db.execute(select(OperatingPlan).where(
            OperatingPlan.workspace_id == workspace_id, OperatingPlan.is_active.is_(True))
            .order_by(OperatingPlan.updated_at.desc()).limit(1))).scalar_one_or_none()

    # ----- weekly execution plans ------------------------------------------------------

    async def create_weekly_plan(self, db: AsyncSession, workspace_id: UUID, *, week_of: Any = None,
                                 objectives: Optional[Sequence[Any]] = None,
                                 priorities: Optional[Sequence[str]] = None,
                                 deliverables: Optional[Sequence[Any]] = None,
                                 created_by: Optional[UUID] = None) -> WeeklyExecutionPlan:
        day = _day(week_of, default=_now().date())
        start = day - timedelta(days=day.weekday())
        existing = (await db.execute(select(WeeklyExecutionPlan).where(
            WeeklyExecutionPlan.workspace_id == workspace_id, WeeklyExecutionPlan.week_start_date == start))
            ).scalar_one_or_none()
        if existing is not None:
            raise ValueError(f"A weekly execution plan for the week of {start.isoformat()} already exists "
                             f"({existing.id}); update it instead")
        objs = _items(objectives)
        done, _total, pct = _progress(objs)
        iso = start.isocalendar()
        now = _now()
        plan = WeeklyExecutionPlan(
            id=uuid4(), workspace_id=workspace_id, week_start_date=start, week_end_date=start + timedelta(days=6),
            week_number=iso[1], year=iso[0], objectives=objs,
            priorities=[str(p).strip() for p in priorities or [] if str(p).strip()],
            deliverables=_items(deliverables), status="active", completion_percentage=pct,
            objectives_completed=done, created_by=created_by, meta_data={}, created_at=now, updated_at=now)
        db.add(plan)
        await db.flush()
        return plan

    async def update_weekly_plan(self, db: AsyncSession, workspace_id: UUID, plan_id: Any, *,
                                 objectives: Optional[Sequence[Any]] = None,
                                 priorities: Optional[Sequence[str]] = None,
                                 deliverables: Optional[Sequence[Any]] = None, status: Optional[str] = None,
                                 review_notes: Optional[str] = None,
                                 lessons_learned: Optional[Sequence[str]] = None) -> WeeklyExecutionPlan:
        plan = await self._one(db, WeeklyExecutionPlan, plan_id, workspace_id)
        plan.objectives = _merge(list(plan.objectives or []), objectives)
        plan.deliverables = _merge(list(plan.deliverables or []), deliverables)
        if priorities is not None:
            plan.priorities = [str(p).strip() for p in priorities if str(p).strip()]
        if review_notes is not None:
            plan.review_notes = review_notes
        if lessons_learned:
            plan.lessons_learned = list(plan.lessons_learned or []) + [str(l) for l in lessons_learned]
        plan.objectives_completed, _total, plan.completion_percentage = _progress(plan.objectives)
        if status:
            plan.status = status[:50]
        plan.updated_at = _now()
        await db.flush()
        return plan

    # ----- workspace activity (real data) ------------------------------------------------

    async def _tasks(self, db: AsyncSession, workspace_id: UUID, *conditions) -> List[Task]:
        return list((await db.execute(select(Task).where(Task.workspace_id == workspace_id, *conditions)
                                      .order_by(Task.updated_at.desc()).limit(200))).scalars().all())

    async def activity(self, db: AsyncSession, workspace_id: UUID, since: datetime, until: datetime
                       ) -> Dict[str, Any]:
        """Tasks finished, failed and open, approvals waiting, and incidents in a window."""
        def within(dt):
            dt = _aware(dt)
            return dt is not None and since <= dt < until

        recent = await self._tasks(db, workspace_id, Task.updated_at >= since - timedelta(days=1))
        completed = [t for t in recent if t.status == "completed" and within(t.completed_at or t.updated_at)]
        failed = [t for t in recent if t.status == "failed" and within(t.failed_at or t.updated_at)]
        open_tasks = await self._tasks(db, workspace_id, Task.status.in_(
            ["pending", "queued", "running", "recovering", "needs_continuation"]))
        waiting = await self._tasks(db, workspace_id, Task.status.in_(["waiting_on_approval", "blocked"]))
        approvals = list((await db.execute(select(BoundaryApproval).where(
            BoundaryApproval.workspace_id == workspace_id, BoundaryApproval.status == "pending"))).scalars().all())
        incidents = list((await db.execute(select(Incident).where(Incident.workspace_id == workspace_id))
                          ).scalars().all())
        resolved = [i for i in incidents if within(i.resolved_at)]
        open_incidents = [i for i in incidents if i.status not in ("resolved", "closed")]
        return {"completed": completed, "failed": failed, "open": open_tasks, "waiting": waiting,
                "approvals": approvals, "resolved_incidents": resolved, "open_incidents": open_incidents}

    # ----- standups ------------------------------------------------------------------------

    async def create_standup(self, db: AsyncSession, workspace_id: UUID, *, standup_date: Any = None,
                             agent_id: Optional[UUID] = None, yesterday: Optional[Sequence[str]] = None,
                             today: Optional[Sequence[str]] = None, blockers: Optional[Sequence[str]] = None,
                             needs_help_with: Optional[Sequence[str]] = None, mood: Optional[str] = None
                             ) -> AIStandup:
        """A standup from the workspace's real activity over the last 24 hours (entries given are added)."""
        day = _day(standup_date, default=_now().date())
        until = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
        if day == _now().date():
            until = _now()
        act = await self.activity(db, workspace_id, until - timedelta(days=1), until)

        def mine(tasks):
            return [t for t in tasks if agent_id is None or t.assigned_agent_id == agent_id]

        done, failed, open_tasks, waiting = (mine(act["completed"]), mine(act["failed"]), mine(act["open"]),
                                             mine(act["waiting"]))
        auto_blockers = [f"Failed: {t.title} ({(t.error_message or 'no error recorded')[:160]})" for t in failed]
        auto_blockers += [f"Waiting on approval: {t.title}" for t in waiting if t.status == "waiting_on_approval"]
        auto_blockers += [f"Blocked: {t.title}" for t in waiting if t.status == "blocked"]
        if agent_id is None:
            auto_blockers += [f"Approval pending: {a.input_prompt or a.richard_input_type}"[:300]
                              for a in act["approvals"]]
        judged = len(done) + len(failed)
        now = _now()
        row = AIStandup(
            id=uuid4(), workspace_id=workspace_id, agent_id=agent_id, standup_date=day,
            yesterday_accomplishments=[t.title for t in done] + [str(s) for s in yesterday or []],
            today_plans=[t.title for t in open_tasks[:20]] + [str(s) for s in today or []],
            blockers=auto_blockers + [str(s) for s in blockers or []],
            needs_help_with=[str(s) for s in needs_help_with or []] or None,
            tasks_completed=len(done), tasks_in_progress=sum(1 for t in open_tasks if t.status == "running"),
            tasks_planned=sum(1 for t in open_tasks if t.status != "running"),
            mood=mood or ("blocked" if auto_blockers else "on_track"),
            confidence_level=round(len(done) / judged, 2) if judged else None,
            meta_data={"source": "workspace activity", "window_end": until.isoformat()},
            created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
        return row

    async def update_standup(self, db: AsyncSession, workspace_id: UUID, standup_id: Any, **changes: Any
                             ) -> AIStandup:
        row = await self._one(db, AIStandup, standup_id, workspace_id)
        for field, column in (("yesterday", "yesterday_accomplishments"), ("today", "today_plans"),
                              ("blockers", "blockers"), ("needs_help_with", "needs_help_with")):
            if changes.get(field) is not None:
                setattr(row, column, [str(s) for s in changes[field]])
        if changes.get("mood"):
            row.mood = str(changes["mood"])[:50]
        if changes.get("confidence_level") is not None:
            level = float(changes["confidence_level"])
            if not 0 <= level <= 1:
                raise ValueError("confidence_level is between 0 and 1")
            row.confidence_level = level
        row.updated_at = _now()
        await db.flush()
        return row

    # ----- KPIs ----------------------------------------------------------------------------

    async def record_kpi(self, db: AsyncSession, workspace_id: UUID, *, name: str, value: Any,
                         kpi_type: str = "operational", category: Optional[str] = None,
                         unit: Optional[str] = None, target: Any = None, higher_is_better: bool = True,
                         period_type: str = "daily", period_start: Any = None, period_end: Any = None,
                         notes: Optional[str] = None) -> KPIRecord:
        """Record a KPI value for its period (re-recording the same period updates it)."""
        amount = _decimal(value, f"{name} value")
        if amount is None:
            raise ValueError(f"{name} needs a value")
        start = _day(period_start, default=_now().date())
        end = _day(period_end, default=start)
        previous = await self.latest_kpi(db, workspace_id, name)
        target_value = _decimal(target, f"{name} target")
        if target_value is None and previous is not None:
            target_value = previous.target_value
        direction = higher_is_better if previous is None else bool((previous.meta_data or {}).get(
            "higher_is_better", higher_is_better))
        met = None if target_value is None else (amount >= target_value if direction else amount <= target_value)
        row = (await db.execute(select(KPIRecord).where(
            KPIRecord.workspace_id == workspace_id, KPIRecord.kpi_name == name, KPIRecord.period_start == start,
            KPIRecord.period_type == period_type))).scalar_one_or_none()
        now = _now()
        if row is None:
            row = KPIRecord(id=uuid4(), workspace_id=workspace_id, kpi_name=name[:255], created_at=now,
                            period_start=start, period_type=period_type[:50])
            db.add(row)
        row.kpi_type = kpi_type[:50]
        row.category = category or (previous.category if previous else None)
        row.value, row.unit = amount, unit or (previous.unit if previous else None)
        row.target_value, row.target_met, row.period_end = target_value, met, end
        row.notes, row.updated_at = notes, now
        row.meta_data = {"higher_is_better": direction}
        await db.flush()
        return row

    async def latest_kpi(self, db: AsyncSession, workspace_id: UUID, name: str) -> Optional[KPIRecord]:
        return (await db.execute(select(KPIRecord).where(
            KPIRecord.workspace_id == workspace_id, KPIRecord.kpi_name == name)
            .order_by(KPIRecord.period_start.desc(), KPIRecord.updated_at.desc()).limit(1))).scalar_one_or_none()

    async def kpi_dashboard(self, db: AsyncSession, workspace_id: UUID) -> List[Dict[str, Any]]:
        """Latest value of every KPI, with the previous value and the change."""
        rows = (await db.execute(select(KPIRecord).where(KPIRecord.workspace_id == workspace_id)
                                 .order_by(KPIRecord.kpi_name, KPIRecord.period_start.desc()))).scalars().all()
        board: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            entry = board.get(row.kpi_name)
            if entry is None:
                board[row.kpi_name] = {**kpi_view(row), "previous": None, "change": None, "history": 1}
            else:
                entry["history"] += 1
                if entry["previous"] is None:
                    entry["previous"] = float(row.value)
                    entry["change"] = round(entry["value"] - float(row.value), 4)
        return list(board.values())

    # ----- risks ---------------------------------------------------------------------------

    async def create_risk(self, db: AsyncSession, workspace_id: UUID, *, title: str, description: str,
                          category: str, probability: Any, impact: Any, mitigation_strategy: Optional[str] = None,
                          mitigation_actions: Optional[Sequence[str]] = None, owner_id: Optional[UUID] = None,
                          review_date: Any = None) -> RiskRegisterItem:
        p, i = _level(probability, "probability"), _level(impact, "impact")
        now = _now()
        row = RiskRegisterItem(
            id=uuid4(), workspace_id=workspace_id, risk_title=title[:500], risk_description=description,
            risk_category=category[:50], probability=str(probability), impact=str(impact), risk_score=float(p * i),
            mitigation_strategy=mitigation_strategy, mitigation_actions=list(mitigation_actions or []) or None,
            owner_id=owner_id, status="open", is_mitigated=False, identified_date=now.date(),
            review_date=_day(review_date) if review_date else now.date() + timedelta(days=14),
            meta_data={"probability_level": p, "impact_level": i}, created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
        return row

    async def update_risk(self, db: AsyncSession, workspace_id: UUID, risk_id: Any, **changes: Any
                          ) -> RiskRegisterItem:
        row = await self._one(db, RiskRegisterItem, risk_id, workspace_id)
        meta = dict(row.meta_data or {})
        if changes.get("probability") is not None:
            meta["probability_level"] = _level(changes["probability"], "probability")
            row.probability = str(changes["probability"])
        if changes.get("impact") is not None:
            meta["impact_level"] = _level(changes["impact"], "impact")
            row.impact = str(changes["impact"])
        p = meta.get("probability_level") or _level(row.probability, "probability")
        i = meta.get("impact_level") or _level(row.impact, "impact")
        row.risk_score, row.meta_data = float(p * i), meta
        if changes.get("mitigation_strategy") is not None:
            row.mitigation_strategy = changes["mitigation_strategy"]
        if changes.get("mitigation_actions") is not None:
            row.mitigation_actions = list(row.mitigation_actions or []) + [str(a) for a in changes["mitigation_actions"]]
        if changes.get("review_date"):
            row.review_date = _day(changes["review_date"])
        status = changes.get("status")
        if status:
            row.status = str(status)[:50]
            row.is_mitigated = status in ("mitigated", "closed")
            row.closed_date = _now().date() if status == "closed" else None
        row.updated_at = _now()
        await db.flush()
        return row

    async def risks(self, db: AsyncSession, workspace_id: UUID, include_closed: bool = False) -> List[RiskRegisterItem]:
        query = select(RiskRegisterItem).where(RiskRegisterItem.workspace_id == workspace_id)
        if not include_closed:
            query = query.where(RiskRegisterItem.status != "closed")
        return list((await db.execute(query.order_by(RiskRegisterItem.risk_score.desc()))).scalars().all())

    # ----- decisions -------------------------------------------------------------------------

    async def log_decision(self, db: AsyncSession, workspace_id: UUID, *, title: str, description: str,
                           decision_type: str, rationale: Optional[str] = None, problem: Optional[str] = None,
                           alternatives: Optional[Sequence[str]] = None, impact: Optional[str] = None,
                           stakeholders: Optional[Sequence[str]] = None, made_by: Optional[UUID] = None,
                           agent: Optional[str] = None) -> DecisionLogItem:
        now = _now()
        row = DecisionLogItem(
            id=uuid4(), workspace_id=workspace_id, decision_title=title[:500], decision_description=description,
            decision_type=decision_type[:50], problem_statement=problem,
            alternatives_considered=list(alternatives or []) or None, rationale=rationale, decision_made_by=made_by,
            decision_date=now.date(), impact_assessment=impact, stakeholders=list(stakeholders or []) or None,
            status="active", is_reversed=False, meta_data={"agent": agent} if agent else {},
            created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
        return row

    async def update_decision(self, db: AsyncSession, workspace_id: UUID, decision_id: Any, *,
                              status: Optional[str] = None, rationale: Optional[str] = None,
                              impact: Optional[str] = None, reverse_reason: Optional[str] = None) -> DecisionLogItem:
        row = await self._one(db, DecisionLogItem, decision_id, workspace_id)
        if reverse_reason:
            if row.is_reversed:
                raise ValueError("This decision is already reversed")
            row.is_reversed, row.reversed_date, row.reversal_reason = True, _now().date(), reverse_reason
            row.status = "reversed"
        elif status:
            row.status = status[:50]
        if rationale is not None:
            row.rationale = rationale
        if impact is not None:
            row.impact_assessment = impact
        row.updated_at = _now()
        await db.flush()
        return row

    # ----- next best actions -------------------------------------------------------------

    async def next_best_actions(self, db: AsyncSession, workspace_id: UUID, limit: int = 10) -> List[Dict[str, Any]]:
        """Ranked actions drawn from what is actually open in the workspace."""
        now = _now()
        today = now.date()
        act = await self.activity(db, workspace_id, now - timedelta(days=7), now + timedelta(seconds=1))
        actions: List[Dict[str, Any]] = []

        def add(priority: int, action: str, reason: str, owner: str, ref: Optional[str] = None):
            actions.append({"priority": priority, "action": action, "reason": reason, "owner": owner, "ref": ref})

        for approval in act["approvals"]:
            expires = _aware(getattr(approval, "expires_at", None))
            if expires is None or expires > now:
                add(100, "Clear the pending approval gate",
                    (approval.input_prompt or approval.richard_input_type or "approval requested")[:300],
                    "richard", str(approval.id))
        for incident in act["open_incidents"]:
            weight = {"critical": 95, "high": 85, "medium": 60}.get(str(incident.severity).lower(), 40)
            add(weight, f"Resolve incident {incident.incident_number}: {incident.title}",
                f"{incident.severity} incident, status {incident.status}", "self_healing", str(incident.id))
        retried = {(t.meta_data or {}).get("retry_of") for t in act["open"] + act["completed"]}
        for task in act["failed"]:
            if str(task.id) not in retried:
                add(80, f"Investigate and retry: {task.title}",
                    (task.error_message or "failed without an error message")[:300], "debugging", str(task.id))
        for task in act["waiting"]:
            if task.status == "blocked":
                add(70, f"Unblock: {task.title}", "task is blocked", "orchestrator", str(task.id))
        for risk in await self.risks(db, workspace_id):
            if risk.risk_score >= 12 and not risk.mitigation_strategy:
                add(65, f"Write a mitigation for risk: {risk.risk_title}", f"score {risk.risk_score:g}, unmitigated",
                    "company_operator", str(risk.id))
            elif risk.review_date and risk.review_date <= today:
                add(50, f"Review risk: {risk.risk_title}", f"review was due {risk.review_date.isoformat()}",
                    "company_operator", str(risk.id))
        for kpi in await self.kpi_dashboard(db, workspace_id):
            if kpi["target_met"] is False:
                add(60, f"Recover KPI {kpi['name']}", f"{kpi['value']:g} against target {kpi['target']:g}",
                    "analytics", kpi["id"])
        plan = await self.active_plan(db, workspace_id)
        if plan is not None:
            for milestone in plan.milestones or []:
                due = milestone.get("due") or milestone.get("target_date")
                if due and str(milestone.get("status", "")).lower() not in DONE:
                    try:
                        overdue = _day(due) < today
                    except ValueError:
                        overdue = False
                    if overdue:
                        add(55, f"Overdue milestone: {milestone['title']}", f"was due {due}", "orchestrator",
                            str(plan.id))
            for objective in (plan.objectives or [])[:5]:
                if str(objective.get("status", "")).lower() not in DONE:
                    add(35, f"Advance objective: {objective['title']}", f"operating plan '{plan.plan_name}'",
                        "orchestrator", str(plan.id))
        queued = [t for t in act["open"] if t.status in ("pending", "queued")]
        if queued:
            add(30, f"Work the queue ({len(queued)} task(s) waiting)", ", ".join(t.title for t in queued[:3]),
                "orchestrator")
        actions.sort(key=lambda a: -a["priority"])
        return actions[:limit]

    # ----- daily operating loop -----------------------------------------------------------

    async def create_daily_loop(self, db: AsyncSession, workspace_id: UUID, *, loop_date: Any = None,
                                activities: Optional[Sequence[str]] = None) -> DailyOperatingLoop:
        day = _day(loop_date, default=_now().date())
        existing = (await db.execute(select(DailyOperatingLoop).where(
            DailyOperatingLoop.workspace_id == workspace_id, DailyOperatingLoop.loop_date == day))
            ).scalar_one_or_none()
        if existing is not None:
            return existing
        names = [a for a in (activities or DEFAULT_LOOP_ACTIVITIES) if a in DEFAULT_LOOP_ACTIVITIES]
        if not names:
            raise ValueError(f"Activities are chosen from: {', '.join(DEFAULT_LOOP_ACTIVITIES)}")
        now = _now()
        loop = DailyOperatingLoop(
            id=uuid4(), workspace_id=workspace_id, loop_date=day, status="pending",
            activities=[{"name": n, "status": "pending"} for n in names], completed_activities=0,
            tasks_completed=0, issues_resolved=0, blockers=[], meta_data={}, created_at=now, updated_at=now)
        db.add(loop)
        await db.flush()
        return loop

    async def run_daily_loop(self, db: AsyncSession, workspace_id: UUID, *, loop_date: Any = None
                             ) -> DailyOperatingLoop:
        """Run (or re-run) the day's loop: standup, next actions, KPI snapshot, risk review, plan progress."""
        loop = await self.create_daily_loop(db, workspace_id, loop_date=loop_date)
        now = _now()
        loop.status, loop.started_at = "running", now
        day_start = datetime.combine(loop.loop_date, datetime.min.time(), tzinfo=timezone.utc)
        act = await self.activity(db, workspace_id, day_start, min(day_start + timedelta(days=1), now + timedelta(seconds=1)))
        highlights: List[str] = []
        concerns: List[str] = []
        done_steps: List[Dict[str, Any]] = []
        for step in loop.activities or []:
            name = step["name"]
            try:
                detail = await self._loop_step(db, workspace_id, name, loop.loop_date, act, highlights, concerns)
                done_steps.append({"name": name, "status": "completed", **detail})
            except Exception as exc:  # noqa: BLE001 - one failed step is recorded; the loop continues
                logger.warning(f"daily loop step {name} failed: {exc}")
                done_steps.append({"name": name, "status": "failed", "error": str(exc)[:300]})
                concerns.append(f"{name} step failed: {str(exc)[:160]}")
        blockers = [f"Failed: {t.title}" for t in act["failed"]]
        blockers += [f"Approval pending: {(a.input_prompt or a.richard_input_type or '')[:160]}" for a in act["approvals"]]
        if act["completed"]:
            highlights.insert(0, f"{len(act['completed'])} task(s) completed")
        loop.activities = done_steps
        loop.completed_activities = sum(1 for s in done_steps if s["status"] == "completed")
        loop.tasks_completed, loop.issues_resolved = len(act["completed"]), len(act["resolved_incidents"])
        loop.blockers, loop.highlights, loop.concerns = blockers, highlights, concerns
        loop.status = "completed" if loop.completed_activities == len(done_steps) else "partial"
        loop.completed_at = _now()
        loop.summary = (f"{loop.loop_date.isoformat()}: {loop.tasks_completed} task(s) completed, "
                        f"{len(act['failed'])} failed, {loop.issues_resolved} incident(s) resolved, "
                        f"{len(blockers)} blocker(s); {loop.completed_activities}/{len(done_steps)} loop steps ran.")
        loop.updated_at = loop.completed_at
        await self.post_feed(db, workspace_id, item_type="daily_loop",
                             severity="warning" if blockers or concerns else "success",
                             title=f"Daily operating loop {loop.loop_date.isoformat()}", message=loop.summary,
                             requires_action=bool(act["approvals"]), meta={"loop_id": str(loop.id)})
        await db.flush()
        return loop

    async def _loop_step(self, db, workspace_id, name, day, act, highlights, concerns) -> Dict[str, Any]:
        if name == "standup":
            standup = await self.create_standup(db, workspace_id, standup_date=day)
            return {"standup_id": str(standup.id), "blockers": len(standup.blockers)}
        if name == "next_best_actions":
            actions = await self.next_best_actions(db, workspace_id, limit=5)
            if actions:
                highlights.append(f"Top action: {actions[0]['action']}")
            return {"actions": actions}
        if name == "kpi_snapshot":
            recorded = []
            judged = len(act["completed"]) + len(act["failed"])
            recorded.append(await self.record_kpi(db, workspace_id, name="tasks_completed",
                                                  value=len(act["completed"]), unit="tasks", period_start=day,
                                                  category="delivery", notes="recorded by the daily loop"))
            if judged:
                rate = round(100.0 * len(act["completed"]) / judged, 1)
                kpi = await self.record_kpi(db, workspace_id, name="task_success_rate", value=rate, unit="%",
                                            period_start=day, category="delivery",
                                            notes="completed / (completed + failed)")
                recorded.append(kpi)
                if kpi.target_met is False:
                    concerns.append(f"Task success rate {rate:g}% is below target {float(kpi.target_value):g}%")
            return {"kpis": [kpi_view(k) for k in recorded]}
        if name == "risk_review":
            due = [r for r in await self.risks(db, workspace_id) if r.review_date and r.review_date <= day]
            high = [r for r in await self.risks(db, workspace_id) if r.risk_score >= 15]
            for risk in high:
                concerns.append(f"High risk open: {risk.risk_title} (score {risk.risk_score:g})")
            return {"reviews_due": [risk_view(r) for r in due], "high_risks": len(high)}
        if name == "plan_progress":
            plan = await self.active_plan(db, workspace_id)
            if plan is None:
                return {"plan": None}
            plan.objectives_completed, plan.objectives_total, plan.completion_percentage = _progress(plan.objectives)
            return {"plan": plan.plan_name, "completion_percentage": plan.completion_percentage}
        raise ValueError(f"Unknown loop activity '{name}'")

    async def overview(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, Any]:
        plan = await self.active_plan(db, workspace_id)
        loop = (await db.execute(select(DailyOperatingLoop).where(DailyOperatingLoop.workspace_id == workspace_id)
                                 .order_by(DailyOperatingLoop.loop_date.desc()).limit(1))).scalar_one_or_none()
        week = (await db.execute(select(WeeklyExecutionPlan).where(WeeklyExecutionPlan.workspace_id == workspace_id)
                                 .order_by(WeeklyExecutionPlan.week_start_date.desc()).limit(1))).scalar_one_or_none()
        standup = (await db.execute(select(AIStandup).where(AIStandup.workspace_id == workspace_id)
                                    .order_by(AIStandup.created_at.desc()).limit(1))).scalar_one_or_none()
        decisions = (await db.execute(select(DecisionLogItem).where(DecisionLogItem.workspace_id == workspace_id)
                                      .order_by(DecisionLogItem.created_at.desc()).limit(10))).scalars().all()
        return {"workspace_id": str(workspace_id),
                "operating_plan": plan_view(plan) if plan else None,
                "latest_daily_loop": loop_view(loop) if loop else None,
                "weekly_plan": weekly_view(week) if week else None,
                "latest_standup": standup_view(standup) if standup else None,
                "kpis": await self.kpi_dashboard(db, workspace_id),
                "risks": [risk_view(r) for r in await self.risks(db, workspace_id)],
                "decisions": [decision_view(d) for d in decisions],
                "next_best_actions": await self.next_best_actions(db, workspace_id)}


company_ops = CompanyOpsService()
