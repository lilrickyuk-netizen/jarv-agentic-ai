"""Repair 12b: metrics, alert intake, and trace context.

Covers a valid Prometheus exposition, HTTP metrics by route template, mission
and approval gauges read from the database, the optional metrics token, the
Alertmanager webhook (incident open, de-duplicate, resolve, auth), and request
and mission ids on log records.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.observability.context import (
    TraceContextFilter, accept_request_id, mission_context, request_id_var,
)
from app.core.observability.metrics import reset_caches
from app.models.company_operations import LiveOperationsFeedItem
from app.models.operations import Incident
from app.models.task import Task

_SAMPLE = re.compile(
    r'^[a-zA-Z_:][a-zA-Z0-9_:]*(\{([a-zA-Z_][a-zA-Z0-9_]*="([^"\\]|\\.)*",?)*\})? '
    r'(-?[0-9.]+([eE][-+]?[0-9]+)?|\+Inf|-Inf|NaN)$'
)


@pytest.fixture(autouse=True)
def fresh_metric_caches():
    reset_caches()
    yield
    reset_caches()


def _metrics(client) -> str:
    response = client.get("/metrics")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    return response.text


def _value(text: str, series: str) -> float:
    for line in text.splitlines():
        if line.startswith(series + " "):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"{series} not found")


def test_exposition_is_valid_prometheus_text(client):
    client.get("/health")
    text = _metrics(client)
    names = set()
    for line in text.strip().splitlines():
        if line.startswith("# HELP ") or line.startswith("# TYPE "):
            names.add(line.split()[2])
            continue
        assert _SAMPLE.match(line), f"invalid sample line: {line!r}"
    for required in ("http_requests_total", "http_request_duration_seconds", "jarv_missions",
                     "jarv_missions_stale", "jarv_approvals_waiting", "jarv_metrics_database_up",
                     "jarv_mission_duration_seconds", "process_resident_memory_bytes"):
        assert required in names, required
    assert _value(text, "jarv_metrics_database_up") == 1


def test_http_metrics_use_route_templates_not_raw_paths(client):
    raw_id = str(uuid4())
    client.get("/health")
    client.get(f"/api/command/tasks/{raw_id}")  # 401, but the template is recorded
    text = _metrics(client)
    assert 'http_requests_total{method="GET",route="/health",status="200"}' in text
    assert 'route="/api/command/tasks/{task_id}"' in text
    assert raw_id not in text
    bucket = [l for l in text.splitlines()
              if l.startswith('http_request_duration_seconds_bucket{method="GET",route="/health",le="+Inf"}')]
    assert bucket and float(bucket[0].rsplit(" ", 1)[1]) >= 1


def test_mission_and_approval_gauges_come_from_the_database(client, db_session, test_workspace):
    now = datetime.now(timezone.utc)
    rows = [
        ("queued", None), ("queued", None), ("running", now),
        ("running", now - timedelta(minutes=30)), ("blocked", None), ("failed", None),
    ]
    for status, heartbeat in rows:
        db_session.add(Task(id=uuid4(), workspace_id=test_workspace.id, title="m", task_type="command",
                            status=status, priority=5, heartbeat_at=heartbeat,
                            updated_at=now - timedelta(minutes=20), created_at=now))
    db_session.commit()
    text = _metrics(client)
    assert _value(text, 'jarv_missions{status="queued"}') == 2
    assert _value(text, 'jarv_missions{status="running"}') == 2
    assert _value(text, "jarv_missions_stale") == 1
    assert _value(text, "jarv_approvals_waiting") == 1
    assert _value(text, 'jarv_mission_outcomes_24h{status="failed"}') == 1
    assert _value(text, "jarv_mission_queue_oldest_seconds") >= 1100


def test_metrics_token_is_enforced_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "scrape-secret-123")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = client.get("/metrics", headers={"Authorization": "Bearer scrape-secret-123"})
    assert ok.status_code == 200


def _alert(status="firing", fingerprint="a1b2c3d4e5f60718", severity="critical"):
    return {"status": status, "receiver": "jarv", "alerts": [{
        "status": status, "fingerprint": fingerprint,
        "labels": {"alertname": "JarvWorkersDown", "severity": severity, "job": "jarv-backend"},
        "annotations": {"summary": "No JARV workers are running",
                        "description": "No Celery worker answered a ping for 3 minutes."},
        "startsAt": "2026-10-23T10:00:00Z", "endsAt": "0001-01-01T00:00:00Z",
    }]}


def test_alerts_open_deduplicate_and_resolve_incidents(client, db_session, test_workspace, monkeypatch):
    monkeypatch.setattr(settings, "ALERT_WEBHOOK_TOKEN", "hook-secret-456")
    headers = {"Authorization": "Bearer hook-secret-456"}
    assert client.post("/api/observability/alerts", json=_alert()).status_code == 401

    first = client.post("/api/observability/alerts", json=_alert(), headers=headers)
    assert first.status_code == 200, first.text
    assert len(first.json()["opened"]) == 1
    again = client.post("/api/observability/alerts", json=_alert(), headers=headers)
    assert again.json()["refreshed"] == first.json()["opened"]

    incidents = db_session.query(Incident).all()
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.status == "open" and incident.severity == "critical"
    assert incident.workspace_id == test_workspace.id

    resolved = client.post("/api/observability/alerts", json=_alert(status="resolved"), headers=headers)
    assert resolved.json()["resolved"] == first.json()["opened"]
    db_session.expire_all()
    assert db_session.query(Incident).one().status == "resolved"
    titles = [item.title for item in db_session.query(LiveOperationsFeedItem).all()]
    assert any(t.startswith("Critical alert:") for t in titles)
    assert any(t.startswith("Resolved:") for t in titles)
    flagged = [i for i in db_session.query(LiveOperationsFeedItem).all() if i.title.startswith("Critical")]
    assert all(i.requires_action for i in flagged)


def test_alert_webhook_rejects_public_callers_without_a_token(client, monkeypatch):
    monkeypatch.setattr(settings, "ALERT_WEBHOOK_TOKEN", "")
    # The test client's address is not a private IP, so it is refused.
    assert client.post("/api/observability/alerts", json=_alert()).status_code == 403


def test_log_records_carry_request_and_mission_ids():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    token = request_id_var.set("req-abcdef12")
    try:
        with mission_context("mission-1234"):
            TraceContextFilter().filter(record)
    finally:
        request_id_var.reset(token)
    assert record.request_id == "req-abcdef12" and record.mission_id == "mission-1234"

    bare = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    TraceContextFilter().filter(bare)
    assert bare.request_id == "-" and bare.mission_id == "-"

    assert accept_request_id("good-id_123.45") == "good-id_123.45"
    assert accept_request_id("bad id\nX-Injected: 1") is None


def test_incoming_request_id_is_echoed_and_unsafe_ones_replaced(client):
    kept = client.get("/health", headers={"X-Request-ID": "dashboard-req-0001"})
    assert kept.headers["X-Request-ID"] == "dashboard-req-0001"
    replaced = client.get("/health", headers={"X-Request-ID": "x"})
    assert replaced.headers["X-Request-ID"] != "x" and len(replaced.headers["X-Request-ID"]) >= 32
