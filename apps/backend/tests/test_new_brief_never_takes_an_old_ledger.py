"""
23 November: a new brief is never read as "carry on" because it ends with "...and finish". Four video briefs that
night ended "save it ... and finish"; each took over the Plexecute folder's old carousel ledger (R1-R10,
.jai/check-carousel.sh), was judged against slides it never made, and one carried on a cancelled mission. Pure:
the brief patterns and the ledger reader on a temporary folder; nothing runs, nothing is spent.
"""
from __future__ import annotations

import json

from app.core.command import ledger
from app.core.command.resume import CARRY_ON

TONIGHT = (
    "Use OpenMontage to make a faceless vertical video for Plexecute. Run freezedetect, save it as "
    "plexecute-faceless-01.mp4 at the top of the folder and finish.",
    "Render once, check with freezedetect, save it as plexecute-balcony-founder-edit-final.mp4 at the top of the "
    "folder and finish.",
    "Use OpenMontage to finish the effects edit in the project.",
)
CARRYING_ON = ("Carry on", "Finish the rest of the booking-partners database", "finish it", "Please finish off",
               "Continue the carousel", "Finish the mission")


def test_a_brief_that_ends_with_finish_is_new_work():
    for brief in TONIGHT:
        assert not CARRY_ON.search(brief), brief
    for brief in CARRYING_ON:
        assert CARRY_ON.search(brief), brief


def test_tonights_briefs_never_take_the_folders_carousel_ledger(tmp_path, monkeypatch):
    from app.core.workspaces import fs_inspector

    (tmp_path / ".jai").mkdir()
    (tmp_path / ".jai" / "ledger.json").write_text(json.dumps({"phase": None, "items": [
        {"id": "R1", "text": "7 slides", "check": "sh .jai/check-carousel.sh", "passes": True}]}))
    monkeypatch.setattr(fs_inspector, "host_to_container", lambda host: tmp_path)
    for brief in TONIGHT:
        assert ledger.requirements("C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES", brief) is None, brief
    assert ledger.requirements("C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES", "Carry on with the carousel")
