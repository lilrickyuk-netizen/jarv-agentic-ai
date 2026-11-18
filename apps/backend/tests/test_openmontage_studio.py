"""
18 November: OpenMontage (calesthio/OpenMontage, AGPL-3.0), an agent-run video studio that starts from a reference
video and has a character-animation pipeline, is built into JAI's engineering sandbox and runs when a brief names it.
Pure: the repository's files, the skill choice, the mission's package and the sandbox's command rules; nothing runs,
nothing is spent.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.core.command.sandbox_policy import Scope, check_command
from tests.repo_paths import repo_path

ROOT = "/host/workspaces/PLEXECUTE_IMAGES"
SCOPE = Scope(root=ROOT)
BRIEF = ("Use OpenMontage to make 1 short vertical video for Plexecute in C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES, "
         "starting from the reference video viral-references/reference-1.mp4.")


def test_the_sandbox_has_openmontage_at_a_pinned_commit_with_what_it_runs():
    dockerfile = repo_path("services", "openhands", "Dockerfile").read_text()
    assert "ARG OPENMONTAGE_COMMIT=2e003e65fa99a0f329478a2c1cdcf26bc481933a" in dockerfile
    assert 'checkout --quiet "${OPENMONTAGE_COMMIT}"' in dockerfile
    assert "/opt/openmontage/.venv/bin/pip install -r /opt/openmontage/requirements.txt" in dockerfile
    assert "playwright install" in dockerfile and "chown -R openhands:openhands /opt/openmontage" in dockerfile
    assert "/etc/profile.d/jai-studio.sh" in dockerfile
    # After the voice, so adding it never makes Docker download OpenHands, the toolchain or Hyperframes again.
    assert dockerfile.index("python3 -m venv /opt/kokoro") < dockerfile.index("ARG OPENMONTAGE_COMMIT")


def test_a_brief_naming_openmontage_runs_the_studio_and_brag_stays_the_default():
    from app.core.knowledge import skill_packs

    assert skill_packs.skill_for(BRIEF)["skill"] == "openmontage"
    assert skill_packs.skill_for("Use Open Montage to make a reel for Plexecute")["skill"] == "openmontage"
    assert skill_packs.skill_for("Make 1 short vertical video ad for Plexecute")["skill"] == "brag"


def test_the_studio_package_runs_openmontage_in_richards_folder_and_never_publishes(tmp_path, monkeypatch):
    from app.core.command import mission_org
    from app.core.knowledge.skill_packs import STUDIO_SKILL
    from app.core.workspaces import fs_inspector

    monkeypatch.setattr(fs_inspector, "host_to_container", lambda host: tmp_path)
    team = SimpleNamespace(workspace_root="C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES")
    team._product_facts = lambda mission: mission_org.MissionTeam._product_facts(team, mission)
    package = mission_org.MissionTeam._skill_package(team, STUDIO_SKILL, ["R1"], BRIEF)
    assert "/opt/openmontage/AGENT_GUIDE.md" in package.goal and "OPENMONTAGE_PROJECTS_DIR" in package.goal
    assert "never the publish stage" in package.goal and "never ask for an API key" in package.goal
    assert mission_org.VIDEO_TOOLS_READY in package.goal and ".jai/product.md" in package.goal
    assert package.max_cost == 10.0
    check = mission_org.MissionTeam._creative_check(STUDIO_SKILL)
    assert "/opt/openmontage/skills/meta/reviewer.md" in check and "reference video" in check


def test_the_studio_folder_is_a_place_to_work_and_other_projects_are_still_refused():
    assert check_command("cd /opt/openmontage", ROOT, SCOPE) is None
    assert check_command(".venv/bin/python -m tools.tool_registry", "/opt/openmontage", SCOPE) is None
    assert check_command(f"cd {ROOT}", "/opt/openmontage", SCOPE) is None
    assert "outside this mission's workspace" in check_command("ls /host/workspaces/Other", "/opt/openmontage",
                                                               SCOPE)
    assert "outside this mission's workspace" in check_command("ls", "/opt", SCOPE)
