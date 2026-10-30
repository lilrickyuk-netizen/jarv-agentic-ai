"""
JARV Backend - Alert intake

``POST /api/observability/alerts`` receives Alertmanager webhook notifications
and turns them into JARV incidents and Live Operations Feed items, so alerts
land where Richard and the agents already look instead of a separate inbox.

- A firing alert opens (or refreshes) one incident per alert fingerprint, so a
  repeating alert updates its incident instead of creating duplicates.
- A resolved alert resolves that incident.
- Critical alerts are marked as requiring action in the feed.

Authentication: when ``ALERT_WEBHOOK_TOKEN`` is set, the request must carry
``Authorization: Bearer <token>`` (configure it in Alertmanager's
``http_config``). Without a token, only private-network and loopback callers
are accepted (Alertmanager runs on the same private Docker network).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.company_operations import LiveOperationsFeedItem
from app.models.operations import Incident
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/observability", tags=["observability"])

_SEVERITY = {"critical": "critical", "page": "critical", "error": "high", "warning": "medium",
             "info": "low"}
_PRIORITY = {"critical": "p1", "high": "p2", "medium": "p3", "low": "p4"}
_FEED_SEVERITY = {"critical": "error", "high": "error", "medium": "warning", "low": "info"}


class AlertItem(BaseModel):
    status: str = "firing"
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)
    startsAt: Optional[str] = None
    endsAt: Optional[str] = None
    fingerprint: Optional[str] = None
    generatorURL: Optional[str] = None


class AlertmanagerPayload(BaseModel):
    status: str = "firing"
    receiver: Optional[str] = None
    alerts: List[AlertItem] = Field(default_factory=list)


def _authorise(request: Request, authorization: Optional[str]) -> None:
    token = (getattr(settings, "ALERT_WEBHOOK_TOKEN", "") or "").strip()
    if token:
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="Alert webhook token required")
        return
    host = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise HTTPException(status_code=403, detail="Alert webhook accepts private-network callers only")
    if not (address.is_private or address.is_loopback):
        raise HTTPException(status_code=403, detail="Alert webhook accepts private-network callers only")


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value or value.startswith("0001-"):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _workspace(db: AsyncSession, labels: Dict[str, str]) -> Optional[UUID]:
    wanted = labels.get("workspace_id")
    if wanted:
        try:
            found = (await db.execute(select(Workspace.id).where(Workspace.id == UUID(wanted)))).scalar_one_or_none()
            if found:
                return found
        except ValueError:
            pass
    # System alerts belong to the primary (oldest) workspace.
    return (await db.execute(select(Workspace.id).order_by(Workspace.created_at.asc()).limit(1))).scalar_one_or_none()


@router.post("/alerts")
async def receive_alerts(
    payload: AlertmanagerPayload,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    _authorise(request, authorization)
    now = datetime.now(timezone.utc)
    opened, refreshed, resolved, skipped = [], [], [], []
    for alert in payload.alerts:
        name = alert.labels.get("alertname", "unnamed alert")
        fingerprint = alert.fingerprint or f"{name}:{sorted(alert.labels.items())}"
        number = f"ALERT-{(alert.fingerprint or hashlib.sha256(fingerprint.encode()).hexdigest())[:40]}"
        severity = _SEVERITY.get(alert.labels.get("severity", "warning").lower(), "medium")
        summary = alert.annotations.get("summary") or name
        description = alert.annotations.get("description") or summary
        incident = (await db.execute(select(Incident).where(Incident.incident_number == number))).scalar_one_or_none()
        workspace_id = incident.workspace_id if incident else await _workspace(db, alert.labels)
        if workspace_id is None:
            skipped.append(name)
            continue

        if alert.status == "resolved":
            if incident is None or incident.status in ("resolved", "closed"):
                continue
            incident.status = "resolved"
            incident.resolved_at = _parse_time(alert.endsAt) or now
            incident.resolution = "Alert resolved in Prometheus."
            incident.updated_at = now
            title, feed_severity, action = f"Resolved: {summary}", "success", False
            resolved.append(number)
        else:
            if incident is None:
                incident = Incident(
                    id=uuid4(), workspace_id=workspace_id, incident_number=number,
                    title=summary[:500], description=description, severity=severity,
                    priority=_PRIORITY[severity], category="monitoring", incident_type=name[:50],
                    status="open", affected_systems=[alert.labels.get("job") or alert.labels.get("service") or "jarv"],
                    affected_users=0, impact_description=description, tags=["alertmanager", name],
                    detected_at=_parse_time(alert.startsAt) or now, post_mortem_completed=False,
                    meta_data={"fingerprint": fingerprint, "labels": alert.labels,
                               "generator_url": alert.generatorURL},
                    created_at=now, updated_at=now,
                )
                db.add(incident)
                opened.append(number)
            else:
                if incident.status in ("resolved", "closed"):
                    incident.status = "open"
                    incident.resolved_at = None
                incident.updated_at = now
                refreshed.append(number)
            title = f"{'Critical alert' if severity == 'critical' else 'Alert'}: {summary}"
            feed_severity, action = _FEED_SEVERITY[severity], severity == "critical"
        db.add(LiveOperationsFeedItem(
            id=uuid4(), workspace_id=workspace_id, item_type="incident", severity=feed_severity,
            title=title[:500], message=description[:1000], requires_action=action,
            created_at=now, updated_at=now,
        ))
    await db.flush()
    if skipped:
        logger.warning(f"alerts skipped (no workspace exists yet): {skipped}")
    return {"opened": opened, "refreshed": refreshed, "resolved": resolved, "skipped": skipped}
