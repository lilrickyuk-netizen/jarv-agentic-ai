"""
The result card at the top of every mission report (Richard, 10 November: he was pasting reports to Claude to have them
explained). Made from the mission's own record, with the plain-English line and next steps written by a small model
that is replaced by a stand-in here (no test spends provider credit).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.core.command import result_card

FINISHED = {"success": True, "needs_continuation": False, "answer": "Introductions are written for 32 organisations.",
            "requirements": [{"id": f"R{i}", "status": "done"} for i in range(1, 9)],
            "report": {"confidence": "High"}}


def test_the_card_from_the_record_alone():
    started = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat(timespec="seconds")
    card = asyncio.run(result_card.make(FINISHED, mission="Write the introductions", cost_usd=0.36,
                                        started_at=started))
    assert card["status"] == "Done and checked" and card["confidence"] == "High"
    assert card["numbers"] == [{"label": "requirements met", "value": "8 of 8"}, {"label": "time", "value": "6 min"},
                               {"label": "cost", "value": "28p"}]
    text = result_card.render(card)
    assert text.startswith("### Result\n**Done and checked.**")
    assert "8 of 8 requirements met · 6 min · 28p · confidence: high" in text and text.endswith("---\n\n")


def test_waiting_and_unfinished_missions_say_so():
    waiting = asyncio.run(result_card.make(FINISHED, mission="m", waiting=["Review the introductions"]))
    assert waiting["status"] == "Done: waiting for you" and waiting["needs_you"] == ["Review the introductions"]
    assert "**Needs you:**\n- Review the introductions" in result_card.render(waiting)
    open_round = {"success": False, "needs_continuation": True, "answer": "",
                  "requirements": [{"status": "done"}, {"status": "open"}],
                  "verification": {"unmet": ["R2 the deck is missing"]}}
    card = asyncio.run(result_card.make(open_round, mission="m", cost_usd=2.5))
    assert card["status"] == "Not finished yet: JAI carries on" and card["confidence"] == "Low"
    assert card["numbers"][0]["value"] == "1 of 2" and card["numbers"][-1]["value"] == "£1.95"
    assert "**Still open:**\n- R2 the deck is missing" in result_card.render(card)


def test_the_model_writes_the_line_and_next_steps(monkeypatch):
    async def written(report, mission, record):
        return {"headline": "32 introductions written; 6 are ready to send this week.",
                "numbers": [{"label": "introductions", "value": "32"}],
                "needs_you": ["Read the six priority-one introductions"],
                "next_steps": ["Send the four investor forms", "Email Reward Gateway", "Run the growth list"]}

    monkeypatch.setattr(result_card, "_write", written)
    card = asyncio.run(result_card.make(FINISHED, mission="m", cost_usd=0.36))
    text = result_card.render(card)
    assert text.startswith("### Result\n**32 introductions written; 6 are ready to send this week.**")
    assert card["numbers"][0] == {"label": "introductions", "value": "32"}
    assert "1. Send the four investor forms" in text and "- Read the six priority-one introductions" in text


def test_a_model_that_fails_leaves_the_card_from_the_record(monkeypatch):
    async def broken(report, mission, record):
        raise TimeoutError("too slow")

    monkeypatch.setattr(result_card, "_write", broken)
    card = asyncio.run(result_card.make(FINISHED, mission="m"))
    assert card["headline"] == "Done and checked." and card["next_steps"] == []
