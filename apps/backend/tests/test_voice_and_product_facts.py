"""
18 November: a video run no longer installs Hyperframes' voice or reads the product's website every time. The
sandbox has the voice built in, and the first run in a folder saves the product's facts and real assets for the runs
after it. Pure: reads the repository's files and a temporary folder, nothing runs, nothing is spent.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

from tests.repo_paths import repo_path


def test_the_sandbox_has_hyperframes_voice_built_in_where_the_agents_shell_finds_it():
    dockerfile = repo_path("services", "openhands", "Dockerfile").read_text()
    assert "ARG KOKORO_ONNX_VERSION=0.6.1" in dockerfile and "ARG SOUNDFILE_VERSION=0.14.0" in dockerfile
    assert 'pip install "kokoro-onnx==${KOKORO_ONNX_VERSION}" "soundfile==${SOUNDFILE_VERSION}"' in dockerfile
    assert "ENV HYPERFRAMES_PYTHON=/opt/kokoro/bin/python" in dockerfile
    # The agent's shell is `su openhands -`, a login shell that keeps none of the image's environment.
    assert "/etc/profile.d/jai-voice.sh" in dockerfile
    # After Hyperframes, so adding it never makes Docker download OpenHands or the toolchain again.
    assert dockerfile.index("hyperframes@${HYPERFRAMES_VERSION}") < dockerfile.index("python3 -m venv /opt/kokoro")


def _folder_with_facts(tmp_path: Path, days_old: float) -> Path:
    facts = tmp_path / ".jai" / "product.md"
    facts.parent.mkdir(parents=True)
    facts.write_text("# Plexecute\nPlan your life. Execute the plan. (https://plexecute.com, 18 November 2026)\n")
    then = time.time() - days_old * 86400
    os.utime(facts, (then, then))
    return tmp_path


def test_a_fresh_fact_file_is_read_instead_of_the_website(tmp_path):
    from app.core.command.mission_org import product_facts_rule

    rule = product_facts_rule(_folder_with_facts(tmp_path, 3), "Use your BRAG skill to make 1 video for Plexecute")
    assert ".jai/product.md (3 days old)" in rule and "instead of reading the website again" in rule


def test_no_fact_file_an_old_one_or_a_refresh_reads_the_site_and_saves_them(tmp_path):
    from app.core.command.mission_org import product_facts_rule

    first = product_facts_rule(tmp_path, "Use your BRAG skill to make 1 video for Plexecute")
    assert "Read the product's real website" in first and ".jai/product-assets/" in first
    assert "Read the product's real website" in product_facts_rule(None, "")
    old = _folder_with_facts(tmp_path, 31)
    assert "Read the product's real website" in product_facts_rule(old, "Use your BRAG skill")
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    _folder_with_facts(fresh, 1)
    assert "Read the product's real website" in product_facts_rule(
        fresh, "Use your BRAG skill, and refresh the product facts from the website first")


def test_only_video_skill_runs_get_the_ready_tools_and_the_fact_file(tmp_path, monkeypatch):
    from app.core.command import mission_org
    from app.core.workspaces import fs_inspector

    monkeypatch.setattr(fs_inspector, "host_to_container", lambda host: tmp_path)
    team = SimpleNamespace(workspace_root="C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES")
    team._product_facts = lambda mission: mission_org.MissionTeam._product_facts(team, mission)
    brag = mission_org.MissionTeam._skill_package(team, {"skill": "brag", "sandbox": ["product_designer"]}, ["R1"],
                                                  "Use your BRAG skill")
    assert mission_org.VIDEO_TOOLS_READY in brag.goal and ".jai/product.md" in brag.goal
    other = mission_org.MissionTeam._skill_package(team, {"skill": "frontend-design", "sandbox": ["coding_agent"]},
                                                   ["R1"], "Use your frontend-design skill")
    assert "Install what the skill needs yourself." in other.goal
    assert mission_org.VIDEO_TOOLS_READY not in other.goal and ".jai/product.md" not in other.goal
