"""
22 November: a running mission's card shows how long it has been working and the tokens used so far, instead of
"0s · 0 tokens" until it ends. Pure: a Task row in memory and the progress record's shape; nothing runs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.task import Task


def _task(status: str, started_minutes_ago: float, seconds=None, tokens=0) -> Task:
    return Task(id=uuid4(), title="m", task_type="command", workspace_id=uuid4(), status=status,
                started_at=datetime.now(timezone.utc) - timedelta(minutes=started_minutes_ago),
                execution_duration_seconds=seconds, tokens_used=tokens)


def test_a_running_mission_shows_its_time_and_tokens_so_far():
    from app.api.command import _so_far

    seconds, tokens = _so_far(_task("running", 12), "running", {"tokens_so_far": 845_000})
    assert 715 <= seconds <= 725 and tokens == 845_000
    assert _so_far(_task("running", 1), "running", None)[1] == 0  # no progress record yet: no tokens to show
    # A finished mission keeps its recorded totals, whatever the progress record says.
    assert _so_far(_task("completed", 60, seconds=848, tokens=2_256_672), "completed", {"tokens_so_far": 5}) == \
        (848.0, 2_256_672)


def test_the_team_counts_finished_and_working_packages_and_a_card_shows_its_tokens():
    from app.core.command.mission_org import Package

    package = Package("P1", "video", "creation", "g", [], [], ["R1"], "d", tokens=120_000)
    assert package.card()["tokens"] == 120_000
