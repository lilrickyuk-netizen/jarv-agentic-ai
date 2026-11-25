"""
25 November (mission 00d44272, accountability-02): the studio ignored OpenMontage's clip-factory pipeline and wrote
one Composition.tsx importing only "remotion" and fonts: no composer component, no video_compose, none of the stage
tools, empty asset folders. OpenMontage's own rule (AGENT_GUIDE.md, Rule Zero, at the pinned 2e003e65) is that every
production goes through a pipeline, stage by stage, each stage's director skill read first; its checkpoint protocol
lets a person pre-authorise the whole run with one approval_policy decision. The studio now does exactly that, and
the mission's report lists the OpenMontage tools and components that actually ran, from OpenMontage's own log
(events.jsonl) and the edit_decisions VideoCompose rendered. Pure: no model, no sandbox.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

from app.core.command.mission_org import studio_goal
from app.core.creative import openmontage_used


def test_the_studio_runs_the_chosen_pipeline_stage_by_stage_with_its_tools():
    goal = studio_goal()
    assert "through its own pipeline" in goal and "Rule Zero" in goal
    assert "Choose the pipeline in pipeline_defs/" in goal and "clip-factory" in goal and "talking-head" in goal
    assert "init_project(" in goal and "approval_policy" in goal and "checkpoint-protocol.md" in goal
    assert "skills/pipelines/<pipeline>/<stage>-director.md" in goal
    for tool in ("face_tracker", "auto_reframe", "silence_cutter", "color_grade", "audio_enhance", "transcriber"):
        assert tool in goal, tool
    assert "human_approved=True" in goal and "never stop at a gate" in goal
    assert "Skip the publish stage" in goal
    assert "VideoCompose operation render with the edit stage's edit_decisions" in goal
    assert "remotion-composer's own compositions and components" in goal
    # a hand-written composition only when the brief asks for one, and never instead of the stages' tools
    assert "only then read skills/meta/taste-direction.md" in goal
    assert "the stages before compose still run with their tools" in goal
    assert "Do not run its staged pipeline" not in goal and "validate nothing" not in goal


def _project(root, name, pipeline, events, edit=None, old=False):
    folder = root / "openmontage-projects" / name
    folder.mkdir(parents=True)
    (folder / "project.json").write_text(json.dumps({"project_id": name, "pipeline_type": pipeline}))
    now = datetime.now(timezone.utc)
    with open(folder / "events.jsonl", "w") as f:
        for i, (tool, ok, depth) in enumerate(events):
            ts = (now - timedelta(days=3) if old else now).isoformat()
            f.write(json.dumps({"ts": ts, "tool": tool, "event": "start"}) + "\n")
            f.write(json.dumps({"ts": ts, "tool": tool, "event": "finish", "success": ok,
                                **({"depth": depth} if depth else {})}) + "\n")
        f.write("not json\n")
    if edit is not None:
        (folder / "checkpoint_edit.json").write_text(json.dumps({"stage": "edit", "status": "completed",
                                                                 "artifacts": {"edit_decisions": edit}}))
    (folder / "checkpoint_idea.json").write_text(json.dumps({"stage": "idea", "status": "completed"}))
    if old:
        stamp = time.time() - 3 * 86400
        for p in folder.iterdir():
            os.utime(p, (stamp, stamp))
        os.utime(folder, (stamp, stamp))
    return folder


def test_the_report_lists_the_tools_and_components_that_ran(tmp_path):
    edit = {"render_runtime": "remotion", "renderer_family": "presenter", "subtitles": {"enabled": True},
            "cuts": [{"id": "c1", "source": "a1"}, {"id": "c2", "type": "hero_title", "text": "Day 2"}],
            "overlays": [{"type": "stat_reveal", "text": "3x"}], "end_tag": {"text": "Follow"}}
    _project(tmp_path, "accountability-02", "clip-factory",
             [("transcriber", True, None), ("face_tracker", True, None), ("auto_reframe", True, None),
              ("color_grade", False, None), ("video_compose", True, None), ("ffmpeg_inner", True, 1)], edit)
    _project(tmp_path, "older-mission", "talking-head", [("silence_cutter", True, None)], old=True)
    since = datetime.now(timezone.utc) - timedelta(hours=2)
    used = openmontage_used.used(tmp_path, since)
    assert used["pipelines"] == ["clip-factory"]  # the older mission's project is not this mission's
    assert used["tools"] == {"transcriber": 1, "face_tracker": 1, "auto_reframe": 1, "video_compose": 1}
    assert used["failed"] == {"color_grade": 1}  # a nested provider call (depth 1) is not counted
    assert used["components"] == ["TalkingHead", "OffthreadVideo", "HeroTitle", "StatReveal", "CaptionOverlay",
                                  "EndTag"]
    line = openmontage_used.summary(used)
    assert line.startswith("**OpenMontage used:** pipeline clip-factory (stages done: edit, idea)")
    assert "tools: transcriber ×1, face_tracker ×1, auto_reframe ×1, video_compose ×1" in line
    assert "failed: color_grade ×1" in line and "components: TalkingHead, OffthreadVideo, HeroTitle" in line


def test_a_hand_written_composition_and_no_tools_are_said_plainly(tmp_path):
    _project(tmp_path, "custom", "cinematic", [], {"render_runtime": "remotion", "composition_mode": "atelier",
                                                    "bespoke": {"entry": "/w/x/src/index.tsx",
                                                                "composition_id": "Main"}})
    used = openmontage_used.used(tmp_path, datetime.now(timezone.utc) - timedelta(hours=1))
    assert used["components"] == ["hand-written composition Main (atelier)"]
    assert "none of its tools ran" in openmontage_used.summary(used)
    nothing = openmontage_used.used(tmp_path / "empty", None)
    assert openmontage_used.summary(nothing) == ("**OpenMontage used:** none of its tools ran and no OpenMontage "
                                                 "project was made in this mission's folder.")


def test_every_videocompose_render_is_given_openmontages_own_render_time_limit():
    """25 November, mission 84779dd7: four 4K clips hit VideoCompose's default max(600, scenes x 15) s limit."""
    from app.core.command.mission_org import REMOTION_TIMEOUT_MS

    assert REMOTION_TIMEOUT_MS == 3_600_000
    assert "remotion_timeout_ms 3600000" in studio_goal()
