"""
The bench's scores (command/bench) are worked out in code from the files a job made, and a mission's own allowance
(mission_budget) is the lower of the setting and the one the bench gives it. No mission runs here.
"""
from __future__ import annotations

import asyncio
import time

from app.core.agents.workspace_ops import xlsx_bytes
from app.core.command import bench, mission_budget

HEADER = ["Company", "Website", "Published phone", "Published email", "Partnership page", "Source links"]


def _book(folder, rows, name="partners.xlsx"):
    (folder / name).write_bytes(xlsx_bytes([{"name": "Chains", "rows": [HEADER] + rows},
                                            {"name": "Read Me", "rows": [["Notes"], ["about this workbook"]]}]))


def _rows(n=50):
    return [[f"Chain {i}", f"https://chain{i}.co.uk", f"020 7{i:03d} 0000" if i < 5 else "Not recorded",
             f"hello@chain{i}.co.uk" if i < 40 or i >= 50 else "", f"https://chain{i}.co.uk/partners",
             f"https://chain{i}.co.uk/contact"] for i in range(n)]


def _scores(coro):
    return {c.what: c for c in asyncio.run(coro)}


def test_a_booking_workbook_is_scored_from_its_cells(tmp_path, monkeypatch):
    async def answers(urls):
        return {u: "madeup" not in u for u in urls}

    monkeypatch.setattr(bench, "reachable", answers)
    outcome = bench.Outcome(job="booking", folder=tmp_path, status="completed", verified=True, engine="claude",
                            cost_usd=0.6, minutes=12.0)
    # JAI carried on past the 10 businesses that publish neither: 60 listed, 50 can be contacted
    _book(tmp_path, _rows(60))
    good = _scores(bench.score_booking(outcome))
    assert all(c.passed for c in good.values()), {k: c.detail for k, c in good.items() if not c.passed}
    _book(tmp_path, _rows(50))                       # it stopped at 50 listed: only 40 can be contacted
    reached = _scores(bench.score_booking(outcome))[
        "partners.xlsx has at least 50 businesses to contact (a published email or phone)"]
    assert not reached.passed and reached.detail.startswith("40 of 50 listed")

    rows = _rows(60)
    rows[2][3] = "info@gmail.com"                    # an address from a data broker's page, not the business's
    rows[2][5] = "https://prospeo.io/c/chain2"
    rows[3][1] = "https://madeup-chain.co.uk"        # a site that does not exist
    rows[4][5] = ""                                  # no source
    _book(tmp_path, rows)
    failed = {k for k, c in _scores(bench.score_booking(outcome)).items() if not c.passed}
    assert failed == {"no email is guessed: each is published on the business's own site",
                      "every website is real (it answers on the web)", "every entry has its source page"}

    rows = _rows(60)
    rows[6][3], rows[7][3] = "guestexperience@trgplc.com", "pressemea@chain7.com"   # published by the business itself
    _book(tmp_path, rows)
    assert _scores(bench.score_booking(outcome))["no email is guessed: each is published on the business's own site"].passed
    rows[8][2] = ""                                  # an email and its source, no phone: still sourced
    _book(tmp_path, rows)
    assert _scores(bench.score_booking(outcome))["every entry has its source page"].passed

    _book(tmp_path, _rows(6))
    assert not _scores(bench.score_booking(outcome))["partners.xlsx has at least 50 businesses to contact (a published email or phone)"].passed
    outcome.minutes = 31.0
    assert not _scores(bench.score_booking(outcome))["done within 15 minutes (faster than a person searching by hand)"].passed
    outcome.engine, outcome.cost_usd = "", 3.0
    scored = _scores(bench.score_booking(outcome))
    assert not scored["ran on the Claude engine"].passed and not scored["stayed within its £1 allowance"].passed


def test_a_list_of_places_counts_a_site_twice_once(tmp_path, monkeypatch):
    async def answers(urls):
        return {u: True for u in urls}

    monkeypatch.setattr(bench, "reachable", answers)
    rows = [["Place", "URL", "What is allowed and how to post", "Checked on"]] + [
        [f"Place {i}", f"https://place{i}.com", "A weekly show-and-tell thread", f"https://place{i}.com/rules"]
        for i in range(8)]
    (tmp_path / "free-places.xlsx").write_bytes(xlsx_bytes([{"name": "Free places", "rows": rows}]))
    outcome = bench.Outcome(job="places", folder=tmp_path, status="completed", verified=True, engine="claude")
    assert all(c.passed for c in _scores(bench.score_places(outcome)).values())
    rows[3][1] = "https://place1.com/another-page"
    (tmp_path / "free-places.xlsx").write_bytes(xlsx_bytes([{"name": "Free places", "rows": rows}]))
    failed = [k for k, c in _scores(bench.score_places(outcome)).items() if not c.passed]
    assert failed == ["no entry is listed twice"]


