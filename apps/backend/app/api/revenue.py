"""
JARV Backend - Revenue API (Repair 12e-4b)

Owner-scoped revenue metrics for the Revenue Operations page (revenue,
subscriptions, failed payments, conversion, payment events), recording a
revenue event, running the revenue loop, and the Stripe webhook that records
payments as they happen. The webhook is unauthenticated by design (Stripe
calls it) and is accepted only with a valid Stripe signature
(STRIPE_WEBHOOK_SECRET); without the secret it is disabled.
"""
from __future__ import annotations

import json
from datetime import date as Date
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId
from app.core.business.revenue import EVENT_TYPES, revenue_service, stripe_configured, verify_stripe_signature
from app.core.config import settings
from app.core.database import get_db
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/revenue", tags=["revenue"])


async def _owned(db: AsyncSession, user_id: str, workspace_id: UUID) -> None:
    found = (await db.execute(select(Workspace.id).where(Workspace.id == workspace_id,
                                                         Workspace.owner_id == UUID(str(user_id))))).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=404, detail="Workspace not found")


async def _guard(call):
    try:
        return await call
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/status")
async def status(user_id: CurrentUserId) -> Dict[str, Any]:
    return {"stripe": "connected" if stripe_configured() else "disabled_no_key",
            "webhook": "enabled" if settings.STRIPE_WEBHOOK_SECRET else "disabled_no_secret",
            "analytics": "plausible" if settings.PLAUSIBLE_API_KEY and settings.PLAUSIBLE_SITE_ID else "kpis",
            "setup": ["Set STRIPE_SECRET_KEY to a restricted read-only key to read Stripe directly.",
                      "Add a Stripe webhook to /api/revenue/{workspace_id}/stripe-webhook and set "
                      "STRIPE_WEBHOOK_SECRET to its signing secret to record payments as they happen.",
                      "Set PLAUSIBLE_API_KEY and PLAUSIBLE_SITE_ID for traffic analytics."]}


@router.get("/{workspace_id}/metrics")
async def metrics(workspace_id: UUID, user_id: CurrentUserId, days: int = Query(30, ge=1, le=365),
                  db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    return {"revenue": await _guard(revenue_service.revenue(db, workspace_id, days)),
            "subscriptions": await _guard(revenue_service.subscriptions(db, workspace_id, days)),
            "failed_payments": await _guard(revenue_service.failed_payments(db, workspace_id, days)),
            "conversion": await _guard(revenue_service.conversion(db, workspace_id, days))}


@router.get("/{workspace_id}/analytics")
async def analytics(workspace_id: UUID, user_id: CurrentUserId, days: int = Query(30, ge=1, le=365),
                    db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Traffic from Plausible when configured, otherwise the traffic KPIs recorded for the workspace."""
    await _owned(db, user_id, workspace_id)
    return await _guard(revenue_service.analytics(db, workspace_id, days))


@router.get("/{workspace_id}/payment-events")
async def payment_events(workspace_id: UUID, user_id: CurrentUserId, hours: int = Query(24, ge=1, le=720),
                         db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    return await _guard(revenue_service.payment_events(db, workspace_id, hours))


class RevenueEvent(BaseModel):
    event: str = Field(..., description=", ".join(EVENT_TYPES))
    amount: float = Field(..., ge=0)
    currency: str = "USD"
    customer_id: Optional[str] = None
    product_id: Optional[str] = None
    description: Optional[str] = None
    date: Optional[Date] = None
    interval: Optional[str] = None


@router.post("/{workspace_id}/events")
async def record_event(workspace_id: UUID, body: RevenueEvent, user_id: CurrentUserId,
                       db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    amount = round(body.amount / 12, 2) if body.event.startswith("subscription") and body.interval == "year" else body.amount
    try:
        row = await revenue_service.record(db, workspace_id, event=body.event, amount=amount, currency=body.currency,
                                           customer_id=body.customer_id, product_id=body.product_id,
                                           description=body.description, occurred=body.date, interval=body.interval,
                                           status="failed" if body.event == "failed_payment" else "completed")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return {"id": str(row.id), "event": row.operation_type, "amount": float(row.amount),
            "date": row.operation_date.isoformat()}


@router.post("/{workspace_id}/loop")
async def run_loop(workspace_id: UUID, user_id: CurrentUserId, days: int = Query(30, ge=1, le=365),
                   db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    result = await _guard(revenue_service.run_loop(db, workspace_id, days))
    await db.commit()
    return result


@router.post("/{workspace_id}/stripe-webhook")
async def stripe_webhook(workspace_id: UUID, request: Request, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe webhook is disabled (STRIPE_WEBHOOK_SECRET not set)")
    payload = await request.body()
    if not verify_stripe_signature(payload, request.headers.get("stripe-signature", ""), secret):
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    exists = (await db.execute(select(Workspace.id).where(Workspace.id == workspace_id))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        event = json.loads(payload)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    row = await revenue_service.ingest_stripe_event(db, workspace_id, event)
    await db.commit()
    return {"received": True, "recorded": row is not None, "type": event.get("type"),
            "id": str(row.id) if row is not None else None}
