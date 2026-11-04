"""
The voice talks rather than recites, and starts sooner: its instructions say how to talk (short first sentence, no
read-out lists or timestamps, offer the rest), there is no reasoning pass before a spoken reply, and the live state
it reads before every reply is compact and always whole JSON.
"""
import json

from app.core.config import settings
from app.core.voice import live


def test_the_voice_is_told_to_talk_not_recite():
    style = live.CONVERSATION_STYLE
    for rule in ("short sentence of under ten words", "Never recite", "Want the rest?", "'what else'",
                 "not clock readings"):
        assert rule in style, rule
    assert settings.VOICE_PIPELINE_REASONING == "none"


def test_the_live_state_is_compact_and_always_whole_json():
    facts = {
        "recent_missions": [{"id": str(i), "title": f"Mission {i}", "last_report": "x" * 5000} for i in range(8)],
        "memories": [{"content": "y" * 2000, "type": "source"}, {"content": "Prefers British English " * 40,
                                                                 "type": "preference"}],
        "knowledge": [{"title": "k", "content": "z" * 3000}] * 5,
        "mission_asked_about": {"title": "Plexecute plan", "result": "The plan. " * 4000},
        "now": "Wednesday",
    }
    small = live.compact_for_voice(facts)
    assert len(small["recent_missions"]) == 5 and all(len(m["last_report"]) == 350 for m in small["recent_missions"])
    assert [m["type"] for m in small["memories"]] == ["preference"] and len(small["memories"][0]["content"]) == 240
    text = live.voice_state_text(small)
    assert len(text) <= live.VOICE_STATE_CHARS
    parsed = json.loads(text)                                            # never cut mid-JSON
    assert parsed["mission_asked_about"]["result"].startswith("The plan.") and parsed["now"] == "Wednesday"


def test_a_mission_is_not_started_from_words_that_do_not_say_what_it_is():
    for empty in ("New mission, Jay, keep me updated.", "Start a mission", "Jay, new task please", "Keep me posted."):
        assert live.mission_brief_is_real(empty) is False, empty
    for real in ("Carry on building MYCO from Phase 0", "Keep me updated on the carry on building my core mission",
                 "Make a launch banner for Plexecute", "Research competitors"):
        assert live.mission_brief_is_real(real) is True, real


def test_the_workspace_is_taken_from_what_he_said_as_heard():
    from types import SimpleNamespace as W

    spaces = [W(name="MYCO", id=1), W(name="Plexecute", id=2), W(name="Command Center", id=3)]
    assert live.workspace_named_in(spaces, "carry on building my core mission").name == "MYCO"
    assert live.workspace_named_in(spaces, "a banner for Plexecute's waitlist").name == "Plexecute"
    assert live.workspace_named_in(spaces, "what's the weather") is None


def test_both_voices_speak_as_richards_jarvis_style_aide():
    for brain in (True, False):
        text = live.spoken_instructions([], brain=brain)
        assert "You are Jay, a JARVIS-style aide" in text and "Received Pronunciation" in text
        assert "'boss' now and then" in text and "never 'sir'" in text and "Never recite" in text
