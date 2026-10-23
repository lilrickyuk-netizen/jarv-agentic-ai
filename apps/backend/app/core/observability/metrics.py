"""
JARV Backend - Prometheus metrics

Exposed at ``GET /metrics`` in the Prometheus text format (0.0.4).

Two kinds of metric:

- Process metrics for the API process that serves the scrape: HTTP request
  counts and latency histograms (by route template, not raw path, so ids do
  not explode cardinality), and process CPU / memory.
- System metrics read from the database and broker at scrape time. Missions
  run on the workers, so worker activity is measured where it is recorded:
  mission status, stale heartbeats, queue age, recoveries, durations,
  outcomes, tokens, agent runs, tool calls, approvals waiting, memory, and
  verified lessons. These are correct whichever process did the work and
  survive restarts. They are cached for ``DB_CACHE_SECONDS`` so frequent
  scrapes cannot load the database.
"""
from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

HTTP_BUCKETS: Tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
DB_CACHE_SECONDS = 10.0
WORKER_PING_CACHE_SECONDS = 30.0
WINDOW_HOURS = 24


def _escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(labels: Dict[str, object]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items()) + "}"


def _num(value: float) -> str:
    if value == math.inf:
        return "+Inf"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(float(value)) if isinstance(value, float) else str(value)


class _Family:
    def __init__(self, name: str, kind: str, help_text: str):
        self.name, self.kind, self.help = name, kind, help_text
        self.samples: List[Tuple[str, Dict[str, object], float]] = []

    def add(self, value: float, suffix: str = "", **labels: object) -> "_Family":
        self.samples.append((self.name + suffix, labels, value))
        return self

    def render(self) -> List[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} {self.kind}"]
        lines += [f"{name}{_labels(labels)} {_num(value)}" for name, labels, value in self.samples]
        return lines


# ----- HTTP metrics (this process) -------------------------------------------------

