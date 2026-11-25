"""
22 November: a footage video ran three rounds for about £10, writing its own caption and render code because
OpenMontage's Remotion composer was never installed. A video mission now has its own allowance across every round
and its check (VIDEO_MISSION_MAX_COST_USD), runs on Sonnet at medium effort, composes with OpenMontage's own
composers, and stops once its render passes. Pure: no model, no sandbox, nothing spent.
"""
from __future__ import annotations

import asyncio

from app.core.command import mission_budget
from app.core.config import settings
from tests.repo_paths import repo_path


class _Redis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def incrbyfloat(self, key, value):
        self.store[key] = float(self.store.get(key) or 0) + value

    async def expire(self, key, seconds):
        return True


def test_a_missions_own_allowance_limits_it_below_the_setting(monkeypatch):
    redis = _Redis()

    async def fake():
        return redis

    monkeypatch.setattr(mission_budget, "_redis", fake)
    monkeypatch.setattr(settings, "MISSION_MAX_COST_USD", 12.0)

    async def run():
        before = await mission_budget.left("video")
        await mission_budget.set_allowance("video", 4.0)
        await mission_budget.add("video", 3.0)
        after = await mission_budget.left("video")
        await mission_budget.set_allowance("big", 50.0)
        return before, after, await mission_budget.left("big")

    before, after, big = asyncio.run(run())
    assert before == 12.0 and after == 1.0  # three rounds share the one $4 allowance
    assert big == 12.0  # never above the setting
    monkeypatch.setattr(settings, "MISSION_MAX_COST_USD", 0.0)
    assert asyncio.run(mission_budget.left("video")) == 1.0  # the video's own allowance still holds


def test_a_video_runs_on_sonnet_within_its_own_allowance():
    from app.core.command import mission_org

    run = mission_org.SKILL_RUNS["openmontage"]
    assert run["model"] == mission_org.VIDEO and settings.VIDEO_MODEL == "claude-sonnet-5-5"
    assert run["effort"] == "medium"
    assert settings.VIDEO_MISSION_MAX_COST_USD == 4.0
    source = repo_path("apps", "backend", "app", "core", "command", "mission_org.py").read_text()
    assert "set_allowance(self.runtime.task_id" in source and "VIDEO_MISSION_MAX_COST_USD" in source


def test_the_sandbox_installs_openmontages_remotion_composer_from_its_lockfile():
    dockerfile = repo_path("services", "openhands", "Dockerfile").read_text()
    assert "cd /opt/openmontage/remotion-composer" in dockerfile and "npm ci" in dockerfile
    assert "npx remotion browser ensure" in dockerfile
    assert dockerfile.index("ARG OPENMONTAGE_COMMIT") < dockerfile.index("npx remotion browser ensure")
    assert "Remotion's packages are not installed" not in dockerfile


def test_richard_is_the_judge_of_videos_and_the_maker_runs_only_technical_checks():
    """22 November, Richard: "im the verifier when it comes to videos"."""
    from app.core.command.mission_org import studio_goal

    assert settings.VIDEO_INDEPENDENT_CHECK is False
    source = repo_path("apps", "backend", "app", "core", "command", "mission_org.py").read_text()
    assert "if settings.VIDEO_INDEPENDENT_CHECK:" in source
    goal = studio_goal()
    assert "freezedetect" in goal and "Richard judges the video himself" in goal
