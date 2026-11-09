"""
JAI uses the skill made for the job. On 9 November "make a high-quality video ad for Plexecute" was built by the
general builder with no skill loaded ("What JAI used: no skills loaded"), although BRAG is JAI's video-ad skill.
"""
from __future__ import annotations

from app.core.command.sandbox_engine import builder_method
from app.core.knowledge.skill_packs import named_skill


def test_a_video_ad_goes_to_brag_without_being_told():
    for brief in ("Make a high-quality video ad for Plexecute in C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES.",
                  "Make a fresh launch video for Plexecute", "Make a promo video for MYCO"):
        found = named_skill(brief)
        assert found is not None and found["pack"] == "brag", brief


def test_brag_named_on_its_own_is_brag():
    assert named_skill("Using BRAG, make a fresh Plexecute ad")["pack"] == "brag"


def test_other_work_and_edits_are_planned_as_usual():
    for brief in ("Build the marketing site with a hero video", "Make me a professional investor pitch deck",
                  "Edit the video ad: read the address as dot co dot U K", "Carry on with MYCO Phase 0",
                  "Fix the page with accessibility in mind", "Use all your marketing skills on the launch video"):
        assert named_skill(brief) is None, brief


def test_the_builder_is_told_to_use_a_skill_made_for_its_work():
    assert "invoke it and follow it" in builder_method("Make the onboarding flow")
