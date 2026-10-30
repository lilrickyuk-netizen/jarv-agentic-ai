"""
JARV Backend - Calendar feed API (Repair 15b)

JARV's calendar events (calendar_events, created by the agents' calendar tools) as a private
iCalendar (RFC 5545) subscription feed, so they appear in Richard's own calendar app with no
calendar password or OAuth grant:

- GET  /api/calendar/{workspace_id}/feed: the signed-in owner's subscription link (created on
  first use) and how to add it.
- POST /api/calendar/{workspace_id}/feed/rotate: a new link; the old one stops working.
- GET  /api/calendar/feed/{workspace_id}/{token}.ics: the feed itself. Calendar apps cannot
  sign in, so the link carries a secret: an HMAC of the workspace, its owner and a per-workspace
  salt under SECRET_KEY, compared in constant time. Read-only; nothing can be changed through it.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId
from app.core.config import settings
from app.core.database import get_db
from app.core.scoping import as_uuid
from app.models.integrations import CalendarEvent
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

SALT_KEY = "calendar_feed_salt"
HISTORY_DAYS = 90


def _token(workspace: Workspace, salt: str) -> str:
    message = f"calendar-feed:{workspace.id}:{workspace.owner_id}:{salt}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()[:40]


def _escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n") \
        .replace("\n", "\\n")


def _fold(line: str) -> str:
    """Fold a content line at 75 octets (RFC 5545 3.1)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        if len(current) + len(encoded) > (75 if not parts else 74):
            parts.append(current.decode("utf-8"))
            current = b""
        current += encoded
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def _stamp(value: datetime) -> str:
    value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def to_ics(workspace: Workspace, events: List[CalendarEvent]) -> str:
    now = _stamp(datetime.now(timezone.utc))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JARV//Agentic AI//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_escape(f'JARV - {workspace.name}')}", "X-PUBLISHED-TTL:PT15M"]
    for event in events:
        lines += ["BEGIN:VEVENT", f"UID:{event.id}@jarv", f"DTSTAMP:{now}",
                  f"DTSTART:{_stamp(event.start_time)}", f"DTEND:{_stamp(event.end_time)}",
                  f"SUMMARY:{_escape(event.title)}"]
        if event.description:
            lines.append(f"DESCRIPTION:{_escape(event.description)}")
        if event.location:
            lines.append(f"LOCATION:{_escape(event.location)}")
        for attendee in event.attendees or []:
            lines.append(f"ATTENDEE;RSVP=FALSE:mailto:{_escape(str(attendee))}")
        if event.updated_at:
            lines.append(f"LAST-MODIFIED:{_stamp(event.updated_at)}")
        for minutes in sorted({int(m) for m in (event.reminders or []) if int(m) >= 0}):
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(event.title)}",
                      f"TRIGGER:-PT{minutes}M", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


async def _owned(db: AsyncSession, user_id: str, workspace_id: UUID) -> Workspace:
    workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id,
                                                          Workspace.owner_id == as_uuid(user_id)))).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _public_base(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _link(request: Request, workspace: Workspace) -> Dict[str, Any]:
    token = _token(workspace, workspace.config[SALT_KEY])
    https_url = f"{_public_base(request)}/api/calendar/feed/{workspace.id}/{token}.ics"
    return {"url": https_url, "webcal_url": "webcal://" + https_url.split("://", 1)[1],
            "how_to_add": ["Google Calendar: Other calendars > + > From URL, paste the link.",
                           "Apple Calendar: File > New Calendar Subscription, paste the webcal link.",
                           "Outlook: Add calendar > Subscribe from web, paste the link."],
            "note": "Anyone with this link can see the calendar. Rotate it to make the old link stop working."}


async def _ensure_salt(db: AsyncSession, workspace: Workspace, rotate: bool = False) -> None:
    config = dict(workspace.config or {})
    if rotate or not config.get(SALT_KEY):
        config[SALT_KEY] = secrets.token_urlsafe(16)
        workspace.config = config
        await db.commit()
        await db.refresh(workspace)


@router.get("/{workspace_id}/feed")
async def feed_link(workspace_id: UUID, request: Request, user_id: CurrentUserId,
                    db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    workspace = await _owned(db, user_id, workspace_id)
    await _ensure_salt(db, workspace)
    return _link(request, workspace)


@router.post("/{workspace_id}/feed/rotate")
async def rotate_link(workspace_id: UUID, request: Request, user_id: CurrentUserId,
                      db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    workspace = await _owned(db, user_id, workspace_id)
    await _ensure_salt(db, workspace, rotate=True)
    return _link(request, workspace)


@router.get("/feed/{workspace_id}/{token}.ics")
async def feed(workspace_id: UUID, token: str, db: AsyncSession = Depends(get_db)) -> Response:
    workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
    salt = (workspace.config or {}).get(SALT_KEY) if workspace is not None else None
    if not salt or not hmac.compare_digest(_token(workspace, salt), token or ""):
        raise HTTPException(status_code=404, detail="Calendar not found")
    since = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)
    events = (await db.execute(select(CalendarEvent).where(
        CalendarEvent.workspace_id == workspace_id, CalendarEvent.owner_id == workspace.owner_id,
        CalendarEvent.is_active.is_(True), CalendarEvent.end_time >= since)
        .order_by(CalendarEvent.start_time))).scalars().all()
    return Response(content=to_ics(workspace, list(events)), media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "private, max-age=300",
                             "Content-Disposition": 'inline; filename="jarv.ics"'})
