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
