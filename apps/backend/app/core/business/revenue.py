"""
JARV Backend - Revenue operations

Two sources, never mixed silently (every result says which it used):

- Stripe, read-only, when STRIPE_SECRET_KEY is set: balance transactions,
  subscriptions, open invoices and events.
- Recorded revenue: RevenueOperation rows (written by the verified Stripe
  webhook, the API or tools: payment, refund, subscription_started,
  subscription_cancelled, failed_payment, dispute) plus paid SalesRecord rows.

On top of either: revenue, subscription (MRR, churn), failed-payment and
conversion metrics; the revenue operations loop records them as KPIs, lists
findings and next actions, and posts to the operations feed. Nothing here
charges, refunds or changes a customer: money movement is a hard boundary.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.business import SalesRecord
from app.models.company_operations import RevenueOperation

STRIPE_API = "https://api.stripe.com/v1"
EVENT_TYPES = ("payment", "refund", "subscription_started", "subscription_cancelled", "failed_payment", "dispute")
_INTERVAL_MONTHS = {"day": 1 / 30, "week": 12 / 52, "month": 1, "year": 12}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def stripe_configured() -> bool:
    return bool(getattr(settings, "STRIPE_SECRET_KEY", None))


async def stripe_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One read-only Stripe API call (GET only)."""
    if not stripe_configured():
        raise RuntimeError("Stripe is not configured (set STRIPE_SECRET_KEY to a restricted read-only key)")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{STRIPE_API}/{path.lstrip('/')}", params=params or {},
                                    auth=(settings.STRIPE_SECRET_KEY, ""))
    if response.status_code >= 400:
        raise RuntimeError(f"Stripe returned {response.status_code}: {response.text[:200]}")
    return response.json()


async def _stripe_list(path: str, params: Dict[str, Any], limit: int = 1000) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    params = {**params, "limit": 100}
    while len(items) < limit:
        page = await stripe_get(path, params)
        data = page.get("data") or []
        items += data
        if not page.get("has_more") or not data:
            break
        params["starting_after"] = data[-1]["id"]
    return items[:limit]


def verify_stripe_signature(payload: bytes, header: str, secret: str, tolerance: int = 300) -> bool:
    """Stripe webhook signature: v1 = HMAC-SHA256(secret, f"{t}.{payload}") within the tolerance."""
    pairs = [p.split("=", 1) for p in (header or "").split(",") if "=" in p]
    stamp = next((v for k, v in pairs if k.strip() == "t"), None)
    signatures = [v for k, v in pairs if k.strip() == "v1"]
    if not stamp or not stamp.isdigit() or not signatures or abs(time.time() - int(stamp)) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s.strip()) for s in signatures)


def _money(cents: Any) -> float:
    return round(int(cents or 0) / 100, 2)


