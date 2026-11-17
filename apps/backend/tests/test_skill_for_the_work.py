"""
Which skill runs a mission. A skill Richard names runs it (named_skill). From 17 November new video work runs on
BRAG, JAI's video skill, without his having to name it (skill_for): two ads the builder made without a skill
(mission 092182a7) were not good enough to post, and the first BRAG video was. On 9 November the builder had made a
good ad for about four pounds and BRAG cost many times that; Richard judged the skill's work worth it.
"""
from __future__ import annotations

from app.core.command.sandbox_engine import builder_method
from app.core.knowledge.skill_packs import named_skill, skill_for


def test_a_video_ad_names_no_skill():
    """The words alone name no skill; skill_for decides that new video work runs on BRAG."""
    for brief in ("Make a high-quality video ad for Plexecute in C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES.",
                  "Make a fresh launch video for Plexecute", "Make a promo video for MYCO"):
        assert named_skill(brief) is None, brief


def test_brag_named_on_its_own_is_brag():
    assert named_skill("Using BRAG, make a fresh Plexecute ad")["pack"] == "brag"


def test_other_work_and_edits_are_planned_as_usual():
    for brief in ("Build the marketing site with a hero video", "Make me a professional investor pitch deck",
                  "Edit the video ad: read the address as dot co dot U K", "Carry on with MYCO Phase 0",
                  "Fix the page with accessibility in mind", "Use all your marketing skills on the launch video"):
        assert named_skill(brief) is None, brief


def test_the_builder_uses_skills_as_references_not_as_a_pipeline():
    assert "do not hand the mission to a whole pipeline" in builder_method("Make the onboarding flow")


def test_a_skill_brief_in_a_workspace_is_a_mission_whatever_words_it_uses():
    from app.core.command.service import CommandService

    brief = ("Using BRAG, make a fresh video ad for Plexecute in C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES. In the "
             "narration, write the web address as plexecute dot co dot U K. Don't post it anywhere.")
    assert CommandService._detect_intent(brief) == "agent_task"
    assert CommandService._detect_intent("Draft a marketing email for the Plexecute launch") == "company_workflow"


def test_new_work_in_a_folder_with_an_old_ledger_starts_its_own():
    """9 November: the Plexecute pitch deck was handed the ad mission's ledger."""
    assert "This is new work" in builder_method("Make me an investor pitch deck for Plexecute")
    assert "This is new work" not in builder_method("Carry on with the Plexecute video ad")
    assert "This is new work" not in builder_method("Carry on building MYCO Phase 0")


def test_new_video_work_runs_on_brag_without_naming_it():
    for brief in ("Make 2 viral-worthy short vertical video ads for Plexecute. Each must be emotional, educational "
                  "and entertaining.", "Make a promo video for MYCO", "Make 3 TikTok reels for Plexecute",
                  "Create an animated explainer for Plexecute", "Make 2 viral video ads for the Plexecute app"):
        entry = skill_for(brief)
        assert entry is not None and (entry["pack"], entry["skill"]) == ("brag", "brag"), brief
    assert skill_for("Use your BRAG Slim skill to make a Plexecute video")["skill"] == "brag-slim"   # named wins


def test_software_changes_and_a_no_brag_brief_are_not_new_video_work():
    for brief in ("Build the marketing site with a hero video", "Build the app with an intro video",
                  "Edit the video ad: read the address as dot co dot U K", "Carry on with the Plexecute video ad",
                  "Fix the onboarding video player in the app", "Make a video ad without BRAG",
                  "Use all your marketing skills on the launch video", "Make me a professional investor pitch deck",
                  "Make a carousel post for Instagram"):
        assert skill_for(brief) is None, brief


def test_a_video_brief_is_a_mission_whatever_words_it_uses():
    from app.core.command.service import CommandService

    assert CommandService._detect_intent("Make 2 viral video ads for Plexecute") == "agent_task"