class HttpMetrics:
    """Request counts and latency histograms, safe across threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Dict[Tuple[str, str, str], int] = defaultdict(int)
        self._buckets: Dict[Tuple[str, str], List[int]] = {}
        self._sum: Dict[Tuple[str, str], float] = defaultdict(float)
        self._n: Dict[Tuple[str, str], int] = defaultdict(int)
        self._in_flight = 0

    def started(self) -> None:
        with self._lock:
            self._in_flight += 1

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        key = (method, route)
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._counts[(method, route, str(status))] += 1
            buckets = self._buckets.setdefault(key, [0] * len(HTTP_BUCKETS))
            for i, bound in enumerate(HTTP_BUCKETS):
                if seconds <= bound:
                    buckets[i] += 1
            self._sum[key] += seconds
            self._n[key] += 1

    def families(self) -> List[_Family]:
        with self._lock:
            total = _Family("http_requests_total", "counter", "HTTP requests by method, route template, and status.")
            for (method, route, status), count in sorted(self._counts.items()):
                total.add(count, method=method, route=route, status=status)
            hist = _Family("http_request_duration_seconds", "histogram", "HTTP request latency by method and route template.")
            for key in sorted(self._buckets):
                method, route = key
                for bound, count in zip(HTTP_BUCKETS, self._buckets[key]):
                    hist.add(count, "_bucket", method=method, route=route, le=_num(bound))
                hist.add(self._n[key], "_bucket", method=method, route=route, le="+Inf")
                hist.add(self._sum[key], "_sum", method=method, route=route)
                hist.add(self._n[key], "_count", method=method, route=route)
            flight = _Family("http_requests_in_flight", "gauge", "HTTP requests currently being served.")
            flight.add(self._in_flight)
            return [total, hist, flight]


http_metrics = HttpMetrics()


# ----- process metrics ---------------------------------------------------------------

def _process_families() -> List[_Family]:
    try:
        import psutil

        proc = psutil.Process()
        cpu = proc.cpu_times()
        families = [
            _Family("process_cpu_seconds_total", "counter", "Total user and system CPU time spent in seconds.")
            .add(cpu.user + cpu.system),
            _Family("process_resident_memory_bytes", "gauge", "Resident memory size in bytes.")
            .add(proc.memory_info().rss),
            _Family("process_start_time_seconds", "gauge", "Start time of the process since unix epoch in seconds.")
            .add(proc.create_time()),
        ]
        try:
            families.append(_Family("process_open_fds", "gauge", "Number of open file descriptors.")
                            .add(proc.num_fds()))
        except (AttributeError, OSError):
            pass
        return families
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"process metrics unavailable: {exc}")
        return []


# ----- system metrics from the database ------------------------------------------------

def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, math.ceil(q * len(sorted_values)) - 1))
    return float(sorted_values[index])


async def _db_families(db: AsyncSession) -> List[_Family]:
    from app.core.runtime import lifecycle
    from app.core.runtime.missions import MISSION_TASK_TYPE, STALE_AFTER_SECONDS
    from app.models.memory import Memory
    from app.models.operations import AuditLog
    from app.models.self_evolution import ExperienceRecord
    from app.models.task import Task

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=WINDOW_HOURS)
    families: List[_Family] = []
    command = Task.task_type == MISSION_TASK_TYPE

    by_status = _Family("jarv_missions", "gauge", "Missions by current status.")
    counts = dict((await db.execute(select(Task.status, func.count()).where(command).group_by(Task.status))).all())
    for status in sorted({*lifecycle._ALLOWED.keys(), *counts.keys()}):
        by_status.add(counts.get(status, 0), status=status)
    families.append(by_status)

    stale = (await db.execute(select(func.count()).where(
        command, Task.status == lifecycle.RUNNING,
        Task.heartbeat_at < now - timedelta(seconds=STALE_AFTER_SECONDS),
    ))).scalar() or 0
    families.append(_Family("jarv_missions_stale", "gauge",
                            "Running missions whose worker heartbeat is older than the stale threshold.").add(stale))

    oldest = (await db.execute(select(func.min(Task.updated_at)).where(
        command, Task.status == lifecycle.QUEUED))).scalar()
    age = 0.0
    if oldest is not None:
        oldest = oldest if oldest.tzinfo else oldest.replace(tzinfo=timezone.utc)
        age = max(0.0, (now - oldest).total_seconds())
    families.append(_Family("jarv_mission_queue_oldest_seconds", "gauge",
                            "Age of the oldest queued mission (0 when the queue is empty).").add(age))

    recoveries = (await db.execute(select(func.coalesce(func.sum(Task.retry_count), 0)).where(command))).scalar() or 0
    families.append(_Family("jarv_mission_recoveries", "gauge",
                            "Total times missions were recovered after their worker was lost.").add(recoveries))

    outcomes = _Family("jarv_mission_outcomes_24h", "gauge", "Missions that finished in the last 24 hours, by outcome.")
    rows = dict((await db.execute(select(Task.status, func.count()).where(
        command, Task.updated_at >= since,
        Task.status.in_(sorted(lifecycle.TERMINAL)),
    ).group_by(Task.status))).all())
    for status in sorted(lifecycle.TERMINAL):
        outcomes.add(rows.get(status, 0), status=status)
    families.append(outcomes)

    durations = sorted(float(v) for v in (await db.execute(select(Task.execution_duration_seconds).where(
        command, Task.updated_at >= since, Task.execution_duration_seconds.is_not(None),
        Task.status.in_(sorted(lifecycle.TERMINAL)),
    ).limit(5000))).scalars().all())
    summary = _Family("jarv_mission_duration_seconds", "summary",
                      "Duration of missions finished in the last 24 hours.")
    for q in (0.5, 0.9, 0.95, 0.99):
        summary.add(_quantile(durations, q), quantile=_num(q))
    summary.add(sum(durations), "_sum").add(len(durations), "_count")
    families.append(summary)

    tokens = (await db.execute(select(func.coalesce(func.sum(Task.tokens_used), 0)).where(
        command, Task.updated_at >= since))).scalar() or 0
    families.append(_Family("jarv_tokens_used_24h", "gauge", "Model tokens used by missions updated in the last 24 hours.")
                    .add(tokens))

    waiting = (await db.execute(select(func.count()).where(
        command, Task.status.in_((lifecycle.BLOCKED, lifecycle.WAITING_ON_APPROVAL))))).scalar() or 0
    families.append(_Family("jarv_approvals_waiting", "gauge", "Missions waiting for Richard's approval.").add(waiting))

    agents = _Family("jarv_agent_runs_24h", "gauge", "Agent executions in the last 24 hours, by agent and result.")
    for action, success, count in (await db.execute(
        select(AuditLog.action, AuditLog.success, func.count())
        .where(AuditLog.action_category == "agent", AuditLog.created_at >= since)
        .group_by(AuditLog.action, AuditLog.success)
    )).all():
        parts = (action or "").split(".")
        if len(parts) == 3 and parts[0] == "agent" and parts[2] in ("complete", "error"):
            agents.add(count, agent=parts[1], result="success" if parts[2] == "complete" and success else "failure")
    families.append(agents)

    tools = _Family("jarv_tool_calls_24h", "gauge", "Runtime tool calls in the last 24 hours, by tool and result.")
    for action, success, count in (await db.execute(
        select(AuditLog.action, AuditLog.success, func.count())
        .where(AuditLog.action_category == "tool_execution", AuditLog.created_at >= since)
        .group_by(AuditLog.action, AuditLog.success)
    )).all():
        tools.add(count, tool=(action or "").removeprefix("tool:"), result="success" if success else "failure")
    families.append(tools)

    memory = _Family("jarv_memories", "gauge", "Stored memories by category.")
    for category, count in (await db.execute(
        select(Memory.memory_category, func.count()).group_by(Memory.memory_category))).all():
        memory.add(count, category=category or "global")
    families.append(memory)

    lessons = _Family("jarv_lessons", "gauge", "Learned lessons by lifecycle status.")
    for status, count in (await db.execute(
        select(ExperienceRecord.lesson_status, func.count()).group_by(ExperienceRecord.lesson_status))).all():
        lessons.add(count, status=status or "candidate")
    families.append(lessons)
    return families


# ----- broker and workers -------------------------------------------------------------

_worker_cache: Tuple[float, Optional[int]] = (0.0, None)


def _ping_workers() -> Optional[int]:
    from app.core.celery import celery_app

    replies = celery_app.control.ping(timeout=1.0) or []
    return len(replies)


async def _broker_families() -> List[_Family]:
    from app.core.config import settings

    families: List[_Family] = []
    try:
        from app.core.redis import get_redis

        client = await get_redis()
        length = await client.llen("celery")
        families.append(_Family("celery_queue_length", "gauge",
                                "Messages waiting in the default Celery queue.").add(length, queue="celery"))
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"queue length unavailable: {exc}")

    if settings.TESTING:
        return families
    global _worker_cache
    checked, value = _worker_cache
    if time.monotonic() - checked > WORKER_PING_CACHE_SECONDS:
        try:
            value = await asyncio.wait_for(asyncio.to_thread(_ping_workers), timeout=3.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"worker ping failed: {exc}")
            value = 0
        _worker_cache = (time.monotonic(), value)
    families.append(_Family("jarv_workers_up", "gauge",
                            "Celery workers that answered a ping (cached for 30s).").add(value or 0))
    return families


_db_cache: Tuple[float, List[_Family]] = (0.0, [])
_db_lock = asyncio.Lock()


async def render(db: AsyncSession) -> str:
    """The full metrics page."""
    global _db_cache
    families: List[_Family] = list(http_metrics.families()) + _process_families()
    async with _db_lock:
        cached_at, cached = _db_cache
        if time.monotonic() - cached_at > DB_CACHE_SECONDS:
            try:
                cached = await _db_families(db)
                _db_cache = (time.monotonic(), cached)
            except Exception as exc:  # noqa: BLE001 - never fail the scrape; report the gap
                logger.error(f"database metrics failed: {exc}", exc_info=True)
                cached = []
    up = _Family("jarv_metrics_database_up", "gauge", "1 when database-backed metrics were collected.")
    families += cached + [up.add(1 if cached else 0)]
    families += await _broker_families()
    lines: List[str] = []
    for family in families:
        lines += family.render()
    return "\n".join(lines) + "\n"


def reset_caches() -> None:
    """Drop cached database and worker readings (tests)."""
    global _db_cache, _worker_cache
    _db_cache = (0.0, [])
    _worker_cache = (0.0, None)
