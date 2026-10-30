"""
JARV Backend - Revenue and business monitoring tools (Repair 12e-4b)

check_revenue_metrics, check_conversion_metrics, check_subscription_metrics,
check_failed_payments, create_revenue_experiment,
update_revenue_operations_loop, record_revenue_event (create_offer_draft and
create_pricing_review are drafting tools grounded in these numbers), and the
monitoring checks check_payment_events, check_reviews and check_analytics.

Numbers come from Stripe (read-only) when STRIPE_SECRET_KEY is set, otherwise
from recorded revenue; every result names its source. Nothing here moves
money or changes a customer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.agents.base import AuthorityLevel
from app.core.business.revenue import EVENT_TYPES, revenue_service
from app.tools._scoped import ScopedTool


class _RevenueTool(ScopedTool):
    _category = "revenue"
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS


class _Days(BaseModel):
    days: int = Field(30, ge=1, le=365)


class CheckRevenueMetricsTool(_RevenueTool):
    _name = "check_revenue_metrics"
    _description = "Gross, refunds, fees, net and daily revenue for a period (Stripe or recorded revenue)."
    _input = _Days

    async def act(self, db, context, owner, data):
        result = await revenue_service.revenue(db, context.workspace_id, data["days"])
        return result, f"Net {result['net']:.2f} {result.get('currency', 'USD')} over {data['days']} days ({result['source']})"


class CheckConversionMetricsTool(_RevenueTool):
    _name = "check_conversion_metrics"
    _description = "Conversion through the funnel (visitors, signups, trials, activated, paying) from KPIs and analytics."
    _input = _Days

    async def act(self, db, context, owner, data):
        result = await revenue_service.conversion(db, context.workspace_id, data["days"])
        overall = f"overall {result['overall']:.2%}" if result["overall"] is not None else "no complete funnel yet"
        return result, f"{len(result['stages'])} funnel stage(s) measured; {overall}"


class CheckSubscriptionMetricsTool(_RevenueTool):
    _name = "check_subscription_metrics"
    _description = "Active subscriptions, MRR, new, cancelled, churn and ARPU."
    _input = _Days

    async def act(self, db, context, owner, data):
        result = await revenue_service.subscriptions(db, context.workspace_id, data["days"])
        return result, f"{result['active']} active, MRR {result['mrr']:.2f} ({result['source']})"


class CheckFailedPaymentsTool(_RevenueTool):
    _name = "check_failed_payments"
    _description = "Failed payments not yet recovered, with amounts and reasons."
    _input = _Days

    async def act(self, db, context, owner, data):
        result = await revenue_service.failed_payments(db, context.workspace_id, data["days"])
        return result, f"{result['count']} failed payment(s), {result['amount']:.2f} outstanding ({result['source']})"


class _Experiment(BaseModel):
    name: str = Field(..., min_length=3)
    hypothesis: str = Field(..., min_length=10)
    metric: str = Field(..., description="KPI the experiment moves, e.g. trial_to_paid or mrr")
    variants: List[str] = Field(..., min_length=2, description="Control first")
    duration_days: int = Field(14, ge=3, le=120)
    success_threshold: str = Field(..., description="What counts as a win, e.g. '+10% trial_to_paid'")


class CreateRevenueExperimentTool(_RevenueTool):
    _name = "create_revenue_experiment"
    _description = ("Plan a revenue experiment with its hypothesis, metric, variants, duration and success threshold; "
                    "the metric's current value is saved as the baseline. Launching it is a separate, reviewed step.")
    _input = _Experiment
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    async def act(self, db, context, owner, data):
        from app.core.company_ops.service import company_ops
        from app.models.content import ContentItem

        baseline = await company_ops.latest_kpi(db, context.workspace_id, data["metric"])
        now = datetime.now(timezone.utc)
        plan = {**data, "baseline": float(baseline.value) if baseline else None,
                "baseline_period": baseline.period_start.isoformat() if baseline else None, "status": "planned"}
        body = (f"# Experiment: {data['name']}\n\n**Hypothesis:** {data['hypothesis']}\n\n**Metric:** {data['metric']} "
                f"(baseline {plan['baseline'] if plan['baseline'] is not None else 'not measured yet'})\n\n"
                f"**Variants:** {', '.join(data['variants'])} (control: {data['variants'][0]})\n\n"
                f"**Duration:** {data['duration_days']} days\n\n**Success:** {data['success_threshold']}\n")
        row = ContentItem(id=uuid4(), workspace_id=context.workspace_id, title=data["name"][:500],
                          content_type="revenue_experiment", category="revenue",
                          slug=f"experiment-{uuid4().hex[:12]}", content_body=body, content_format="markdown",
                          status="planned", is_published=False, author_id=owner, author_name="JARV",
                          tags=["experiment", data["metric"]], meta_data=plan, created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
        if baseline is None:
            text = f"Experiment planned; {data['metric']} has no baseline yet, measure it before starting"
        else:
            text = f"Experiment planned with {data['metric']} baseline {float(baseline.value):g}"
        return {"id": str(row.id), **plan}, text


class UpdateRevenueOperationsLoopTool(_RevenueTool):
    _name = "update_revenue_operations_loop"
    _description = ("Run the revenue operations loop: measure revenue, MRR, churn, failed payments and conversion, "
                    "record them as KPIs, list findings and next actions, and post to the operations feed.")
    _input = _Days
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    async def act(self, db, context, owner, data):
        result = await revenue_service.run_loop(db, context.workspace_id, data["days"])
        return result, result["summary"]


class _Event(BaseModel):
    event: str = Field(..., description=", ".join(EVENT_TYPES))
    amount: float = Field(..., ge=0)
    currency: str = "USD"
    customer_id: Optional[str] = None
    product_id: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = Field(None, description="YYYY-MM-DD; defaults to today")
    interval: Optional[str] = Field(None, description="Subscriptions: month or year")


class RecordRevenueEventTool(_RevenueTool):
    _name = "record_revenue_event"
    _description = "Record a revenue event (payment, refund, subscription start/cancel, failed payment, dispute)."
    _input = _Event
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    async def act(self, db, context, owner, data):
        from datetime import date

        amount = data["amount"]
        if data["event"].startswith("subscription") and data.get("interval") == "year":
            amount = round(amount / 12, 2)
        row = await revenue_service.record(
            db, context.workspace_id, event=data["event"], amount=amount, currency=data["currency"],
            customer_id=data.get("customer_id"), product_id=data.get("product_id"), description=data.get("description"),
            occurred=date.fromisoformat(data["date"]) if data.get("date") else None, interval=data.get("interval"),
            status="failed" if data["event"] == "failed_payment" else "completed")
        return {"id": str(row.id), "event": row.operation_type, "amount": float(row.amount),
                "date": row.operation_date.isoformat()}, f"{row.operation_type} {float(row.amount):.2f} recorded"


class _Hours(BaseModel):
    hours: int = Field(24, ge=1, le=720)


class CheckPaymentEventsTool(_RevenueTool):
    _name = "check_payment_events"
    _description = "Payment events in the last hours, flagging failures, disputes and fraud warnings."
    _input = _Hours

    async def act(self, db, context, owner, data):
        result = await revenue_service.payment_events(db, context.workspace_id, data["hours"])
        return result, f"{result['events']} payment event(s), {len(result['alerts'])} alert(s) ({result['source']})"


class _Reviews(BaseModel):
    app_store_id: Optional[str] = Field(None, description="Numeric App Store id (from the app's store URL)")
    country: Optional[str] = Field(None, description="Two-letter store country, e.g. gb or us")


class CheckReviewsTool(_RevenueTool):
    _name = "check_reviews"
    _description = "Read new App Store reviews into the workspace and summarise ratings, sentiment and low-rated themes."
    _input = _Reviews
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    async def act(self, db, context, owner, data):
        from app.core.business.reviews import check_reviews

        result = await check_reviews(db, context.workspace_id, owner, app_store_id=data.get("app_store_id"),
                                     country=data.get("country"))
        avg = f"average {result['average_rating']}" if result["average_rating"] is not None else "no ratings yet"
        return result, f"{result['reviews']} review(s), {result['new']} new; {avg}"


class CheckAnalyticsTool(_RevenueTool):
    _name = "check_analytics"
    _description = "Visitors, page views, bounce rate and top pages (Plausible when configured, otherwise traffic KPIs)."
    _input = _Days
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    async def act(self, db, context, owner, data):
        result = await revenue_service.analytics(db, context.workspace_id, data["days"])
        if result["source"] == "plausible":
            return result, f"{result['visitors']} visitors, {result['pageviews']} page views"
        return result, f"Analytics not connected; {len(result['kpis'])} traffic KPI(s) recorded"


REVENUE_TOOLS = [
    CheckRevenueMetricsTool, CheckConversionMetricsTool, CheckSubscriptionMetricsTool, CheckFailedPaymentsTool,
    CreateRevenueExperimentTool, UpdateRevenueOperationsLoopTool, RecordRevenueEventTool, CheckPaymentEventsTool,
    CheckReviewsTool, CheckAnalyticsTool,
]
