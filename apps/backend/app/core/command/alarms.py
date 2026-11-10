"""
JAI Backend - Alarms on JAI's own behaviour

Richard, 10 November (from AskRich's monitoring): JAI should notice its own failures within a minute instead of Richard
finding out after 44 minutes. A mission raises each alarm at most once, as a warning in the Live Operations feed with
the mission attached:
  - routed: the brief went to the Lead Builder although nothing in it was about software;
  - slow: research or writing has run longer than SLOW_SPECIALIST_MINUTES (it should take minutes);
  - costly: research or writing has spent more than COSTLY_SPECIALIST_USD;
  - stuck: a software round completed nothing, so Opus takes the next one.
An alarm never stops the work and never fails the mission when it cannot be written.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

SLOW_SPECIALIST_MINUTES = 15
COSTLY_SPECIALIST_USD = 1.0


async def raise_once(team: Any, key: str, title: str, message: str, severity: str = "warning") -> bool:
    """Write the alarm to the feed unless this mission already raised it. True when it was written."""
    raised = getattr(team, "_alarms", None)
    if raised is None:
        raised = set()
        setattr(team, "_alarms", raised)
    if key in raised:
        return False
    raised.add(key)
    try:
        from app.core.database import AsyncSessionLocal
        from app.models import LiveOperationsFeedItem

        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            db.add(LiveOperationsFeedItem(
                id=uuid4(), workspace_id=team.runtime.workspace_id, item_type="alarm", severity=severity,
                title=title, message=message[:2000], related_task_id=team.runtime.task_id, requires_action=False,
                created_at=now, updated_at=now))
            await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - an alarm is a notice; the mission goes on
        logger.warning(f"alarm {key} not written: {exc}")
        return False


def _minutes_since(started_at: Optional[str]) -> float:
    try:
        started = datetime.fromisoformat(str(started_at))
    except (TypeError, ValueError):
        return 0.0
    return (datetime.now(timezone.utc) - started).total_seconds() / 60


async def check(team: Any) -> None:
    """The running checks, made each time the mission's progress is saved."""
    lead = (team.packages or [None])[0]
    acting = getattr(lead, "acting_as", None)
    if not acting:
        return
    role = lead.role
    minutes = _minutes_since(getattr(team, "_started_at", None))
    if minutes >= SLOW_SPECIALIST_MINUTES:
        await raise_once(team, "slow", f"{role} is taking longer than expected",
                         f"This {role} mission has run for {int(minutes)} minutes; research and writing should take "
                         "a few. It stops by itself after one round. Cancel it if it looks stuck.")
    spent = float(getattr(team.lead.usage, "cost_usd", 0) or 0)
    if spent >= COSTLY_SPECIALIST_USD:
        await raise_once(team, "costly", f"{role} has spent ${spent:.2f}",
                         f"This {role} mission has spent ${spent:.2f}, more than research and writing should "
                         f"(alarm at ${COSTLY_SPECIALIST_USD:.2f}; it stops at its own limit).")
