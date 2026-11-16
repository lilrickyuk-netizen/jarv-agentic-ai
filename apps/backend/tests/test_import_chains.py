"""
import_chains: UK and US chains from the Name Suggestion Index and Wikidata into a workbook, ready for
fill_contacts. Both sources are played by an httpx MockTransport, so nothing leaves the test and no credit is spent.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.business import chains, prospecting
from tests.conftest import AsyncTestingSessionLocal
from app.core.command.role_mission import RoleExecutor
from tests.test_repair12e3a_workspace_tools import project  # noqa: F401


def _site(url, country=None, rank="normal"):
    claim = {"mainsnak": {"datavalue": {"value": url}}, "rank": rank}
    if country:
        claim["qualifiers"] = {"P1001": [{"datavalue": {"value": {"id": country}}}]}
    return claim


def test_the_website_for_the_country_is_chosen_and_another_countrys_is_set_apart():
    assert chains.official_site({"P856": [_site("https://deltaco.com/")]}, "us") == ("https://deltaco.com/", "")
    # Wikidata says which site is for the UK
    both = {"P856": [_site("https://www.brand.com", "Q30"), _site("https://www.brand.co.uk", "Q145")]}
    assert chains.official_site(both, "gb") == ("https://www.brand.co.uk", "")
    assert chains.official_site(both, "us") == ("https://www.brand.com", "")
    # an address ending in the country's code wins over a general one
    ending = {"P856": [_site("https://brand.com"), _site("https://brand.co.uk")]}
    assert chains.official_site(ending, "gb")[0] == "https://brand.co.uk"
    # the only site is another country's: no website, that site set apart (Kura Sushi, Galito's)
    assert chains.official_site({"P856": [_site("https://www.kurasushi.co.jp/")]}, "us") == (
        "", "https://www.kurasushi.co.jp/")
    assert chains.official_site({"P856": [_site("https://www.galitos.co.za/")]}, "gb")[0] == ""
    assert chains.official_site({"P856": [_site("https://x.com", rank="deprecated")]}, "gb") == ("", "")
    assert chains.official_site({}, "gb") == ("", "")
    assert chains.official_site({"P856": [_site("https://brand.io")]}, "gb")[0] == "https://brand.io"


def test_only_brands_trading_in_the_countries_asked_for_with_a_wikidata_id_are_kept():
    items = [
        {"displayName": "UK Only", "locationSet": {"include": ["gb"]}, "tags": {"brand:wikidata": "Q1"}},
        {"displayName": "Scottish", "locationSet": {"include": ["gb-sct.geojson"]}, "tags": {"brand:wikidata": "Q2"}},
        {"displayName": "Everywhere", "locationSet": {"include": ["001"]}, "tags": {"brand:wikidata": "Q3"}},
        {"displayName": "French", "locationSet": {"include": ["fr"]}, "tags": {"brand:wikidata": "Q4"}},
        {"displayName": "No ID", "locationSet": {"include": ["us"]}, "tags": {}},
    ]
    kept = chains.brands(items, ["gb", "us"], "restaurant")
    assert [b["name"] for b in kept] == ["UK Only", "Scottish", "Everywhere"]
    assert kept[2]["countries"] == ["gb", "us"]
    assert [b["name"] for b in chains.brands(items, ["us"], "restaurant")] == ["Everywhere"]
    with pytest.raises(ValueError):
        chains.category_files(["spaceports"])
    with pytest.raises(ValueError):
        chains.country_codes(["France"])
    assert chains.category_files(["Hotels", "fast_food"]) == [("hotel", "tourism/hotel"),
                                                             ("fast food", "amenity/fast_food")]


INDEX = {
    "amenity/restaurant": {"items": [
        {"displayName": "Giraffe", "locationSet": {"include": ["gb"]}, "tags": {"brand:wikidata": "Q10"}},
        {"displayName": "Both Grill", "locationSet": {"include": ["gb", "us"]}, "tags": {"brand:wikidata": "Q11"}},
        {"displayName": "Kura Sushi", "locationSet": {"include": ["us"]}, "tags": {"brand:wikidata": "Q12"}},
        {"displayName": "Known Ltd", "locationSet": {"include": ["gb"]}, "tags": {"brand:wikidata": "Q13"}},
        {"displayName": "Paris Only", "locationSet": {"include": ["fr"]}, "tags": {"brand:wikidata": "Q14"}},
    ]},
    "tourism/hotel": {"items": [
        {"displayName": "Giraffe", "locationSet": {"include": ["gb"]}, "tags": {"brand:wikidata": "Q10"}},
        {"displayName": "Stay Inn", "locationSet": {"include": ["us"]}, "tags": {"brand:wikidata": "Q15"}},
    ]},
}
WIKIDATA = {
    "Q10": [_site("https://www.giraffe.net")],
    "Q11": [_site("https://bothgrill.com", "Q30"), _site("https://bothgrill.co.uk", "Q145")],
    "Q12": [_site("https://www.kurasushi.co.jp/")],
    "Q13": [_site("https://known.co.uk")],
    "Q15": [_site("https://stayinn.com")],
}


def open_data(seen):
    def answer(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if "raw.githubusercontent.com" in url:
            path = url.split("/data/brands/")[1].removesuffix(".json")
            return httpx.Response(200, json=INDEX[path]) if path in INDEX else httpx.Response(404)
        assert request.url.params["action"] == "wbgetentities" and len(request.url.params["ids"].split("|")) <= 50
        ids = request.url.params["ids"].split("|")
        return httpx.Response(200, json={"entities": {q: {"claims": {"P856": WIKIDATA.get(q, [])}} for q in ids}})
    return answer


@pytest.mark.integration
def test_chains_are_added_to_the_workbook_ready_for_fill_contacts(project, monkeypatch):  # noqa: F811
    from pathlib import Path

    from app.core.agents.workspace_ops import rows_wanting_contacts, xlsx_read
    from app.core.command.role_mission import role_tools
    from app.core.command.tool_runtime import ToolRuntime
    from tests.test_repair12e3a_workspace_tools import _seed as seed_workspace

    seen = []
    monkeypatch.setattr(prospecting, "http_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(open_data(seen))))
    monkeypatch.setattr(chains, "WIKIDATA_PAUSE", 0)
    host, root = project
    book = Path(root) / "plexecute" / "partners.xlsx"

    async def go():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await seed_workspace(db, host)
            runtime = ToolRuntime(db, ws_id, None, operator="agent:partnerships", authority_level=3,
                                  user_id=user_id)
            runner = RoleExecutor(runtime, "gpt-6-luna", host, role="partnerships")
            await runner._prepare_tools()
            call = runner.toolbox.call
            await call("write_spreadsheet", {"path": "plexecute/partners.xlsx", "sheets": [
                {"name": "Partners", "rows": [["Business", "Website", "Email"], ["Known", "https://www.known.co.uk", ""]]}]})
            first = await call("import_chains", {"path": "plexecute/partners.xlsx",
                                                 "categories": ["restaurant", "hotel"]})
            again = await call("import_chains", {"path": "plexecute/partners.xlsx",
                                                 "categories": ["restaurant", "hotel"]})
            wrong = await call("import_chains", {"path": "plexecute/partners.xlsx", "countries": ["France"]})
            return first, again, wrong, list(runtime.calls)

    first, again, wrong, calls = asyncio.run(go())
    sheets = {s["name"]: s["rows"] for s in xlsx_read(book.read_bytes())}
    assert sheets["Partners"][1][0] == "Known"                       # the earlier sheet is kept
    rows = sheets["Chains"]
    assert rows[0] == chains.HEADER
    listed = {(r[0], r[2], r[3]) for r in rows[1:]}
    assert listed == {("Giraffe", "UK", "https://www.giraffe.net"),
                      ("Both Grill", "UK", "https://bothgrill.co.uk"), ("Both Grill", "US", "https://bothgrill.com"),
                      ("Kura Sushi", "US", ""), ("Stay Inn", "US", "https://stayinn.com")}
    kura = next(r for r in rows if r[0] == "Kura Sushi")
    assert kura[10] == "https://www.kurasushi.co.jp/" and "another country" in kura[11]
    assert all(r[9].startswith("https://www.wikidata.org/wiki/Q") for r in rows[1:])
    assert all(len(r) == len(chains.HEADER) for r in rows)
    assert first["success"] and first["added"] == 5 and first["with_website"] == 4
    assert first["counts"]["already_listed"] == 1 and first["counts"]["other_country_only"] == 1
    assert "fill_contacts" in first["next"]
    # the second run adds nothing: every website, and every chain without one, is already in the workbook
    assert again["success"] and again["added"] == 0 and again["counts"]["already_listed"] == 6
    assert wrong["success"] is False and "UK or US" in wrong["error"]
    # fill_contacts sees the chains with a website as rows to fill
    wanting = rows_wanting_contacts(xlsx_read(book.read_bytes()), ["Chains"])
    assert {w["name"] for w in wanting} >= {"Giraffe", "Both Grill", "Stay Inn"}
    assert all("wikidata.org" in u or "githubusercontent.com" in u for u in seen)
    assert any(c.get("tool") == "write_file" for c in calls)
    assert "import_chains" in role_tools("partnerships")