class RevenueService:
    # ----- recording --------------------------------------------------------------------------

    async def record(self, db: AsyncSession, workspace_id: UUID, *, event: str, amount: float, currency: str = "USD",
                     customer_id: Optional[str] = None, product_id: Optional[str] = None,
                     description: Optional[str] = None, occurred: Optional[date] = None, interval: Optional[str] = None,
                     external_id: Optional[str] = None, status: str = "completed") -> RevenueOperation:
        if event not in EVENT_TYPES:
            raise ValueError(f"event is one of {', '.join(EVENT_TYPES)}")
        if external_id:
            rows = (await db.execute(select(RevenueOperation).where(RevenueOperation.workspace_id == workspace_id))).scalars().all()
            for row in rows:
                if (row.meta_data or {}).get("external_id") == external_id:
                    return row
        now = _now()
        row = RevenueOperation(
            id=uuid4(), workspace_id=workspace_id, operation_type=event, operation_date=occurred or now.date(),
            amount=Decimal(str(round(float(amount), 2))), currency=(currency or "USD").upper()[:3],
            customer_id=customer_id, product_id=product_id, description=description, status=status,
            is_recurring=event.startswith("subscription"),
            meta_data={"interval": interval, "external_id": external_id}, created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
        return row

    async def ingest_stripe_event(self, db: AsyncSession, workspace_id: UUID, event: Dict[str, Any]) -> Optional[RevenueOperation]:
        """Map a verified Stripe webhook event to a recorded revenue event (others are acknowledged and skipped)."""
        kind = event.get("type", "")
        obj = (event.get("data") or {}).get("object") or {}
        when = datetime.fromtimestamp(int(event.get("created") or time.time()), tz=timezone.utc).date()
        common = {"currency": obj.get("currency") or "usd", "customer_id": obj.get("customer"),
                  "occurred": when, "external_id": event.get("id")}
        if kind in ("charge.succeeded", "invoice.paid"):
            amount = obj.get("amount_paid") if kind == "invoice.paid" else obj.get("amount")
            return await self.record(db, workspace_id, event="payment", amount=_money(amount),
                                     description=obj.get("description") or kind, **common)
        if kind == "charge.refunded":
            return await self.record(db, workspace_id, event="refund", amount=_money(obj.get("amount_refunded")),
                                     description="refund", **common)
        if kind in ("invoice.payment_failed", "charge.failed"):
            amount = obj.get("amount_due") if kind == "invoice.payment_failed" else obj.get("amount")
            return await self.record(db, workspace_id, event="failed_payment", amount=_money(amount), status="failed",
                                     description=(obj.get("last_payment_error") or {}).get("message") or kind, **common)
        if kind == "charge.dispute.created":
            return await self.record(db, workspace_id, event="dispute", amount=_money(obj.get("amount")),
                                     status="open", description=obj.get("reason"), **common)
        if kind in ("customer.subscription.created", "customer.subscription.deleted"):
            item = ((obj.get("items") or {}).get("data") or [{}])[0]
            price = item.get("price") or {}
            months = _INTERVAL_MONTHS.get((price.get("recurring") or {}).get("interval", "month"), 1)
            monthly = _money(price.get("unit_amount")) * int(item.get("quantity") or 1) / months
            return await self.record(
                db, workspace_id,
                event="subscription_started" if kind.endswith("created") else "subscription_cancelled",
                amount=round(monthly, 2), product_id=price.get("product"), interval="month",
                description=obj.get("id"), **common)
        return None

    # ----- metrics ----------------------------------------------------------------------------

    async def _ops(self, db: AsyncSession, workspace_id: UUID, since: date) -> List[RevenueOperation]:
        return list((await db.execute(select(RevenueOperation).where(
            RevenueOperation.workspace_id == workspace_id, RevenueOperation.operation_date >= since))).scalars().all())

    async def revenue(self, db: AsyncSession, workspace_id: UUID, days: int = 30) -> Dict[str, Any]:
        since = _now() - timedelta(days=days)
        if stripe_configured():
            txns = await _stripe_list("balance_transactions", {"created[gte]": int(since.timestamp())})
            gross = sum(_money(t["amount"]) for t in txns if t.get("type") in ("charge", "payment"))
            refunds = -sum(_money(t["amount"]) for t in txns if t.get("type") in ("refund", "payment_refund"))
            fees = sum(_money(t.get("fee")) for t in txns)
            daily: Dict[str, float] = defaultdict(float)
            for t in txns:
                if t.get("type") in ("charge", "payment"):
                    daily[datetime.fromtimestamp(t["created"], tz=timezone.utc).date().isoformat()] += _money(t["amount"])
            return {"source": "stripe", "period_days": days, "gross": round(gross, 2), "refunds": round(refunds, 2),
                    "fees": round(fees, 2), "net": round(gross - refunds - fees, 2), "payments": sum(
                        1 for t in txns if t.get("type") in ("charge", "payment")),
                    "daily": dict(sorted(daily.items())), "currency": (txns[0].get("currency", "usd").upper()
                                                                        if txns else "USD")}
        ops = await self._ops(db, workspace_id, since.date())
        sales = (await db.execute(select(SalesRecord).where(
            SalesRecord.workspace_id == workspace_id, SalesRecord.sale_date >= since.date(),
            SalesRecord.payment_status == "paid"))).scalars().all()
        payments = [o for o in ops if o.operation_type == "payment" and o.status == "completed"]
        refunds = [o for o in ops if o.operation_type == "refund"]
        gross = sum(float(o.amount) for o in payments) + sum(float(s.total) for s in sales)
        refund_total = sum(float(o.amount) for o in refunds)
        daily: Dict[str, float] = defaultdict(float)
        by_product: Dict[str, float] = defaultdict(float)
        for o in payments:
            daily[o.operation_date.isoformat()] += float(o.amount)
            by_product[o.product_id or "unspecified"] += float(o.amount)
        for s in sales:
            daily[s.sale_date.isoformat() if isinstance(s.sale_date, date) else str(s.sale_date)[:10]] += float(s.total)
            by_product[s.product_name] += float(s.total)
        return {"source": "recorded", "period_days": days, "gross": round(gross, 2), "refunds": round(refund_total, 2),
                "net": round(gross - refund_total, 2), "payments": len(payments) + len(sales),
                "daily": {k: round(v, 2) for k, v in sorted(daily.items())},
                "by_product": {k: round(v, 2) for k, v in by_product.items()}, "currency": "USD",
                "has_data": bool(payments or sales or refunds)}

    async def subscriptions(self, db: AsyncSession, workspace_id: UUID, days: int = 30) -> Dict[str, Any]:
        since = _now() - timedelta(days=days)
        if stripe_configured():
            subs = await _stripe_list("subscriptions", {"status": "all"})
            active = [s for s in subs if s.get("status") in ("active", "trialing", "past_due")]
            mrr = 0.0
            for s in active:
                for item in (s.get("items") or {}).get("data") or []:
                    price = item.get("price") or {}
                    months = _INTERVAL_MONTHS.get((price.get("recurring") or {}).get("interval", "month"), 1)
                    mrr += _money(price.get("unit_amount")) * int(item.get("quantity") or 1) / months
            new = [s for s in subs if int(s.get("created") or 0) >= since.timestamp()]
            cancelled = [s for s in subs if s.get("canceled_at") and int(s["canceled_at"]) >= since.timestamp()]
            start = len(active) + len(cancelled) - len(new)
            return {"source": "stripe", "active": len(active), "mrr": round(mrr, 2), "new": len(new),
                    "cancelled": len(cancelled), "churn_rate": round(len(cancelled) / start, 3) if start > 0 else None,
                    "arpu": round(mrr / len(active), 2) if active else None,
                    "past_due": sum(1 for s in subs if s.get("status") == "past_due")}
        ops = (await db.execute(select(RevenueOperation).where(
            RevenueOperation.workspace_id == workspace_id,
            RevenueOperation.operation_type.in_(("subscription_started", "subscription_cancelled")))
            .order_by(RevenueOperation.operation_date))).scalars().all()
        state: Dict[Tuple[str, str], float] = {}
        for o in ops:
            key = (o.customer_id or str(o.id), o.product_id or "")
            if o.operation_type == "subscription_started":
                state[key] = float(o.amount)
            else:
                state.pop(key, None)
        new = [o for o in ops if o.operation_type == "subscription_started" and o.operation_date >= since.date()]
        cancelled = [o for o in ops if o.operation_type == "subscription_cancelled" and o.operation_date >= since.date()]
        start = len(state) + len(cancelled) - len(new)
        mrr = sum(state.values())
        return {"source": "recorded", "active": len(state), "mrr": round(mrr, 2), "new": len(new),
                "cancelled": len(cancelled), "churn_rate": round(len(cancelled) / start, 3) if start > 0 else None,
                "arpu": round(mrr / len(state), 2) if state else None, "has_data": bool(ops)}

    async def failed_payments(self, db: AsyncSession, workspace_id: UUID, days: int = 30) -> Dict[str, Any]:
        since = _now() - timedelta(days=days)
        if stripe_configured():
            invoices = await _stripe_list("invoices", {"status": "open", "created[gte]": int(since.timestamp())})
            failing = [i for i in invoices if int(i.get("attempt_count") or 0) > 0]
            return {"source": "stripe", "count": len(failing), "amount": round(sum(_money(i.get("amount_due")) for i in failing), 2),
                    "items": [{"invoice": i["id"], "customer": i.get("customer_email") or i.get("customer"),
                               "amount": _money(i.get("amount_due")), "attempts": i.get("attempt_count"),
                               "next_attempt": i.get("next_payment_attempt")} for i in failing[:50]]}
        ops = await self._ops(db, workspace_id, since.date())
        paid_after: Dict[str, date] = {}
        for o in ops:
            if o.operation_type == "payment" and o.customer_id:
                paid_after[o.customer_id] = max(paid_after.get(o.customer_id, o.operation_date), o.operation_date)
        failing = [o for o in ops if o.operation_type == "failed_payment" and not (
            o.customer_id and paid_after.get(o.customer_id, date.min) >= o.operation_date)]
        return {"source": "recorded", "count": len(failing), "amount": round(sum(float(o.amount) for o in failing), 2),
                "items": [{"id": str(o.id), "customer": o.customer_id, "amount": float(o.amount),
                           "date": o.operation_date.isoformat(), "reason": o.description} for o in failing[:50]]}

    async def conversion(self, db: AsyncSession, workspace_id: UUID, days: int = 30) -> Dict[str, Any]:
        """Funnel from KPIs (visitors, signups, trials, activations, paying customers)."""
        from app.core.company_ops.service import company_ops

        board = {k["name"].lower(): k for k in await company_ops.kpi_dashboard(db, workspace_id)}
        stages = []
        for stage, names in (("visitors", ("visitors", "unique_visitors", "sessions")), ("signups", ("signups", "sign_ups")),
                             ("trials", ("trials", "trial_starts")), ("activated", ("activations", "activated_users")),
                             ("paying", ("paying_customers", "new_customers", "conversions"))):
            hit = next((board[n] for n in names if n in board), None)
            if hit is not None:
                stages.append({"stage": stage, "value": hit["value"], "kpi": hit["name"], "period": hit["period_start"]})
        if not any(s["stage"] == "visitors" for s in stages) and getattr(settings, "PLAUSIBLE_API_KEY", None):
            analytics = await self.analytics(db, workspace_id, days)
            if analytics.get("visitors") is not None:
                stages.insert(0, {"stage": "visitors", "value": analytics["visitors"], "kpi": "plausible"})
        steps = []
        for a, b in zip(stages, stages[1:]):
            steps.append({"from": a["stage"], "to": b["stage"],
                          "rate": round(b["value"] / a["value"], 4) if a["value"] else None})
        missing = [s for s in ("visitors", "signups", "activated", "paying") if s not in {x["stage"] for x in stages}]
        return {"stages": stages, "conversion": steps, "missing": missing,
                "overall": round(stages[-1]["value"] / stages[0]["value"], 4) if len(stages) > 1 and stages[0]["value"] else None}

    async def analytics(self, db: AsyncSession, workspace_id: UUID, days: int = 30) -> Dict[str, Any]:
        key, site = getattr(settings, "PLAUSIBLE_API_KEY", None), getattr(settings, "PLAUSIBLE_SITE_ID", None)
        if key and site:
            # Stats API v2: POST /api/v2/query; results carry metrics in the order requested.
            base = getattr(settings, "PLAUSIBLE_URL", "https://plausible.io").rstrip("/")
            span = [(_now() - timedelta(days=days)).date().isoformat(), _now().date().isoformat()]
            names = ["visitors", "visits", "pageviews", "bounce_rate", "visit_duration"]
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=20) as client:
                agg = await client.post(f"{base}/api/v2/query", headers=headers,
                                        json={"site_id": site, "metrics": names, "date_range": span})
                pages = await client.post(f"{base}/api/v2/query", headers=headers,
                                          json={"site_id": site, "metrics": ["visitors", "pageviews"],
                                                "date_range": span, "dimensions": ["event:page"],
                                                "order_by": [["visitors", "desc"]],
                                                "pagination": {"limit": 10, "offset": 0}})
            if agg.status_code >= 400:
                raise RuntimeError(f"Plausible returned {agg.status_code}: {agg.text[:200]}")
            rows = agg.json().get("results") or []
            values = dict(zip(names, (rows[0].get("metrics") or []) if rows else []))
            top = []
            if pages.status_code < 400:
                top = [{"page": (r.get("dimensions") or [None])[0], "visitors": (r.get("metrics") or [None, None])[0],
                        "pageviews": (r.get("metrics") or [None, None])[1]} for r in pages.json().get("results") or []]
            return {"source": "plausible", "period_days": days, **{n: values.get(n) for n in names}, "top_pages": top}
        from app.core.company_ops.service import company_ops

        board = await company_ops.kpi_dashboard(db, workspace_id)
        traffic = [k for k in board if any(w in k["name"].lower() for w in ("visit", "pageview", "session", "bounce", "signup"))]
        return {"source": "recorded KPIs", "kpis": traffic,
                "configured": False, "missing": ["PLAUSIBLE_API_KEY", "PLAUSIBLE_SITE_ID"]}

    async def payment_events(self, db: AsyncSession, workspace_id: UUID, hours: int = 24) -> Dict[str, Any]:
        since = _now() - timedelta(hours=hours)
        if stripe_configured():
            events = await _stripe_list("events", {"created[gte]": int(since.timestamp())}, limit=500)
            counts: Dict[str, int] = defaultdict(int)
            for e in events:
                counts[e["type"]] += 1
            alerts = [e for e in events if e["type"] in ("invoice.payment_failed", "charge.failed",
                                                         "charge.dispute.created", "radar.early_fraud_warning.created")]
            return {"source": "stripe", "events": len(events), "by_type": dict(counts),
                    "alerts": [{"type": e["type"], "id": e["id"], "created": e["created"]} for e in alerts[:50]],
                    "status": "attention" if alerts else "ok"}
        rows = (await db.execute(select(RevenueOperation).where(
            RevenueOperation.workspace_id == workspace_id, RevenueOperation.created_at >= since))).scalars().all()
        counts = defaultdict(int)
        for r in rows:
            counts[r.operation_type] += 1
        alerts = [r for r in rows if r.operation_type in ("failed_payment", "dispute")]
        return {"source": "recorded", "events": len(rows), "by_type": dict(counts),
                "alerts": [{"type": r.operation_type, "id": str(r.id), "amount": float(r.amount),
                            "customer": r.customer_id} for r in alerts[:50]],
                "status": "attention" if alerts else "ok"}

    # ----- the loop ---------------------------------------------------------------------------

    async def run_loop(self, db: AsyncSession, workspace_id: UUID, days: int = 30) -> Dict[str, Any]:
        from app.core.company_ops.service import company_ops

        revenue = await self.revenue(db, workspace_id, days)
        subs = await self.subscriptions(db, workspace_id, days)
        failed = await self.failed_payments(db, workspace_id, days)
        conversion = await self.conversion(db, workspace_id, days)
        recorded = []
        for name, value, unit in ((f"revenue_{days}d", revenue["net"], revenue.get("currency", "USD")),
                                  ("mrr", subs["mrr"], "USD"), ("active_subscriptions", subs["active"], "subs"),
                                  ("failed_payments_open", failed["count"], "payments")):
            kpi = await company_ops.record_kpi(db, workspace_id, name=name, value=value, unit=unit, kpi_type="revenue",
                                               category="revenue", higher_is_better=name != "failed_payments_open",
                                               notes=f"revenue loop ({revenue['source']})")
            recorded.append(name)
        if subs.get("churn_rate") is not None:
            await company_ops.record_kpi(db, workspace_id, name="churn_rate", value=round(subs["churn_rate"] * 100, 2),
                                         unit="%", kpi_type="revenue", category="revenue", higher_is_better=False)
            recorded.append("churn_rate")
        findings, actions = [], []
        if failed["count"]:
            findings.append(f"{failed['count']} unpaid failed payment(s) worth {failed['amount']:.2f}")
            actions.append("Draft payment-recovery emails for the failed payments (sending needs Richard or a rule)")
        if subs.get("churn_rate") and subs["churn_rate"] > 0.05:
            findings.append(f"churn {subs['churn_rate']:.1%} over {days} days")
            actions.append("Review cancellations and support themes (summarise_feedback) before the next pricing change")
        if revenue["refunds"] and revenue["gross"] and revenue["refunds"] / revenue["gross"] > 0.05:
            findings.append(f"refunds are {revenue['refunds'] / revenue['gross']:.1%} of gross")
        if conversion["missing"]:
            actions.append(f"Start measuring: {', '.join(conversion['missing'])} (record them as KPIs or connect analytics)")
        no_data = revenue["source"] == "recorded" and not revenue.get("has_data") and not subs.get("has_data")
        if no_data:
            actions.insert(0, "No revenue recorded yet: connect Stripe (STRIPE_SECRET_KEY + webhook) or record sales")
        summary = (f"Revenue {days}d net {revenue['net']:.2f} {revenue.get('currency', 'USD')}, MRR {subs['mrr']:.2f}, "
                   f"{subs['active']} active subscription(s), {failed['count']} failed payment(s) ({revenue['source']}).")
        await company_ops.post_feed(db, workspace_id, item_type="revenue", title="Revenue operations loop",
                                    message=summary + (" " + "; ".join(findings) if findings else ""),
                                    severity="warning" if findings else "info", requires_action=bool(failed["count"]))
        return {"summary": summary, "revenue": revenue, "subscriptions": subs, "failed_payments": failed,
                "conversion": conversion, "kpis_recorded": recorded, "findings": findings, "next_actions": actions}


revenue_service = RevenueService()