def test_the_team_job_needs_a_second_specialist_and_the_cancel_job_nothing_written_after(tmp_path, monkeypatch):
    async def answers(urls):
        return {u: True for u in urls}

    monkeypatch.setattr(bench, "reachable", answers)
    (tmp_path / "partners.xlsx").write_bytes(xlsx_bytes([{"name": "Partners", "rows": [
        ["Company", "Website", "Partnership contact", "Source"]] + [
        [f"Hub{i} Spaces", f"https://hub{i}.co.uk", f"partners@hub{i}.co.uk", f"https://hub{i}.co.uk"]
        for i in range(5)]}]))
    (tmp_path / "outreach.md").write_text("\n".join(f"## Hub{i} Spaces\nHello" for i in range(5)))
    team = bench.Outcome(job="team", folder=tmp_path, status="completed", verified=True, engine="claude",
                         delegated=[{"to": "sales", "what": "the first emails"}])
    assert all(c.passed for c in _scores(bench.score_team(team)).values())
    team.delegated = []
    assert [k for k, c in _scores(bench.score_team(team)).items() if not c.passed] == [
        "a second specialist did part of the work"]
    team.child_tasks = 2                                  # split by the Orchestrator into two specialists' steps
    assert all(c.passed for c in _scores(bench.score_team(team)).values())

    cancelled = bench.Outcome(job="cancel", folder=tmp_path, status="cancelled", cancelled_at=time.time())
    assert all(c.passed for c in _scores(bench.score_cancel(cancelled)).values())
    cancelled.cancelled_at = time.time() - 100            # a file written well after the cancel
    assert [k for k, c in _scores(bench.score_cancel(cancelled)).items() if not c.passed] == [
        "nothing was written after the cancel"]
    assert bench.email_matches_site("partners@hub1.co.uk", "hub1.co.uk") is True
    assert bench.email_matches_site("", "hub1.co.uk") is None


def test_a_missions_own_allowance_is_never_more_than_the_setting(monkeypatch):
    from app.core.config import settings

    store = {}

    class Redis:
        async def get(self, key):
            return store.get(key)

        async def set(self, key, value, ex=None):
            store[key] = value

    async def redis():
        return Redis()

    monkeypatch.setattr(mission_budget, "_redis", redis)
    monkeypatch.setattr(settings, "ROLE_MISSION_MAX_COST_USD", 2.5)
    assert asyncio.run(mission_budget.role_cap("t1")) == 2.5          # none set: the setting
    asyncio.run(mission_budget.set_allowance("t1", 1.28))
    assert asyncio.run(mission_budget.role_cap("t1")) == 1.28         # the bench's £1
    asyncio.run(mission_budget.set_allowance("t2", 9.0))
    assert asyncio.run(mission_budget.role_cap("t2")) == 2.5          # never above the setting
    assert asyncio.run(mission_budget.role_cap(None)) == 2.5
    assert set(bench.JOBS) == {"booking", "places", "investors", "team", "cancel"}


def test_a_workbook_in_a_new_folder_keeps_its_backup_beside_it_never_above_the_workspaces(tmp_path, monkeypatch):
    from app.core.agents.workspace_ops import _backup_workbook
    from app.core.config import settings

    monkeypatch.setattr(settings, "WORKSPACE_CONTAINER_ROOT", str(tmp_path))
    fresh = tmp_path / "_jai_bench" / "investors"
    fresh.mkdir(parents=True)
    book = fresh / "investors.xlsx"
    book.write_bytes(b"new")
    _backup_workbook(book, b"old")                    # 15 November: "Permission denied: '/.jai'"
    assert [p.read_bytes() for p in (fresh / ".jai" / "backups").glob("investors-*.xlsx")] == [b"old"]
    workspace = tmp_path / "PLEXECUTE"
    (workspace / ".jai").mkdir(parents=True)
    (workspace / "plexecute").mkdir()
    (workspace / "plexecute" / "p.xlsx").write_bytes(b"new")
    _backup_workbook(workspace / "plexecute" / "p.xlsx", b"old")
    assert list((workspace / ".jai" / "backups").glob("p-*.xlsx"))      # a workspace keeps them at its root


def test_the_bench_folder_has_one_backslash_where_the_setting_escapes_them(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "WORKSPACE_HOST_ROOT", "C:\\\\Users\\\\lilri\\\\Projects")
    assert bench._host_folder("booking") == "C:\\Users\\lilri\\Projects\\_jai_bench\\booking"
    monkeypatch.setattr(settings, "WORKSPACE_HOST_ROOT", "C:\\Users\\lilri\\Projects\\")
    assert bench._host_folder() == "C:\\Users\\lilri\\Projects\\_jai_bench"


def test_a_list_kept_in_several_sheets_is_counted_whole(tmp_path, monkeypatch):
    async def answers(urls):
        return {u: True for u in urls}

    monkeypatch.setattr(bench, "reachable", answers)
    rows = _rows(60)
    (tmp_path / "partners.xlsx").write_bytes(xlsx_bytes([
        {"name": "Groups and chains", "rows": [HEADER] + rows[:20]},
        {"name": "Independents", "rows": [HEADER] + rows[20:35]},
        {"name": "Cafés", "rows": [HEADER[1:] + HEADER[:1]] + [r[1:] + r[:1] for r in rows[35:]]},   # other order
        {"name": "Notes", "rows": [["Notes"], ["how it was made"]]}]))
    outcome = bench.Outcome(job="booking", folder=tmp_path, status="completed", verified=True, engine="claude",
                            cost_usd=0.6, minutes=12.0)
    scored = _scores(bench.score_booking(outcome))
    whole = scored["partners.xlsx has at least 50 businesses to contact (a published email or phone)"]
    assert whole.passed and whole.detail.startswith("50 of 60 listed"), whole.detail
    assert all(c.passed for c in scored.values()), {k: c.detail for k, c in scored.items() if not c.passed}
