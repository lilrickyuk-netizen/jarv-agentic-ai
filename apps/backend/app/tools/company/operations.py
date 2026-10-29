"""
JARV Backend - Company operating-layer tools (Repair 12e-3c)

create_operating_plan, update_operating_plan, create_daily_operating_loop,
run_daily_operating_loop, create_weekly_execution_plan,
update_weekly_execution_plan, create_ai_standup, update_ai_standup,
decide_next_best_actions, create_kpi_dashboard, update_kpi_dashboard,
create_risk_register, update_risk_register, create_decision_log,
update_decision_log, create_live_operations_feed_item,
update_live_operations_feed.

Each one reads and writes the company tables for the calling workspace
through app.core.company_ops (real records; standups, loops and next actions
are computed from the workspace's own tasks, approvals, incidents, KPIs,
risks and plans).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.agents.base import AuthorityLevel
from app.core.company_ops.service import (
    company_ops, decision_view, feed_view, kpi_view, loop_view, plan_view, risk_view, standup_view, weekly_view,
)
from app.tools._scoped import ScopedTool, as_uuid


class _CompanyTool(ScopedTool):
    _category = "company"
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS


# ----- inputs ------------------------------------------------------------------------------

class _PlanCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    plan_type: str = Field("quarterly", description="e.g. launch, quarterly, growth, operations")
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    description: Optional[str] = None
    objectives: List[Any] = Field(default_factory=list, description="Strings or {title, status, target}")
    strategies: List[Any] = Field(default_factory=list)
    milestones: List[Any] = Field(default_factory=list, description="Strings or {title, due, status}")
    activate: bool = True


class _PlanUpdate(BaseModel):
    plan_id: str
    change_summary: str = Field(..., min_length=3)
    objectives: Optional[List[Any]] = Field(None, description="Changes by title; {title, remove: true} removes")
    strategies: Optional[List[Any]] = None
    milestones: Optional[List[Any]] = None
    status: Optional[str] = None
    description: Optional[str] = None
    end_date: Optional[str] = None
    activate: Optional[bool] = None


class _LoopCreate(BaseModel):
    loop_date: Optional[str] = Field(None, description="YYYY-MM-DD; defaults to today")
    activities: Optional[List[str]] = Field(None, description="standup, next_best_actions, kpi_snapshot, "
                                                               "risk_review, plan_progress")


class _LoopRun(BaseModel):
    loop_date: Optional[str] = None


class _WeekCreate(BaseModel):
    week_of: Optional[str] = Field(None, description="Any date in the week; defaults to this week")
    objectives: List[Any] = Field(default_factory=list)
    priorities: List[str] = Field(default_factory=list)
    deliverables: List[Any] = Field(default_factory=list)


class _WeekUpdate(BaseModel):
    plan_id: str
    objectives: Optional[List[Any]] = None
    priorities: Optional[List[str]] = None
    deliverables: Optional[List[Any]] = None
    status: Optional[str] = None
    review_notes: Optional[str] = None
    lessons_learned: Optional[List[str]] = None


class _StandupCreate(BaseModel):
    standup_date: Optional[str] = None
    agent_id: Optional[str] = Field(None, description="One agent's standup; omit for the whole workspace")
    yesterday: List[str] = Field(default_factory=list)
    today: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    needs_help_with: List[str] = Field(default_factory=list)
    mood: Optional[str] = None


class _StandupUpdate(BaseModel):
    standup_id: str
    yesterday: Optional[List[str]] = None
    today: Optional[List[str]] = None
    blockers: Optional[List[str]] = None
    needs_help_with: Optional[List[str]] = None
    mood: Optional[str] = None
    confidence_level: Optional[float] = None


class _Actions(BaseModel):
    limit: int = Field(10, ge=1, le=50)


class _Kpi(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    value: float
    target: Optional[float] = None
    unit: Optional[str] = None
    kpi_type: str = "operational"
    category: Optional[str] = None
    higher_is_better: bool = True
    period_type: str = "daily"
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    notes: Optional[str] = None


class _KpiCreate(BaseModel):
    kpis: List[_Kpi] = Field(..., min_length=1)


class _KpiUpdate(_Kpi):
    pass


class _RiskCreate(BaseModel):
    title: str = Field(..., min_length=3)
    description: str = Field(..., min_length=3)
    category: str = Field("operational", description="technical, operational, financial, legal, security, market")
    probability: str = Field(..., description="very_low, low, medium, high, very_high (or 1-5)")
    impact: str = Field(..., description="very_low, low, medium, high, very_high (or 1-5)")
    mitigation_strategy: Optional[str] = None
    mitigation_actions: List[str] = Field(default_factory=list)
    review_date: Optional[str] = None


class _RiskUpdate(BaseModel):
    risk_id: str
    probability: Optional[str] = None
    impact: Optional[str] = None
    mitigation_strategy: Optional[str] = None
    mitigation_actions: Optional[List[str]] = None
    status: Optional[str] = Field(None, description="open, monitoring, mitigated, closed")
    review_date: Optional[str] = None


class _DecisionCreate(BaseModel):
    title: str = Field(..., min_length=3)
    description: str = Field(..., min_length=3)
    decision_type: str = Field("operational", description="technical, product, operational, commercial, ...")
    rationale: Optional[str] = None
    problem: Optional[str] = None
    alternatives: List[str] = Field(default_factory=list)
    impact: Optional[str] = None
    stakeholders: List[str] = Field(default_factory=list)


class _DecisionUpdate(BaseModel):
    decision_id: str
    status: Optional[str] = None
    rationale: Optional[str] = None
    impact: Optional[str] = None
    reverse_reason: Optional[str] = Field(None, description="Reverses the decision, with this reason")


class _FeedCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=500)
    message: str = Field(..., min_length=1)
    item_type: str = "update"
    severity: str = Field("info", description="info, success, warning, error, critical")
    requires_action: bool = False
    task_id: Optional[str] = None


class _FeedUpdate(BaseModel):
    item_ids: List[str] = Field(..., min_length=1)
    mark_read: Optional[bool] = None
    archive: Optional[bool] = None
    action_taken: Optional[str] = None


# ----- tools ------------------------------------------------------------------------------

class CreateOperatingPlanTool(_CompanyTool):
    _name = "create_operating_plan"
    _description = "Create a versioned operating plan (objectives, strategies, milestones); activating it supersedes the previous active plan of the same type."
    _input = _PlanCreate

    async def act(self, db, context, owner, data):
        plan = await company_ops.create_operating_plan(
            db, context.workspace_id, name=data["name"], plan_type=data["plan_type"], start=data["start_date"],
            end=data["end_date"], description=data.get("description"), objectives=data["objectives"],
            strategies=data["strategies"], milestones=data["milestones"], activate=data["activate"],
            created_by=owner)
        return plan_view(plan), f"Operating plan '{plan.plan_name}' created (v1, {plan.objectives_total} objectives)"


class UpdateOperatingPlanTool(_CompanyTool):
    _name = "update_operating_plan"
    _description = "Change an operating plan; every change is saved as a new version with its summary."
    _input = _PlanUpdate

    async def act(self, db, context, owner, data):
        plan = await company_ops.update_operating_plan(
            db, context.workspace_id, data["plan_id"], change_summary=data["change_summary"],
            objectives=data.get("objectives"), strategies=data.get("strategies"), milestones=data.get("milestones"),
            status=data.get("status"), description=data.get("description"), end=data.get("end_date"),
            activate=data.get("activate"), changed_by=owner)
        versions = await company_ops.plan_versions(db, context.workspace_id, plan.id)
        return ({**plan_view(plan), "versions": versions},
                f"Plan v{plan.current_version}: {plan.completion_percentage:g}% of objectives done")


class CreateDailyOperatingLoopTool(_CompanyTool):
    _name = "create_daily_operating_loop"
    _description = "Set up the day's operating loop and its activities (one loop per day)."
    _input = _LoopCreate

    async def act(self, db, context, owner, data):
        loop = await company_ops.create_daily_loop(db, context.workspace_id, loop_date=data.get("loop_date"),
                                                   activities=data.get("activities"))
        return loop_view(loop), f"Daily loop {loop.loop_date.isoformat()} ({len(loop.activities)} activities, {loop.status})"


class RunDailyOperatingLoopTool(_CompanyTool):
    _name = "run_daily_operating_loop"
    _description = ("Run the day's loop on real workspace data: standup, next best actions, KPI snapshot, "
                    "risk review and plan progress; posts the summary to the operations feed.")
    _input = _LoopRun

    async def act(self, db, context, owner, data):
        loop = await company_ops.run_daily_loop(db, context.workspace_id, loop_date=data.get("loop_date"))
        return loop_view(loop), loop.summary


class CreateWeeklyExecutionPlanTool(_CompanyTool):
    _name = "create_weekly_execution_plan"
    _description = "Create the week's execution plan (objectives, priorities, deliverables)."
    _input = _WeekCreate

    async def act(self, db, context, owner, data):
        plan = await company_ops.create_weekly_plan(
            db, context.workspace_id, week_of=data.get("week_of"), objectives=data["objectives"],
            priorities=data["priorities"], deliverables=data["deliverables"], created_by=owner)
        return weekly_view(plan), f"Week {plan.week_number}/{plan.year} plan created"


class UpdateWeeklyExecutionPlanTool(_CompanyTool):
    _name = "update_weekly_execution_plan"
    _description = "Update a weekly plan: objective and deliverable status, priorities, review notes, lessons."
    _input = _WeekUpdate

    async def act(self, db, context, owner, data):
        plan = await company_ops.update_weekly_plan(
            db, context.workspace_id, data["plan_id"], objectives=data.get("objectives"),
            priorities=data.get("priorities"), deliverables=data.get("deliverables"), status=data.get("status"),
            review_notes=data.get("review_notes"), lessons_learned=data.get("lessons_learned"))
        return weekly_view(plan), f"Week {plan.week_number}: {plan.completion_percentage:g}% done"


class CreateAIStandupTool(_CompanyTool):
    _name = "create_ai_standup"
    _description = ("Write a standup from the workspace's real last 24 hours: tasks completed, in progress "
                    "and planned, failures, waiting approvals; extra entries are added.")
    _input = _StandupCreate

    async def act(self, db, context, owner, data):
        agent_id = as_uuid(data["agent_id"], "agent id") if data.get("agent_id") else None
        if agent_id is not None:
            from sqlalchemy import select

            from app.models.agent import Agent

            found = (await db.execute(select(Agent.id).where(Agent.id == agent_id,
                                                            Agent.workspace_id == context.workspace_id))
                     ).scalar_one_or_none()
            if found is None:
                raise LookupError("Agent not found in this workspace")
        row = await company_ops.create_standup(
            db, context.workspace_id, standup_date=data.get("standup_date"), agent_id=agent_id,
            yesterday=data["yesterday"], today=data["today"], blockers=data["blockers"],
            needs_help_with=data["needs_help_with"], mood=data.get("mood"))
        return standup_view(row), (f"Standup: {row.tasks_completed} done, {row.tasks_in_progress} in progress, "
                                   f"{len(row.blockers)} blocker(s)")


class UpdateAIStandupTool(_CompanyTool):
    _name = "update_ai_standup"
    _description = "Correct or add to a standup."
    _input = _StandupUpdate

    async def act(self, db, context, owner, data):
        row = await company_ops.update_standup(db, context.workspace_id, data.pop("standup_id"), **data)
        return standup_view(row), "Standup updated"


class DecideNextBestActionsTool(_CompanyTool):
    _name = "decide_next_best_actions"
    _description = ("Rank what to do next from what is actually open: approval gates, incidents, failed and "
                    "blocked tasks, unmitigated risks, missed KPIs, overdue milestones, plan objectives, queue.")
    _input = _Actions
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        actions = await company_ops.next_best_actions(db, context.workspace_id, limit=data["limit"])
        return {"actions": actions}, (f"{len(actions)} action(s); first: {actions[0]['action']}" if actions
                                      else "Nothing open: no approvals, failures, incidents, risks or plan items need action")


class CreateKPIDashboardTool(_CompanyTool):
    _name = "create_kpi_dashboard"
    _description = "Record a set of KPIs with targets; returns the dashboard of latest values and changes."
    _input = _KpiCreate

    async def act(self, db, context, owner, data):
        for kpi in data["kpis"]:
            await company_ops.record_kpi(db, context.workspace_id, **_kpi_args(kpi))
        board = await company_ops.kpi_dashboard(db, context.workspace_id)
        return {"kpis": board}, f"{len(data['kpis'])} KPI(s) recorded; dashboard has {len(board)}"


class UpdateKPIDashboardTool(_CompanyTool):
    _name = "update_kpi_dashboard"
    _description = "Record a new value for a KPI (same period updates it); keeps its target and direction."
    _input = _KpiUpdate

    async def act(self, db, context, owner, data):
        row = await company_ops.record_kpi(db, context.workspace_id, **_kpi_args(data))
        verdict = "" if row.target_met is None else (" (target met)" if row.target_met else " (below target)")
        return kpi_view(row), f"{row.kpi_name} = {float(row.value):g}{verdict}"


def _kpi_args(kpi: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": kpi["name"], "value": kpi["value"], "target": kpi.get("target"), "unit": kpi.get("unit"),
            "kpi_type": kpi.get("kpi_type") or "operational", "category": kpi.get("category"),
            "higher_is_better": kpi.get("higher_is_better", True), "period_type": kpi.get("period_type") or "daily",
            "period_start": kpi.get("period_start"), "period_end": kpi.get("period_end"), "notes": kpi.get("notes")}


class CreateRiskRegisterTool(_CompanyTool):
    _name = "create_risk_register"
    _description = "Add a risk to the register; its score is probability x impact (1-25)."
    _input = _RiskCreate

    async def act(self, db, context, owner, data):
        row = await company_ops.create_risk(
            db, context.workspace_id, title=data["title"], description=data["description"],
            category=data["category"], probability=data["probability"], impact=data["impact"],
            mitigation_strategy=data.get("mitigation_strategy"), mitigation_actions=data["mitigation_actions"],
            owner_id=owner, review_date=data.get("review_date"))
        register = [risk_view(r) for r in await company_ops.risks(db, context.workspace_id)]
        return {"risk": risk_view(row), "register": register}, f"Risk '{row.risk_title}' scored {row.risk_score:g}"


class UpdateRiskRegisterTool(_CompanyTool):
    _name = "update_risk_register"
    _description = "Re-score a risk, add mitigations, or change its status (mitigated/closed)."
    _input = _RiskUpdate

    async def act(self, db, context, owner, data):
        row = await company_ops.update_risk(db, context.workspace_id, data.pop("risk_id"), **data)
        return risk_view(row), f"Risk '{row.risk_title}': {row.status}, score {row.risk_score:g}"


class CreateDecisionLogTool(_CompanyTool):
    _name = "create_decision_log"
    _description = "Record a decision with its problem, alternatives, rationale and expected impact."
    _input = _DecisionCreate

    async def act(self, db, context, owner, data):
        row = await company_ops.log_decision(
            db, context.workspace_id, title=data["title"], description=data["description"],
            decision_type=data["decision_type"], rationale=data.get("rationale"), problem=data.get("problem"),
            alternatives=data["alternatives"], impact=data.get("impact"), stakeholders=data["stakeholders"],
            made_by=owner, agent=str(context.agent_id) if context.agent_id else None)
        return decision_view(row), f"Decision logged: {row.decision_title}"


class UpdateDecisionLogTool(_CompanyTool):
    _name = "update_decision_log"
    _description = "Update a decision's status, rationale or impact, or reverse it with a reason."
    _input = _DecisionUpdate

    async def act(self, db, context, owner, data):
        row = await company_ops.update_decision(
            db, context.workspace_id, data["decision_id"], status=data.get("status"), rationale=data.get("rationale"),
            impact=data.get("impact"), reverse_reason=data.get("reverse_reason"))
        return decision_view(row), f"Decision '{row.decision_title}': {row.status}"


class CreateLiveOperationsFeedItemTool(_CompanyTool):
    _name = "create_live_operations_feed_item"
    _description = "Post an item to the workspace's live operations feed."
    _input = _FeedCreate
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        task_id = as_uuid(data["task_id"], "task id") if data.get("task_id") else context.task_id
        if task_id is not None:
            from sqlalchemy import select

            from app.models.task import Task

            if (await db.execute(select(Task.id).where(Task.id == task_id, Task.workspace_id == context.workspace_id))
                ).scalar_one_or_none() is None:
                task_id = None
        row = await company_ops.post_feed(
            db, context.workspace_id, item_type=data["item_type"], title=data["title"], message=data["message"],
            severity=data["severity"], requires_action=data["requires_action"], task_id=task_id,
            agent_id=context.agent_id)
        return feed_view(row), f"Feed: {row.title}"


class UpdateLiveOperationsFeedTool(_CompanyTool):
    _name = "update_live_operations_feed"
    _description = "Mark feed items read, archive them, or record the action taken on them."
    _input = _FeedUpdate
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        if data.get("mark_read") is None and data.get("archive") is None and not data.get("action_taken"):
            raise ValueError("Say what to change: mark_read, archive or action_taken")
        rows = await company_ops.update_feed(db, context.workspace_id, data["item_ids"], mark_read=data.get("mark_read"),
                                             archive=data.get("archive"), action_taken=data.get("action_taken"),
                                             actor=owner)
        return {"items": [feed_view(r) for r in rows]}, f"{len(rows)} feed item(s) updated"


COMPANY_TOOLS = [
    CreateOperatingPlanTool, UpdateOperatingPlanTool, CreateDailyOperatingLoopTool, RunDailyOperatingLoopTool,
    CreateWeeklyExecutionPlanTool, UpdateWeeklyExecutionPlanTool, CreateAIStandupTool, UpdateAIStandupTool,
    DecideNextBestActionsTool, CreateKPIDashboardTool, UpdateKPIDashboardTool, CreateRiskRegisterTool,
    UpdateRiskRegisterTool, CreateDecisionLogTool, UpdateDecisionLogTool, CreateLiveOperationsFeedItemTool,
    UpdateLiveOperationsFeedTool,
]
