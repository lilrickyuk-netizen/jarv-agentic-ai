"""
16 and 17 November: a request naming a skill without a typed folder path went to a one-off answer instead of the
skill's mission ("Use my BRAG skill on Plexecute, starting from the project in brag-output-..." reviewed the old video
instead of making a new one). These tests hold the fix.
"""
from app.core.command.service import CommandService


def test_a_named_skill_is_its_mission_without_a_typed_folder_path():
    brief = ("Use my BRAG skill on Plexecute, starting from the project in brag-output-2026-11-16-183500 — reuse its "
             "screen recordings, logo, music and composition; don't record the app again.")
    assert CommandService._detect_intent(brief) == "agent_task"
    assert CommandService._detect_intent("use my social skill to make 3 carousels for Plexecute") == "agent_task"
    # with a path, as before
    assert CommandService._detect_intent(
        r"In C:\Users\lilri\Projects\PLEXECUTE_IMAGES, use my BRAG skill on the app") == "agent_task"


def test_a_question_about_a_skill_keeps_its_quick_answer():
    assert CommandService._detect_intent("what does the BRAG skill do?") != "agent_task"
