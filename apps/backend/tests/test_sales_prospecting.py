"""
Upgrade 6: the Sales agent's prospecting workflow, end to end on real rows. Played by recorders: OpenStreetMap's
Nominatim and Overpass (an httpx MockTransport), the companies' websites, the DNS mail lookup, the model and the
outgoing mailbox, so nothing leaves the test and no credit is spent.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.business import prospecting
from app.core.business.prospecting import prospecting_service
from app.core.config import settings
from app.models.company_crm import CRMDeal
from app.models.prospecting import OutreachMessage, OutreachSuppression, Prospect
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal

TUESDAY_10AM = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
SATURDAY = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)

SITES = {
    "https://harbordental.test/": ('<html><body><h1>Harbor Dental Studio</h1><p>Call us to make an appointment.</p>'
                                   '<a href="/about-us">About</a> <a href="mailto:elena.park@harbordental.test">Email</a>'
                                   '</body></html>'),
    "https://harbordental.test/about-us": ("<html><body><p>Elena Park, Practice Manager, has run the studio since "
                                           "2019.</p></body></html>"),
    "https://brightsmile.test/": ('<html><body><h1>Bright Smile</h1><a href="/book">Book online</a> in seconds. '
                                  '<p>Owner: Tom Reed</p> info@brightsmile.test</body></html>'),
}


def overpass_and_nominatim(request: httpx.Request) -> httpx.Response:
    if "nominatim" in str(request.url):
        assert request.url.params["q"] == "Leeds, UK"
        return httpx.Response(200, json=[{"boundingbox": ["53.7", "53.9", "-1.7", "-1.4"]}])
    query = request.content.decode()
    assert "amenity" in query and "dentist" in query and "website" in query and "53.7" in query
    return httpx.Response(200, json={"elements": [
        {"type": "node", "id": 1, "tags": {"name": "Harbor Dental Studio", "website": "https://harbordental.test/",
                                           "addr:city": "Leeds"}},
        {"type": "node", "id": 2, "tags": {"name": "Bright Smile", "website": "brightsmile.test"}},
        {"type": "node", "id": 3, "tags": {"name": "No Website Dental"}}]})


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(prospecting, "http_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(overpass_and_nominatim)))

    async def fetch(url):
        url = url if url.endswith("/") or "/about" in url or "/book" in url else url + "/"
        html = SITES.get(url)
        return {"ok": True, "url": url, "html": html} if html else {"ok": False, "url": url, "reason": "HTTP 404"}

    async def mx(domain):
        return [f"mx.{domain}"] if domain.endswith(".test") else []

    monkeypatch.setattr(prospecting, "fetch", fetch)
    monkeypatch.setattr(prospecting, "mx_hosts", mx)
    monkeypatch.setattr(prospecting, "page_text", lambda html: __import__("re").sub(r"<[^>]+>", " ", html))
    monkeypatch.setattr(settings, "SALES_SENDER_NAME", "Richard Curley")
    monkeypatch.setattr(settings, "SALES_SENDER_COMPANY", "Plexecute")
    monkeypatch.setattr(settings, "SALES_SENDER_ADDRESS", "1 Example Street, Leeds LS1 1AA, UK")
    monkeypatch.setattr(settings, "SALES_DAILY_SEND_LIMIT", 20)


async def _seed(db):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io", password_hash="x",
                is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="Plexecute", slug=f"px-{ws_id.hex[:8]}",
                     description="Booking reminders that cut no-shows", workspace_type="project", authority_level=5,
                     is_active=True, config={}))
    await db.commit()
    return user_id, ws_id


def fake_model(text):
    calls = []

    async def complete(model, prompt, **kwargs):
        calls.append((model, prompt))
        return {"text": text}

    complete.calls = calls
    return complete


SEQUENCE = ("SUBJECT: Online booking for Harbor Dental\nBODY:\nHi Elena, your site asks patients to call to book. "
            "Plexecute adds online booking with reminders.\nWorth a 15-minute call?\n===\nSUBJECT: Re: Online booking\n"
            "BODY:\nHi Elena, one more thought: reminders go out the day before.\nShall I send an overview?")


def test_the_whole_outreach_workflow_with_richards_gate(world):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws = await _seed(db)
            found = await prospecting_service.discover(db, ws, category="dentist", area="Leeds, UK")
            assert found["found"] == 2 and {c["domain"] for c in found["companies"]} == {"harbordental.test",
                                                                                         "brightsmile.test"}
            ids = [c["id"] for c in found["companies"]]
            scored = await prospecting_service.read_signals(db, ws, ids, [
                {"name": "no online booking", "look_for": ["book online", "online booking"], "want": "absent"}])
            by_name = {c["name"]: c for c in scored}
            assert by_name["Harbor Dental Studio"]["status"] == "qualified"
            assert by_name["Bright Smile"]["status"] == "not_a_fit"  # it already takes bookings online
            harbor = by_name["Harbor Dental Studio"]["id"]

            people = await prospecting_service.find_people(db, ws, harbor)
            assert [(p["name"], p["role"]) for p in people["people"]] == [("Elena Park", "Practice Manager")]
            elena = people["people"][0]["id"]
            checked = await prospecting_service.verify(db, ws, elena)
            assert checked["email"] == "elena.park@harbordental.test" and checked["email_status"] == "verified"

            model = fake_model(SEQUENCE)
            drafted = await prospecting_service.draft_sequence(db, ws, elena, steps=2, offer="a free month",
                                                               complete=model)
            assert drafted["sendable"] is True and len(drafted["messages"]) == 2
            first, second = drafted["messages"]
            assert "Hi Elena" in first["body"] and "1 Example Street" in first["body"]
            assert 'reply "unsubscribe"' in first["body"] and second["send_after_days"] == 3
            assert "no online booking" in model.calls[0][1]  # written from the evidence found

            with pytest.raises(PermissionError, match="hard boundary"):
                await prospecting_service.approve(db, ws, [first["id"], second["id"]], approved=False)
            sent = []

            async def mailbox(to, subject, body, reply_to=None):
                sent.append((to, subject, reply_to))
                return {"message_id": f"<m{len(sent)}@plexecute>"}

            approved = await prospecting_service.approve(db, ws, [first["id"], second["id"]], approved=True)
            assert approved["approved"] == 2
            weekend = await prospecting_service.send_due(db, ws, send=mailbox, moment=SATURDAY)
            assert weekend["sent"] == [] and "office hours" in weekend["reason"]
            now = await prospecting_service.send_due(db, ws, send=mailbox, moment=TUESDAY_10AM)
            assert now["sent"] == [first["id"]] and sent[0][0] == "elena.park@harbordental.test"
            assert now["waiting"] == 1  # the follow-up waits three days
            later = await prospecting_service.send_due(db, ws, send=mailbox,
                                                       moment=TUESDAY_10AM.replace(day=13))
            assert later["sent"] == [second["id"]] and sent[1][2] == "<m1@plexecute>"  # threaded on the first
            prospect = await db.get(Prospect, __import__("uuid").UUID(elena))
            assert prospect.stage == "contacted" and prospect.deal_id is not None

            replies = await prospecting_service.process_replies(db, ws, owner, complete=fake_model("interested"),
                                                                messages=[{"from_email": "Elena.Park@harbordental.test",
                                                                           "subject": "Re: Online booking",
                                                                           "body": "Yes, tell me more.",
                                                                           "message_id": "<r1>"}])
            assert replies["handled"] == [{"prospect": "Elena Park", "class": "interested"}]
            deal = await db.get(CRMDeal, prospect.deal_id)
            assert prospect.stage == "interested" and deal.stage == "qualified"
            answer = (await db.execute(select(OutreachMessage).where(OutreachMessage.step == 9))).scalar_one()
            assert answer.status == "draft"  # the answer waits for approval too
            report = await prospecting_service.report(db, ws)
            assert report["contacted"] == 1 and report["positive_rate"] == 1.0
            assert report["by_signal"]["no online booking"] == {"contacted": 1, "positive": 1}

    asyncio.run(run())


def test_opt_outs_are_honoured_at_once_and_never_emailed_again(world):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws = await _seed(db)
            found = await prospecting_service.discover(db, ws, category="amenity=dentist", area="Leeds, UK")
            harbor = next(c["id"] for c in found["companies"] if c["name"] == "Harbor Dental Studio")
            elena = (await prospecting_service.find_people(db, ws, harbor))["people"][0]["id"]
            await prospecting_service.verify(db, ws, elena)
            drafted = await prospecting_service.draft_sequence(db, ws, elena, complete=fake_model(SEQUENCE))
            ids = [m["id"] for m in drafted["messages"]]
            await prospecting_service.approve(db, ws, ids, approved=True)

            async def mailbox(to, subject, body, reply_to=None):
                return {"message_id": "<m1>"}

            await prospecting_service.send_due(db, ws, send=mailbox, moment=TUESDAY_10AM)
            out = await prospecting_service.process_replies(db, ws, owner, messages=[
                {"from_email": "elena.park@harbordental.test", "subject": "Re", "body": "Please remove me."}])
            assert out["handled"][0]["class"] == "opt_out"
            prospect = await db.get(Prospect, __import__("uuid").UUID(elena))
            assert prospect.stage == "opted_out"
            assert (await db.execute(select(OutreachSuppression.value))).scalars().all() == [
                "elena.park@harbordental.test"]
            follow_up = await db.get(OutreachMessage, __import__("uuid").UUID(ids[1]))
            assert follow_up.status == "cancelled"
            with pytest.raises(ValueError, match="opted out"):
                await prospecting_service.draft_sequence(db, ws, elena, complete=fake_model(SEQUENCE))
            again = await prospecting_service.verify(db, ws, elena)
            assert again["email_status"] == "invalid" and "opt-out" in again["email_evidence"]

    asyncio.run(run())


def test_nothing_is_sent_without_the_senders_identity_or_to_unverified_addresses(world, monkeypatch):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws = await _seed(db)
            found = await prospecting_service.discover(db, ws, category="dentist", area="Leeds, UK")
            bright = next(c["id"] for c in found["companies"] if c["name"] == "Bright Smile")
            tom = (await prospecting_service.find_people(db, ws, bright))["people"][0]
            assert tom["name"] == "Tom Reed" and tom["role"] == "Owner"
            checked = await prospecting_service.verify(db, ws, tom["id"])
            assert checked["email"] == "tom@brightsmile.test" and checked["email_status"] == "guess"
            drafted = await prospecting_service.draft_sequence(db, ws, tom["id"], steps=1, complete=fake_model(SEQUENCE))
            assert drafted["sendable"] is False
            result = await prospecting_service.approve(db, ws, [drafted["messages"][0]["id"]], approved=True)
            assert result["approved"] == 0 and "only verified" in result["refused"][0]["reason"]
            monkeypatch.setattr(settings, "SALES_SENDER_ADDRESS", "")
            footer, missing = prospecting.compliance_footer()
            assert missing == ["SALES_SENDER_ADDRESS"] and "[confirm: postal address]" in footer

    asyncio.run(run())


def test_addresses_are_judged_from_what_the_company_publishes():
    assert prospecting.suggested_address("Elena Park", "x.test", ["elena.park@x.test"])[1] == "verified"
    address, status, why = prospecting.suggested_address("Sam Lee", "x.test", ["info@x.test", "jo.bloggs@x.test"])
    assert (address, status) == ("sam.lee@x.test", "risky") and "jo.bloggs" in why
    assert prospecting.suggested_address("Sam Lee", "x.test", ["info@x.test"])[1] == "guess"
    assert prospecting.people_in("Meet the team. Dr Anna Shah - Principal. Contact us.")[0]["name"] == "Dr Anna Shah"
    assert prospecting.in_office_hours(TUESDAY_10AM) and not prospecting.in_office_hours(SATURDAY)


def test_the_sales_agent_has_the_prospecting_tools_registered_and_gated():
    from app.core.agents.specialists.business_mode import tools_for
    from app.core.agents.base import AuthorityLevel
    from app.core.tools.registry import create_tool, get_registry
    from app.tools.sales_prospecting import PROSPECTING_TOOLS

    registry = get_registry()
    sales = tools_for("sales")
    for tool in PROSPECTING_TOOLS:
        assert registry.is_implemented(tool._name) and tool._name in sales
    send = create_tool("approve_and_send_outreach", __import__("app.core.tools.base", fromlist=["ToolConfig"]).ToolConfig())
    assert send.required_authority_level == AuthorityLevel.LEVEL_5_NETWORK_ACCESS
    assert json.dumps(PROSPECTING_TOOLS[0]._input.model_json_schema())
