"""
Two-stage routing and alarms on JAI's own behaviour (Richard, 10 November, from AskRich's design): rules first, then a
small model with a confidence when no rule matches, Richard's corrections learned, and an alarm within a minute when
work lands on the Lead Builder without being software, or research runs long or costs too much. The model is replaced
by a stand-in here: no test spends provider credit.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.core.command import alarms, work_type


def _run(coro):
    return asyncio.run(coro)


def _forget():
    async def wipe():
        await (await work_type._redis()).delete(work_type.CORRECTIONS_KEY)
    _run(wipe())


def test_rules_decide_first_and_the_model_is_never_asked_for_them(monkeypatch):
    asked = []

    async def model(text):
        asked.append(text)
        return {"specialist": "content", "confidence": 0.99, "why": "x"}

    monkeypatch.setattr(work_type, "_ask_model", model)
    _forget()
    software = _run(work_type.classify("Fix the failing tests in the MYCO backend"))
    assert software["route"] is None and software["source"] == "rules"
    for brief in ("Carry on with MYCO Phase 1", "Complete phase 2 of the spec", "Build the MVP for Secundas"):
        assert _run(work_type.classify(brief))["source"] == "rules", brief
    sales = _run(work_type.classify("Build an investor database for Plexecute"))
    assert sales["route"]["specialist"] == "sales" and sales["source"] == "keywords"
    assert asked == []


def test_the_model_chooses_when_no_rule_matches_and_low_confidence_falls_back(monkeypatch):
    answers = {"confident": {"specialist": "marketing", "confidence": 0.86, "why": "growth outreach"},
               "unsure": {"specialist": "marketing", "confidence": 0.4, "why": "maybe"}}
    current = {"answer": answers["confident"]}

    async def model(text):
        return current["answer"]

    monkeypatch.setattr(work_type, "_ask_model", model)
    _forget()
    brief = "Find people who might champion Plexecute and how to reach them"
    chosen = _run(work_type.classify(brief))
    assert chosen["source"] == "model" and chosen["route"]["specialist"] == "marketing"
    assert chosen["confidence"] == 0.86 and chosen["route"]["skills"]
    current["answer"] = answers["unsure"]
    unsure = _run(work_type.classify(brief))
    assert unsure["route"] is None and unsure["source"] == "default" and unsure["confidence"] == 0.4
    document = _run(work_type.classify(brief + " in notes/champions.md"))
    assert document["route"]["specialist"] == "research" and document["source"] == "document"
    current["answer"] = {"specialist": "builder", "confidence": 0.9, "why": "software"}
    assert _run(work_type.classify(brief))["route"] is None


def test_a_model_that_fails_or_times_out_leaves_the_rules_in_charge(monkeypatch):
    async def broken(text):
        raise TimeoutError("router took too long")

    monkeypatch.setattr(work_type, "_ask_model", broken)
    _forget()
    result = _run(work_type.classify("Sort out who to talk to next in growth/people.xlsx"))
    assert result["route"]["specialist"] == "research" and result["source"] == "document"


def test_richards_correction_wins_for_a_brief_like_it(monkeypatch):
    async def model(text):
        return {"specialist": "research", "confidence": 0.9, "why": "x"}

    monkeypatch.setattr(work_type, "_ask_model", model)
    _forget()
    brief = "Find people who might champion Plexecute and how to reach them"
    _run(work_type.learn(brief, "sales"))
    learned = _run(work_type.classify("Find people who could champion Plexecute and how we reach them"))
    assert learned["source"] == "learned" and learned["route"]["specialist"] == "sales"
    assert _run(work_type.classify("Compare prices of standing desks"))["source"] == "model"
    try:
        _run(work_type.learn(brief, "astrologer"))
        raise AssertionError("an unknown specialist was accepted")
    except ValueError:
        pass
    _forget()


def test_the_router_reads_only_richards_words():
    note = "\n\nPROGRESS FROM EARLIER ROUNDS OF THIS SAME MISSION\n- `python3 build.py`: exit 0"
    result = _run(work_type.classify("Build an investor database for Plexecute" + note))
    assert result["route"]["specialist"] == "sales"


class _Session:
    added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, row):
        _Session.added.append(row)

    async def commit(self):
        return None


def _team(acting, minutes, spent):
    started = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    package = SimpleNamespace(acting_as=acting, role="Marketing Lead" if acting else "Lead Builder")
    return SimpleNamespace(packages=[package], _started_at=started, lead=SimpleNamespace(usage=SimpleNamespace(
        cost_usd=spent)), runtime=SimpleNamespace(workspace_id=uuid4(), task_id=uuid4()))


def test_alarms_fire_once_for_slow_or_costly_research_and_never_for_software(monkeypatch):
    import app.core.database as database

    monkeypatch.setattr(database, "AsyncSessionLocal", _Session)
    _Session.added = []
    team = _team("marketing", minutes=alarms.SLOW_SPECIALIST_MINUTES + 1, spent=alarms.COSTLY_SPECIALIST_USD + 0.2)
    _run(alarms.check(team))
    _run(alarms.check(team))  # raised once each, however often progress is saved
    titles = [row.title for row in _Session.added]
    assert len(titles) == 2 and "taking longer than expected" in titles[0] and "has spent $1.20" in titles[1]
    assert all(row.item_type == "alarm" and row.severity == "warning" for row in _Session.added)
    _Session.added = []
    _run(alarms.check(_team("marketing", minutes=3, spent=0.05)))
    _run(alarms.check(_team(None, minutes=300, spent=20)))
    assert _Session.added == []


def test_an_alarm_that_cannot_be_written_does_not_stop_the_mission(monkeypatch):
    import app.core.database as database

    class Broken(_Session):
        async def commit(self):
            raise RuntimeError("database away")

    monkeypatch.setattr(database, "AsyncSessionLocal", Broken)
    team = _team("marketing", minutes=60, spent=0)
    assert _run(alarms.raise_once(team, "slow", "t", "m")) is False


def test_the_specialist_with_most_of_the_briefs_words_wins(monkeypatch):
    """10 November: "the benefits platforms on the investor list" sent a creators-and-communities brief to Sales."""
    brief = ("In C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES, add to growth/Plexecute-Waitlist-Growth.xlsx. Creators: "
             "find UK fitness creators through their talent agency pages. Communities: read each subreddit's rules. "
             "Drop the Employers sheet: Plexecute reaches employers through the benefits platforms on the investor "
             "list instead.")
    route = work_type.specialist_for(brief)
    assert route["specialist"] == "marketing" and "creators" in route["matched"] and "communities" in route["matched"]
    assert work_type.specialist_for("make me a professional pitch deck for plexecute aimed at investors")[
        "specialist"] == "content"  # a tie goes to the deck to make


def test_richards_correction_wins_over_the_word_lists(monkeypatch):
    async def model(text):
        return None

    monkeypatch.setattr(work_type, "_ask_model", model)
    _forget()
    brief = "Plan the investor newsletter for Plexecute's backers"
    assert _run(work_type.classify(brief))["source"] == "keywords"
    _run(work_type.learn(brief, "content"))
    corrected = _run(work_type.classify("Plan the investor newsletter for Plexecute backers"))
    assert corrected["source"] == "learned" and corrected["route"]["specialist"] == "content"
    _forget()
