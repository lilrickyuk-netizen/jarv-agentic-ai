"""
18 November: the engineering sandbox reaps the processes a render leaves behind, and renders with the Hyperframes
version that works in it. Pure: reads the repository's own files, nothing runs, nothing is spent.
"""
from __future__ import annotations

import yaml

from tests.repo_paths import repo_path


def test_the_sandbox_runs_an_init_that_reaps_finished_processes():
    """17 November: every hung render left its Chromium processes defunct (over 1,000) because uvicorn was PID 1."""
    compose = yaml.safe_load(repo_path("docker-compose.yml").read_text())
    assert compose["services"]["openhands"]["init"] is True


def test_the_sandbox_has_the_hyperframes_version_that_renders_installed():
    """17 November: 0.9.64 hung at capture start with 0 frames; 0.9.58 rendered each ad in about 73 seconds.
    npx uses an installed package when the command names no version, as the skills' `npx hyperframes` does."""
    dockerfile = repo_path("services", "openhands", "Dockerfile").read_text()
    assert "ARG HYPERFRAMES_VERSION=0.9.58" in dockerfile
    assert 'npm install -g "hyperframes@${HYPERFRAMES_VERSION}"' in dockerfile


def test_a_video_edit_in_richards_folder_is_the_builders_mission():
    """18 November: the music edit went to the one-off research and QA answer, which cannot render, twice."""
    from app.core.command.service import CommandService

    brief = ("Edit the Plexecute video ad in C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES\\"
             "brag-output-2026-11-17-215700: leave the background music out of its composition and keep every "
             "sound effect exactly as it is.")
    assert CommandService._detect_intent(brief) == "agent_task"
    question = "What video is in C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES\\brag-output-2026-11-17-215700?"
    assert CommandService._detect_intent(question) != "agent_task"
