"""
JARV Backend - Trace context

Every log line carries the request it came from and, when it belongs to a
mission, the mission id. A command submitted through the API logs with its
request id; the same mission then logs with its mission id on whichever worker
runs it, so one mission can be followed across the API and the workers.
"""
from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

request_id_var: ContextVar[Optional[str]] = ContextVar("jarv_request_id", default=None)
mission_id_var: ContextVar[Optional[str]] = ContextVar("jarv_mission_id", default=None)

# Accept a caller-supplied request id only if it is a plain token (no log injection).
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def accept_request_id(value: Optional[str]) -> Optional[str]:
    return value if value and _SAFE_ID.match(value) else None


@contextmanager
def mission_context(mission_id: object) -> Iterator[None]:
    token = mission_id_var.set(str(mission_id))
    try:
        yield
    finally:
        mission_id_var.reset(token)


class TraceContextFilter(logging.Filter):
    """Adds request_id and mission_id to every record ('-' when absent)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = request_id_var.get() or "-"
        if not getattr(record, "mission_id", None):
            record.mission_id = mission_id_var.get() or "-"
        return True
