"""
18 November, OpenMontage mission a00ac5ea: its video was finished in the first round, but its third round read
"carry on" in JAI's own progress notes, took over the music edit's acceptance ledger (R1-R6 about brag-no-music.mp4)
and spent its rounds on another mission's checks, then waited on Richard to approve ffprobe on its own MP4. Also: a
fact file Richard may have written himself is added to, never rewritten. Pure: a temporary folder and the rules.
"""
from __future__ import annotations

import json
import os
import time

from app.core.workspaces.fs_inspector import classify_command

OLD_LEDGER = {"phase": "", "items": [{"id": "R1", "text": "Save brag-no-music.mp4", "check": "python3 .jai/verify-video.py R1",
                                     "passes": False}]}
NEW_BRIEF = ("Use OpenMontage to make 1 short vertical video for Plexecute in C:\\Users\\lilri\\Projects\\"
             "PLEXECUTE_IMAGES. Publish and post nothing.")


def _folder_with_ledger(tmp_path, monkeypatch):
    from app.core.workspaces import fs_inspector

    (tmp_path / ".jai").mkdir()
    (tmp_path / ".jai" / "ledger.json").write_text(json.dumps(OLD_LEDGER))
    monkeypatch.setattr(fs_inspector, "host_to_container", lambda host: tmp_path)
    return "C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES"


def test_a_later_round_of_new_work_never_takes_an_old_missions_ledger(tmp_path, monkeypatch):
    from app.core.command import ledger

    host = _folder_with_ledger(tmp_path, monkeypatch)
    later_round = NEW_BRIEF + "\n\nPROGRESS FROM EARLIER ROUNDS: the video is finished; carry on and finish the checks."
    assert ledger.requirements(host, NEW_BRIEF) is None
    assert ledger.requirements(host, later_round) is None


def test_richard_saying_carry_on_still_takes_the_ledger(tmp_path, monkeypatch):
    from app.core.command import ledger

    host = _folder_with_ledger(tmp_path, monkeypatch)
    taken = ledger.requirements(host, "Carry on with the Plexecute video edit")
    assert taken and taken[0]["id"] == "R1"


def test_reading_a_videos_streams_needs_no_approval():
    assert classify_command("ffprobe -v error -show_entries stream=index,codec_type,width,height:format=duration "
                            "-of json plexecute-who-finishes-the-week.mp4") == "safe"


def test_an_old_fact_file_is_added_to_and_never_rewritten(tmp_path):
    from app.core.command.mission_org import product_facts_rule

    facts = tmp_path / ".jai" / "product.md"
    facts.parent.mkdir()
    facts.write_text("# Plexecute guide written by Richard\n")
    then = time.time() - 40 * 86400
    os.utime(facts, (then, then))
    rule = product_facts_rule(tmp_path, "Use your BRAG skill")
    assert "Read the product's real website" in rule and "never delete or rewrite the rest" in rule
    assert "never delete" not in product_facts_rule(tmp_path / "empty", "Use your BRAG skill")


def test_a_carousel_in_richards_folder_is_the_builders_mission_and_not_a_video_skill_run():
    """18 November, mission d1aadd3e: the procrastination carousel went to research and QA and made no slides."""
    from app.core.command.service import CommandService
    from app.core.knowledge.skill_packs import skill_for

    brief = ('Make 1 Instagram and TikTok carousel for Plexecute in C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES: "5 things '
             'that kill procrastination". Publish and post nothing.')
    assert CommandService._detect_intent(brief) == "agent_task"
    assert skill_for(brief) is None


def test_a_running_missions_card_shows_the_folder_its_brief_names():
    """18 November: every running mission's card said "no folder" until it finished."""
    from types import SimpleNamespace

    from app.api.command import _folder

    running = SimpleNamespace(result=None, title="Make 1 carousel",
                              description='Make 1 carousel in C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES: "5 things"')
    assert _folder(running) == "C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES"
    done = SimpleNamespace(result={"workspace_path": "C:\\Users\\lilri\\Projects\\MYCO"}, title="x", description="x")
    assert _folder(done) == "C:\\Users\\lilri\\Projects\\MYCO"
    assert _folder(SimpleNamespace(result=None, title="Find investors", description="Find investors")) is None
