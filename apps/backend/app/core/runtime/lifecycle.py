"""
JARV Backend - Mission lifecycle

Every command mission moves through these statuses and only along these
transitions. ``transition`` is the single place a mission's status changes;
it rejects illegal moves and appends each change to the task's status history
(``meta_data["status_history"]``) so the path a mission took is auditable.

Mapping to the design's task states:
    pending              -> CREATED
    queued               -> ASSIGNED          (waiting for a worker)
    running              -> RUNNING
    recovering           -> RESUMING_FROM_CHECKPOINT  (worker lost; being re-queued)
    waiting_on_approval  -> WAITING_ON_APPROVAL       (a tool hit a hard boundary)
    needs_continuation   -> RUNNING (paused at a step limit; continued automatically)
    blocked              -> BLOCKED           (command needs approval before it starts)
    completed            -> COMPLETE
    partial / failed / cancelled -> terminal outcomes
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

PENDING = "pending"
QUEUED = "queued"
RUNNING = "running"
RECOVERING = "recovering"
WAITING_ON_APPROVAL = "waiting_on_approval"
BLOCKED = "blocked"
NEEDS_CONTINUATION = "needs_continuation"
COMPLETED = "completed"
PARTIAL = "partial"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL = frozenset({COMPLETED, PARTIAL, FAILED, CANCELLED})
ACTIVE = frozenset({QUEUED, RUNNING, RECOVERING, NEEDS_CONTINUATION})
# Statuses a user sees as "still going" in the dashboard.
IN_FLIGHT = frozenset({PENDING, QUEUED, RUNNING, RECOVERING, NEEDS_CONTINUATION})

_ALLOWED: Dict[str, frozenset] = {
    PENDING: frozenset({QUEUED, RUNNING, BLOCKED, FAILED, CANCELLED}),
    QUEUED: frozenset({RUNNING, FAILED, CANCELLED}),
    RUNNING: frozenset({COMPLETED, PARTIAL, FAILED, WAITING_ON_APPROVAL, BLOCKED,
                        RECOVERING, CANCELLED, NEEDS_CONTINUATION}),
    NEEDS_CONTINUATION: frozenset({QUEUED, RUNNING, CANCELLED, FAILED}),
    RECOVERING: frozenset({QUEUED, RUNNING, FAILED, CANCELLED}),
    WAITING_ON_APPROVAL: frozenset({QUEUED, RUNNING, CANCELLED, FAILED, BLOCKED}),
    BLOCKED: frozenset({QUEUED, CANCELLED, FAILED}),
    # A finished mission can be retried on request; it re-enters the queue.
    COMPLETED: frozenset(),
    # A partial mission can also be closed so nothing resumes it.
    PARTIAL: frozenset({QUEUED, RUNNING, CANCELLED}),
    FAILED: frozenset({QUEUED}),
    CANCELLED: frozenset(),
}

# Legacy statuses written before the lifecycle was enforced.
_LEGACY = {"approved": BLOCKED, "complete": COMPLETED, "in_progress": RUNNING,
           "executing": RUNNING, "resuming": RECOVERING}

_HISTORY_LIMIT = 50


class IllegalTransition(ValueError):
    """Raised when code tries to move a mission along a transition that does not exist."""


def normalise(status: Optional[str]) -> str:
    value = (status or PENDING).strip().lower()
    return _LEGACY.get(value, value)


def can_transition(current: Optional[str], target: str) -> bool:
    return target in _ALLOWED.get(normalise(current), frozenset())


def record_history(task: Any, previous: str, target: str, *, reason: str = "",
                   actor: str = "system", extra: Optional[Dict[str, Any]] = None) -> None:
    """Append a status change made outside ``transition`` (an atomic claim in SQL)."""
    meta = dict(task.meta_data or {})
    history = list(meta.get("status_history") or [])[-(_HISTORY_LIMIT - 1):]
    entry: Dict[str, Any] = {"from": previous, "to": target,
                             "at": datetime.now(timezone.utc).isoformat(), "actor": actor}
    if reason:
        entry["reason"] = reason[:500]
    if extra:
        entry.update(extra)
    history.append(entry)
    meta["status_history"] = history
    task.meta_data = meta


def transition(task: Any, target: str, *, reason: str = "", actor: str = "system",
               extra: Optional[Dict[str, Any]] = None) -> str:
    """Move ``task`` to ``target`` or raise ``IllegalTransition``.

    Also stamps started/completed/failed times and records the change in the
    task's status history. Returns the previous status.
    """
    previous = normalise(task.status)
    if target not in _ALLOWED:
        raise IllegalTransition(f"Unknown mission status '{target}'")
    if target not in _ALLOWED.get(previous, frozenset()):
        raise IllegalTransition(f"Mission cannot move from '{previous}' to '{target}'")
    now = datetime.now(timezone.utc)
    task.status = target
    task.updated_at = now
    if target == RUNNING and not task.started_at:
        task.started_at = now
    if target == COMPLETED:
        task.completed_at = now
    if target == FAILED:
        task.failed_at = now
    record_history(task, previous, target, reason=reason, actor=actor, extra=extra)
    return previous
