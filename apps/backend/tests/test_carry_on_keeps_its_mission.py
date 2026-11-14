"""
Carrying on keeps the mission it is about: its checklist, its folder and its agent (14 November: a typed "carry on
with the booking-partners database" took over a newer investors mission, ran in another workspace that had no
workbook, and went to the Sales Lead instead of the Partnerships Lead). And a list mission sees the facts of its own
workbook, so it knows when its targets are met. Real: Task and Workspace rows in the test database, the routing and
the workbook reader. No model is called.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.agents.workspace_ops import xlsx_bytes, xlsx_facts, xlsx_read, xlsx_text
from app.core.command.mission_org import MissionTeam
from app.core.command.resume import last_state, topic
from app.models.task import Task
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair11_memory_learning import _seed

BOOKING = ("JAI, your mission is to build a comprehensive UK and USA business partnership contact database for "
           "Plexecute: national chains, regional chains and independent businesses that take bookings.")
INVESTORS = "Build the investors and potential buyers database for Plexecute in outreach/ and keep drafts unsent."
FOLLOW_UP = ("Carry on with the booking-partners database: stop adding rows, rename the sheets to National Chains, "
             "Regional Chains, Independents, Decision-Makers and Read Me, remove duplicates and finish.")
OPEN = {"requirements": [{"id": "R1", "text": "40 national chains", "status": "done", "evidence": "rows"},
                         {"id": "R2", "text": "sheet names", "status": "open", "evidence": ""}],
        "verification": {"verified": False}}


def _run(coro):
    return asyncio.run(coro)


def test_topic_words_say_what_the_work_is_about():
    assert {"booking", "partner", "database", "national", "chain"} <= topic(FOLLOW_UP)
    assert not topic("Carry on, please finish the rest")
    assert len(topic(FOLLOW_UP) & topic(BOOKING)) > len(topic(FOLLOW_UP) & topic(INVESTORS))


def test_carry_on_takes_over_the_mission_it_names_in_its_own_folder():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, plexecute, _ = await _seed(db, with_agent=False)
            acceptance = uuid4()
            db.add(Workspace(id=acceptance, owner_id=owner, name="_jai_acceptance",
                             slug=f"acc-{acceptance.hex[:8]}", description="", workspace_type="test",
                             authority_level=6, is_active=True))
            now = datetime.now(timezone.utc)
            booking = Task(id=uuid4(), title="Booking partners", description=BOOKING, task_type="command",
                           workspace_id=plexecute, status="partial", result=OPEN,
                           created_at=now - timedelta(hours=2), updated_at=now - timedelta(hours=2))
            investors = Task(id=uuid4(), title="Investors", description=INVESTORS, task_type="command",
                             workspace_id=acceptance, status="partial", result=OPEN,  # newer, other work
                             created_at=now - timedelta(hours=1), updated_at=now - timedelta(hours=1))
            db.add_all([booking, investors])
            await db.commit()
            found = await last_state(db, acceptance, None, FOLLOW_UP)
            bare = await last_state(db, acceptance, None, "Carry on")
            return booking.id, investors.id, plexecute, found, bare

    booking_id, investors_id, plexecute, found, bare = _run(run())
    assert found["task_id"] == str(booking_id)          # the mission it names, not the newer one
    assert found["workspace_id"] == plexecute            # in that mission's own workspace
    assert found["brief"] == BOOKING                     # whose brief picks the agent
    assert bare["task_id"] == str(investors_id)          # "carry on" alone: the latest in this workspace


def test_a_carried_mission_goes_back_to_the_agent_who_started_it():
    team = MissionTeam.__new__(MissionTeam)
    team.route, team.route_from = {}, BOOKING
    assert _run(team._role(FOLLOW_UP)) == "partnerships"
    fresh = MissionTeam.__new__(MissionTeam)
    fresh.route, fresh.route_from = {}, None
    assert _run(fresh._role("Find investors for Plexecute")) == "sales"


def test_a_list_mission_sees_its_workbooks_facts():
    sheets = [{"name": "National chains", "rows": [["Country", "Company", "Source links"],
                                                   ["UK", "Pizza Express", "https://a"], ["US", "Olive Garden", ""],
                                                   ["UK", "Toni&Guy", "https://t"]]},
              {"name": "Regional chains", "rows": [["Country", "Company", "Source links"],
                                                   ["UK", "Pizza Express", "https://b"]]}]
    facts = xlsx_facts(sheets)
    assert "- National chains: 3 rows" in facts and "Country: UK 2, US 1" in facts
    assert "rows with no source or link: 1" in facts
    assert "Duplicate names: 1" in facts and "pizza express" in facts
    text = xlsx_text(xlsx_bytes(sheets))
    assert text.startswith("WORKBOOK FACTS") and "Olive Garden" in text
    assert xlsx_read(xlsx_bytes(sheets))[1]["name"] == "Regional chains"
