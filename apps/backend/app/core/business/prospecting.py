"""
JAI Backend - Outbound sales prospecting for the Sales agent (Upgrade 6)

The outreach workflow Sellbird (formerly Harvey; its MIT-licensed releases) made popular, written for JAI on JAI's
own records, mailer, approvals and models, so nothing replaces JAI's orchestrator or model routing:

1. discover   companies that match the customer, from OpenStreetMap (free, open data: Nominatim finds the area,
              Overpass the businesses with a website), never from a paid source without Richard's approval;
2. signals    reads each company's own website for the buying signals Richard confirmed (words present or
              absent); no model call;
3. people     finds the one or two people who decide, named on the company's own pages, never invented: a name is
              kept only if it appears on the page it came from;
4. verify     checks each address: published on the site (verified), built from a pattern the site's own
              addresses use (risky), a plain guess (guess), or undeliverable / a personal mailbox (invalid). Only
              verified addresses are ever sent to;
5. draft      writes a short sequence from what was found, with the sender's name, postal address and a one-line
              opt-out added by JAI (UK PECR and US CAN-SPAM), through the No AI Slop editorial pass;
6. approve    every batch waits for Richard: sending email from his accounts is a hard boundary;
7. send       approved messages go out inside the daily limit, on weekdays in office hours, one at a time, and
              never to an opted-out address or domain (the outbox task sends the rest later);
8. replies    reads the inbox, honours opt-outs at once, sets bounces and auto-replies aside, classifies the rest,
              stops the sequence, drafts an answer for approval, and moves the CRM deal;
9. report     the campaign's funnel, reply and positive rates by signal, and what to change.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.prospecting import OutreachMessage, OutreachSuppression, Prospect, ProspectCompany

logger = logging.getLogger(__name__)

USER_AGENT = "JAI-Prospecting/1.0 (business directory lookup; respects OSM usage policy)"
# Common customer types as OpenStreetMap tags; any other "key=value" tag can be given directly.
CATEGORY_TAGS: Dict[str, str] = {
    "dentist": "amenity=dentist", "dental practice": "amenity=dentist", "doctor": "amenity=doctors",
    "vet": "amenity=veterinary", "veterinary": "amenity=veterinary", "pharmacy": "amenity=pharmacy",
    "physiotherapist": "healthcare=physiotherapist", "optician": "shop=optician",
    "restaurant": "amenity=restaurant", "cafe": "amenity=cafe", "bar": "amenity=bar", "pub": "amenity=pub",
    "hotel": "tourism=hotel", "gym": "leisure=fitness_centre", "fitness": "leisure=fitness_centre",
    "hairdresser": "shop=hairdresser", "barber": "shop=hairdresser", "beauty salon": "shop=beauty",
    "roofer": "craft=roofer", "plumber": "craft=plumber", "electrician": "craft=electrician", "hvac": "craft=hvac",
    "builder": "craft=builder", "carpenter": "craft=carpenter", "painter": "craft=painter",
    "car repair": "shop=car_repair", "garage": "shop=car_repair", "estate agent": "office=estate_agent",
    "real estate": "office=estate_agent", "accountant": "office=accountant", "lawyer": "office=lawyer",
    "solicitor": "office=lawyer", "insurance": "office=insurance", "it company": "office=it",
    "software company": "office=it", "marketing agency": "office=advertising_agency",
    "architect": "office=architect", "school": "amenity=school", "nursery": "amenity=kindergarten",
    "florist": "shop=florist", "bakery": "shop=bakery", "clothes shop": "shop=clothes",
}
FREE_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "yahoo.com",
             "yahoo.co.uk", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com",
             "btinternet.com", "sky.com", "virginmedia.com", "talktalk.net"}
ROLE_ADDRESSES = {"info", "hello", "contact", "enquiries", "enquiry", "sales", "admin", "office", "mail", "team",
                  "support", "reception", "bookings", "accounts", "help", "noreply", "no-reply", "careers", "jobs"}
DECIDER_ROLES = ("owner", "co-owner", "founder", "co-founder", "managing director", "director", "ceo",
                 "chief executive", "principal", "partner", "practice manager", "general manager", "manager", "head")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_NAME = r"((?:Dr\.?\s)?[A-Z][a-z'’-]+(?:\s[A-Z][a-z'’-]+){1,2})"
# Names are capitalised words, matched exactly; only the role is matched in any case ("Owner", "owner").
_ROLE = r"((?i:" + "|".join(re.escape(r) for r in sorted(DECIDER_ROLES, key=len, reverse=True)) + r"))"
_PEOPLE = (re.compile(_NAME + r"\s*[,–—\-|:(]\s*(?:[Oo]ur\s|[Tt]he\s)?" + _ROLE),
           re.compile(_ROLE + r"\s*[,–—\-|:]\s*" + _NAME))
OPT_OUT = re.compile(r"\b(unsubscribe|remove me|take me off|stop emailing|stop contacting|do not (?:email|contact)|"
                     r"don't (?:email|contact)|opt(?:ed)? out)\b", re.I)
AUTO_REPLY = re.compile(r"\b(out of (?:the )?office|automatic reply|auto-?reply|on annual leave|away until)\b", re.I)
BOUNCE_SENDERS = re.compile(r"^(mailer-daemon|postmaster)@", re.I)
REPLY_CLASSES = ("interested", "question", "objection", "not_interested", "referral")
CLOSING_STAGES = ("opted_out", "bounced", "won", "lost", "not_interested")

Fetch = Callable[[str], Awaitable[Dict[str, Any]]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def http_client() -> httpx.AsyncClient:
    """The client for open-data lookups (replaced by a recorder in tests)."""
    return httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0), headers={"User-Agent": USER_AGENT})


async def fetch(url: str) -> Dict[str, Any]:
    """A public page, through JAI's SSRF guard (replaced by a recorder in tests)."""
    from app.core.knowledge.ingest import fetch_page

    return await fetch_page(url)


async def mx_hosts(domain: str) -> List[str]:
    """The domain's mail servers; empty when it has none (no mail can reach it)."""
    try:
        import dns.asyncresolver

        answer = await dns.asyncresolver.resolve(domain, "MX", lifetime=8)
        return sorted(str(r.exchange).rstrip(".") for r in answer)
    except Exception:  # noqa: BLE001 - NXDOMAIN, no answer, timeout: no mail server
        return []


def domain_of(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else (host or None)


def page_text(html: str) -> str:
    try:
        from app.core.knowledge.ingest import extract_markdown

        text = extract_markdown(html)
        if text:
            return text
    except Exception:  # noqa: BLE001 - fall back to the visible text
        pass
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html or "")
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()


def emails_on(html: str, domain: Optional[str]) -> List[str]:
    found = {m.lower().rstrip(".") for m in _EMAIL.findall(html or "")}
    found = {e for e in found if not e.endswith((".png", ".jpg", ".svg", ".webp", ".gif"))}
    if domain:
        found = {e for e in found if e.split("@", 1)[1] == domain or e.split("@", 1)[1].endswith("." + domain)}
    return sorted(found)


def people_in(text: str) -> List[Dict[str, str]]:
    """Names with a deciding role written next to them on the page, as the page says them."""
    out: List[Dict[str, str]] = []
    seen = set()
    for pattern in _PEOPLE:
        for match in pattern.finditer(text or ""):
            groups = match.groups()
            name, role = (groups[0], groups[1]) if pattern is _PEOPLE[0] else (groups[1], groups[0])
            name = " ".join(name.split())
            if name.lower() in seen or any(w.lower() in DECIDER_ROLES for w in name.split()):
                continue
            seen.add(name.lower())
            out.append({"name": name, "role": role.strip().title()})
    return out


def suggested_address(name: str, domain: str, published: Sequence[str]) -> Tuple[Optional[str], str, str]:
    """(address, status, evidence) for a person at a company, from what the company publishes."""
    parts = [p for p in re.sub(r"^(dr\.?\s)", "", name.lower()).replace("’", "'").split() if p.isalpha()]
    if not parts or not domain:
        return None, "invalid", "no usable name or domain"
    first, last = parts[0], parts[-1]
    for address in published:
        local = address.split("@", 1)[0]
        if (first in local and (last in local or len(parts) == 1)) or local in (first, f"{first[0]}{last}"):
            return address, "verified", f"published on the company's site: {address}"
    personal = [a for a in published if a.split("@", 1)[0] not in ROLE_ADDRESSES]
    patterns = {"first.last": f"{first}.{last}", "first": first, "flast": f"{first[0]}{last}",
                "firstlast": f"{first}{last}", "first_last": f"{first}_{last}", "firstl": f"{first}{last[0]}"}
    for address in personal:
        shape = _shape(address.split("@", 1)[0])
        if shape in patterns:
            return (f"{patterns[shape]}@{domain}", "risky",
                    f"the site's own address {address} uses the {shape} pattern")
    return f"{first}@{domain}", "guess", "no address on the site shows the company's pattern"


def _shape(local: str) -> Optional[str]:
    if re.fullmatch(r"[a-z]+\.[a-z]+", local):
        return "first.last"
    if re.fullmatch(r"[a-z]+_[a-z]+", local):
        return "first_last"
    return None


def in_office_hours(moment: Optional[datetime] = None) -> bool:
    zone = ZoneInfo(str(getattr(settings, "SALES_SEND_TIMEZONE", "Europe/London") or "Europe/London"))
    local = (moment or _now()).astimezone(zone)
    return local.weekday() < 5 and 8 <= local.hour < 17


# UK PECR: a limited company or LLP (a corporate subscriber) may be emailed without prior consent, with the sender's
# identity and an opt-out; a sole trader or a partnership is an individual subscriber and needs consent (or the soft
# opt-in). Fines since February 2026 reach £17.5m or 4% of turnover, so a business is treated as corporate only when
# its own site says so.
CORPORATE = re.compile(r"\b(ltd|limited|plc|llp|limited liability partnership|company (no|number|reg(istration)?)|"
                       r"registered in (england|scotland|wales|northern ireland)|companies house)\b", re.I)


def pecr_status(text: str, url: str) -> Dict[str, Any]:
    """Whether a business's own site shows it is a corporate subscriber (it is never a buying signal)."""
    match = CORPORATE.search(text or "")
    if match:
        return {"matched": False, "subscriber": "corporate", "evidence": f'"{match.group(0)}" on {url}'}
    return {"matched": False, "subscriber": "individual or unknown",
            "evidence": f"no company registration (Ltd, LLP, company number) on {url}"}


def compliance_footer() -> Tuple[str, List[str]]:
    """The sender's identity, postal address and opt-out line JAI adds to every message, and what is missing."""
    name = (getattr(settings, "SALES_SENDER_NAME", "") or "").strip()
    company = (getattr(settings, "SALES_SENDER_COMPANY", "") or "").strip()
    address = (getattr(settings, "SALES_SENDER_ADDRESS", "") or "").strip()
    missing = [key for key, value in (("SALES_SENDER_NAME", name), ("SALES_SENDER_ADDRESS", address)) if not value]
    who = ", ".join(p for p in (name or "[confirm: sender name]", company) if p)
    return (f"\n\n--\n{who}\n{address or '[confirm: postal address]'}\n"
            "If you'd rather not hear from me again, reply \"unsubscribe\" and I won't email you again."), missing


class ProspectingService:
    # ----- 1. discover --------------------------------------------------------------------------------
    async def discover(self, db: AsyncSession, workspace_id: UUID, *, category: str, area: str,
                       limit: int = 25) -> Dict[str, Any]:
        tag = category.strip() if "=" in category else CATEGORY_TAGS.get(category.strip().lower())
        if not tag or not re.fullmatch(r"[a-z_:]+=[A-Za-z0-9_ :-]+", tag):
            raise ValueError(f"'{category}' is not a known customer type; give an OpenStreetMap tag such as "
                             f"craft=roofer or one of: {', '.join(sorted(CATEGORY_TAGS)[:12])}, ...")
        key, value = tag.split("=", 1)
        async with http_client() as client:
            place = await client.get(str(settings.SALES_NOMINATIM_URL), params={
                "q": area, "format": "jsonv2", "limit": 1})
            if place.status_code >= 400 or not place.json():
                raise LookupError(f"OpenStreetMap could not find the area '{area}'")
            south, north, west, east = (float(x) for x in place.json()[0]["boundingbox"])
            query = (f'[out:json][timeout:40];nwr["{key}"="{value}"]["website"]({south},{west},{north},{east});'
                     f'out center tags {max(1, min(int(limit), 100))};')
            found = await client.post(str(settings.SALES_OVERPASS_URL), data={"data": query})
            if found.status_code >= 400:
                raise RuntimeError(f"OpenStreetMap's business search answered {found.status_code}")
            elements = found.json().get("elements") or []
        companies = []
        for element in elements[:limit]:
            tags = element.get("tags") or {}
            website = tags.get("website") or tags.get("contact:website")
            name = (tags.get("name") or "").strip()
            if not name or not website:
                continue
            ref = f"osm:{element.get('type')}/{element.get('id')}"
            row = (await db.execute(select(ProspectCompany).where(
                ProspectCompany.workspace_id == workspace_id, ProspectCompany.source_ref == ref))).scalar_one_or_none()
            if row is None:
                row = ProspectCompany(id=uuid4(), workspace_id=workspace_id, source="openstreetmap", source_ref=ref,
                                      name=name[:300], signals={}, published_emails=[], status="found")
                db.add(row)
            row.website = website[:500] if "://" in website else f"https://{website}"[:500]
            row.domain = domain_of(row.website)
            row.category, row.area = category[:120], area[:200]
            row.address = ", ".join(tags[k] for k in ("addr:housenumber", "addr:street", "addr:city", "addr:postcode")
                                    if tags.get(k)) or None
            published = tags.get("email") or tags.get("contact:email")
            if published:
                row.published_emails = sorted(set(row.published_emails or []) | set(emails_on(published, row.domain)))
            companies.append(row)
        await db.flush()
        return {"area": area, "tag": tag, "found": len(companies), "companies": [company_view(c) for c in companies],
                "source": "OpenStreetMap (ODbL): Nominatim and Overpass, free"}

    # ----- 2. signals ---------------------------------------------------------------------------------
    async def read_signals(self, db: AsyncSession, workspace_id: UUID, company_ids: Sequence[str],
                           signals: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not signals:
            raise ValueError("Give the buying signals to look for, e.g. {\"name\": \"no online booking\", "
                             "\"look_for\": [\"book online\", \"booking\"], \"want\": \"absent\"}")
        out = []
        for company in await self._companies(db, workspace_id, company_ids):
            page = await fetch(company.website or "")
            if not page.get("ok"):
                company.status, company.signals = "unreachable", {"error": page.get("reason")}
                out.append(company_view(company))
                continue
            text = page_text(page["html"]).lower()
            results, matched = {}, 0
            for signal in signals:
                words = [str(w).lower() for w in (signal.get("look_for") or []) if str(w).strip()]
                present = [w for w in words if w in text]
                want_absent = str(signal.get("want") or "present").lower() == "absent"
                hit = (not present) if want_absent else bool(present)
                matched += hit
                results[str(signal.get("name") or ", ".join(words))] = {
                    "matched": hit, "evidence": (f"none of {words} on {page['url']}" if want_absent and hit
                                                 else f"found {present} on {page['url']}" if present
                                                 else f"none of {words} on {page['url']}")}
            company.fit_score = round(matched / len(signals), 3)
            results["_pecr"] = {**pecr_status(text, page["url"]),
                                **({"consent": (company.signals or {}).get("_pecr", {}).get("consent")}
                                   if (company.signals or {}).get("_pecr", {}).get("consent") else {})}
            company.signals = results
            company.published_emails = sorted(set(company.published_emails or []) | set(
                emails_on(page["html"], company.domain)))
            company.status = "qualified" if company.fit_score >= 0.5 else "not_a_fit"
            out.append(company_view(company))
        await db.flush()
        return out

    # ----- 3. people ----------------------------------------------------------------------------------
    async def find_people(self, db: AsyncSession, workspace_id: UUID, company_id: str,
                          *, complete: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None) -> Dict[str, Any]:
        company = (await self._companies(db, workspace_id, [company_id]))[0]
        pages = await self._pages(company)
        people: List[Dict[str, str]] = []
        for url, text, html in pages:
            company.published_emails = sorted(set(company.published_emails or []) | set(emails_on(html, company.domain)))
            for person in people_in(text):
                person["found_on"] = url
                people.append(person)
        if not people and pages:
            people = await self._people_by_model(pages, complete)
        existing = {p.name.lower(): p for p in (await db.execute(select(Prospect).where(
            Prospect.company_id == company.id))).scalars().all()}
        kept = []
        for person in people[:2]:  # two people per company at most
            row = existing.get(person["name"].lower())
            if row is None:
                row = Prospect(id=uuid4(), workspace_id=workspace_id, company_id=company.id, name=person["name"][:200],
                               stage="new", email_status="unchecked")
                db.add(row)
            row.role, row.found_on = person.get("role"), person.get("found_on")
            kept.append(row)
        await db.flush()
        return {"company": company_view(company), "people": [prospect_view(p) for p in kept],
                "pages_read": [u for u, _, _ in pages],
                "note": None if kept else "No deciding person is named on the company's own pages."}

    async def _pages(self, company: ProspectCompany) -> List[Tuple[str, str, str]]:
        home = await fetch(company.website or "")
        if not home.get("ok"):
            return []
        pages = [(home["url"], page_text(home["html"]), home["html"])]
        links = re.findall(r'href=["\']([^"\'#]+)["\']', home["html"])
        wanted = []
        for link in links:
            absolute = urljoin(home["url"], link)
            if domain_of(absolute) == company.domain and re.search(r"(about|team|people|staff|contact|meet|who)",
                                                                   urlparse(absolute).path, re.I):
                if absolute not in wanted:
                    wanted.append(absolute)
        for url in wanted[:3]:
            page = await fetch(url)
            if page.get("ok"):
                pages.append((page["url"], page_text(page["html"]), page["html"]))
        return pages

    async def _people_by_model(self, pages, complete) -> List[Dict[str, str]]:
        from app.core.agents.specialists import _helpers as helpers

        if complete is None:
            if not helpers.provider_configured():
                return []
            complete = helpers.llm_complete
        joined = "\n\n".join(f"PAGE {url}\n{text[:6000]}" for url, text, _ in pages)
        reply = await complete(str(settings.LIGHT_MODEL or "gpt-6-luna"),
                               "List the people these pages name as the owner, founder, director, partner or "
                               "manager of this business, one per line as `Name | Role | page URL`. Only people the "
                               "pages name; write NONE if there are none.\n\n" + joined,
                               system="You extract facts from web pages. Never invent a person.",
                               temperature=0.0, max_tokens=300)
        out = []
        for line in str((reply or {}).get("text") or "").splitlines():
            parts = [p.strip(" `-*") for p in line.split("|")]
            if len(parts) < 2 or not parts[0] or parts[0].upper() == "NONE":
                continue
            source = next(((url, text) for url, text, _ in pages if parts[0] in text), None)
            if source is None:  # a name that is not on the pages is never kept
                continue
            out.append({"name": parts[0], "role": parts[1], "found_on": source[0]})
        return out

    # ----- 4. verify ----------------------------------------------------------------------------------
    async def verify(self, db: AsyncSession, workspace_id: UUID, prospect_id: str) -> Dict[str, Any]:
        prospect = await self._prospect(db, workspace_id, prospect_id)
        company = await db.get(ProspectCompany, prospect.company_id)
        domain = company.domain or ""
        address, status, evidence = suggested_address(prospect.name, domain, company.published_emails or [])
        if address and address.split("@", 1)[1] in FREE_MAIL:
            status, evidence = "invalid", "a personal mailbox: marketing to it needs the person's consent"
        elif address and not await mx_hosts(address.split("@", 1)[1]):
            status, evidence = "invalid", f"{address.split('@', 1)[1]} has no mail server"
        if address and await self.suppressed(db, workspace_id, address):
            status, evidence = "invalid", "on the opt-out list"
        prospect.email, prospect.email_status, prospect.email_evidence = address, status, evidence
        await db.flush()
        return prospect_view(prospect)

    # ----- 5. draft -----------------------------------------------------------------------------------
    async def draft_sequence(self, db: AsyncSession, workspace_id: UUID, prospect_id: str, *, steps: int = 2,
                             offer: str = "", complete: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None
                             ) -> Dict[str, Any]:
        from app.core.agents.specialists import _helpers as helpers
        from app.core.business import editorial
        from app.core.business.facts import gather

        prospect = await self._prospect(db, workspace_id, prospect_id)
        if prospect.stage in CLOSING_STAGES:
            raise ValueError(f"{prospect.name} is {prospect.stage.replace('_', ' ')}; no outreach is drafted")
        company = await db.get(ProspectCompany, prospect.company_id)
        facts = await gather(db, workspace_id)
        steps = max(1, min(int(steps), 3))
        matched = {k: v["evidence"] for k, v in (company.signals or {}).items() if isinstance(v, dict) and v.get("matched")}
        footer, missing = compliance_footer()
        complete = complete or (helpers.llm_complete if helpers.provider_configured() else None)
        emails: List[Tuple[str, str]] = []
        if complete is not None:
            prompt = (f"Write a {steps}-email cold outreach sequence from {facts.product} to {prospect.name}"
                      f"{', ' + prospect.role if prospect.role else ''} at {company.name}. Each email under 110 words, "
                      f"plain text, one clear ask (a short call or a reply). Email 1 names the specific reason "
                      f"for writing from the evidence; later emails add one new point each and never guilt-trip.\n"
                      f"Offer: {offer or '[confirm: the offer]'}\nEvidence about them (use only this): {matched}\n"
                      f"FACTS about the product (use only these, never invent numbers or customers):\n"
                      f"{facts.summary()}\nFormat exactly:\nSUBJECT: ...\nBODY:\n...\n=== between emails. No "
                      f"signature, no unsubscribe line (JAI adds both).")
            reply = await complete(str(settings.LIGHT_MODEL or "gpt-6-luna"), prompt,
                                   system="You write short, specific B2B emails. " + editorial.rules(3000),
                                   temperature=0.4, max_tokens=1400)
            emails = _parse_sequence(str((reply or {}).get("text") or ""))[:steps]
        if not emails:
            reason = next(iter(matched), "your business")
            emails = [(f"{facts.product} for {company.name}",
                       f"Hi {prospect.name.split()[0]},\n\nI noticed {reason} at {company.name}. {facts.product} "
                       f"{facts.description or '[confirm: what it does in one line]'}.\n\nWorth a 15-minute call "
                       f"next week?")][:1]
            emails += [(f"Re: {facts.product} for {company.name}",
                        f"Hi {prospect.name.split()[0]},\n\nA quick follow-up in case my last note got buried. "
                        f"{offer or '[confirm: the offer]'}\n\nShall I send a short overview?")
                       for _ in range(steps - 1)][:max(0, steps - 1)]
        await self._cancel_pending(db, prospect.id)
        rows = []
        for step, (subject, body) in enumerate(emails, start=1):
            edit = await editorial.revise(body)
            text = (edit["text"] if edit["revised"] else body).strip() + footer
            row = OutreachMessage(id=uuid4(), workspace_id=workspace_id, prospect_id=prospect.id, direction="out",
                                  step=step, send_after_days=(0, 3, 7)[step - 1], subject=subject[:300], body=text,
                                  status="draft", meta={"editorial": {k: edit[k] for k in ("revised", "patterns")},
                                                        "evidence": matched, "missing": missing})
            db.add(row)
            rows.append(row)
        prospect.stage = "drafted"
        await db.flush()
        return {"prospect": prospect_view(prospect), "messages": [message_view(m) for m in rows],
                "needs_before_sending": missing,
                "sendable": prospect.email_status == "verified" and not missing}

    # ----- 6/7. approve and send ------------------------------------------------------------------------
    async def approve(self, db: AsyncSession, workspace_id: UUID, message_ids: Sequence[str], *,
                      approved: bool, by: str = "Richard") -> Dict[str, Any]:
        if not approved:
            raise PermissionError(f"Sending {len(message_ids)} sales email(s) from Richard's mailbox is a hard "
                                  f"boundary: it waits for his approval of this batch.")
        rows = await self._messages(db, workspace_id, message_ids)
        problems = []
        for row in rows:
            prospect = await db.get(Prospect, row.prospect_id)
            reason = await self._unsendable(db, workspace_id, prospect, row)
            if reason and reason != "not due yet":  # a follow-up is approved now and sent when it is due
                problems.append({"message_id": str(row.id), "reason": reason})
                continue
            row.status, row.approved_by, row.approved_at = "approved", by[:100], _now()
            prospect.stage = "approved" if prospect.stage in ("new", "drafted") else prospect.stage
        await db.flush()
        sent = await self.send_due(db, workspace_id)
        return {"approved": len(rows) - len(problems), "refused": problems, "sent_now": sent["sent"],
                "waiting": sent["waiting"], "reason_waiting": sent["reason"]}

    async def send_due(self, db: AsyncSession, workspace_id: UUID, *,
                       send: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
                       moment: Optional[datetime] = None) -> Dict[str, Any]:
        """Send approved messages that are due, inside the daily limit and office hours (the outbox task)."""
        from app.core.business import mailer

        moment = moment or _now()
        approved = (await db.execute(select(OutreachMessage).where(
            OutreachMessage.workspace_id == workspace_id, OutreachMessage.status == "approved",
            OutreachMessage.direction == "out").order_by(OutreachMessage.step, OutreachMessage.approved_at))
        ).scalars().all()
        if not approved:
            return {"sent": [], "waiting": 0, "reason": None}
        if not in_office_hours(moment):
            return {"sent": [], "waiting": len(approved), "reason": "outside weekday office hours (sent from 8am)"}
        if send is None and not mailer.smtp_configured():
            return {"sent": [], "waiting": len(approved), "reason": "email sending is not set up (SMTP settings)"}
        send = send or mailer.send_email
        limit = int(getattr(settings, "SALES_DAILY_SEND_LIMIT", 20) or 0)
        start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        today = (await db.execute(select(func.count()).select_from(OutreachMessage).where(
            OutreachMessage.workspace_id == workspace_id, OutreachMessage.status == "sent",
            OutreachMessage.sent_at >= start))).scalar_one()
        sent = []
        for row in approved:
            if today >= limit:
                break
            prospect = await db.get(Prospect, row.prospect_id)
            reason = await self._unsendable(db, workspace_id, prospect, row, moment=moment)
            if reason == "not due yet":
                continue
            if reason:
                row.status, row.error = "cancelled", reason
                continue
            previous = await self._previous_sent(db, row)
            try:
                result = await send(prospect.email, row.subject, row.body,
                                    previous.message_id if previous is not None else None)
            except Exception as exc:  # noqa: BLE001 - recorded on the message; the rest still go
                row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:1000]
                continue
            row.status, row.sent_at, row.message_id = "sent", moment, str(result.get("message_id") or "")[:500]
            prospect.stage = "contacted" if prospect.stage in ("new", "drafted", "approved") else prospect.stage
            prospect.last_contacted_at = moment
            if prospect.deal_id is None:  # the first email opens the deal in the CRM
                await self._deal(db, workspace_id, prospect, "prospecting")
            sent.append(str(row.id))
            today += 1
        await db.flush()
        waiting = sum(1 for r in approved if r.status == "approved")
        return {"sent": sent, "waiting": waiting,
                "reason": f"today's limit of {limit} sales emails is reached" if waiting and today >= limit else None}

    async def _unsendable(self, db, workspace_id, prospect: Prospect, row: OutreachMessage,
                          moment: Optional[datetime] = None) -> Optional[str]:
        _footer, missing = compliance_footer()
        if missing:
            return f"set {' and '.join(missing)} first (every message must say who sends it and from where)"
        if "[confirm:" in row.body or "[confirm:" in row.subject:
            return "the message still has [confirm: ...] gaps"
        if prospect.email_status != "verified" or not prospect.email:
            return f"{prospect.name}'s address is {prospect.email_status}; only verified addresses are emailed"
        if await self.suppressed(db, workspace_id, prospect.email):
            return "the address or its domain opted out"
        company = await db.get(ProspectCompany, prospect.company_id)
        pecr = ((company.signals or {}).get("_pecr") or {}) if company is not None else {}
        if pecr.get("subscriber") != "corporate" and not pecr.get("consent"):
            return ("UK PECR: its site does not show it is a limited company or LLP, so it may be a sole trader or "
                    "partnership (an individual subscriber) and needs their consent before marketing email; record "
                    "the consent first")
        if prospect.stage in CLOSING_STAGES or prospect.stage in ("replied", "interested", "objection"):
            return f"{prospect.name} has {prospect.stage.replace('_', ' ')}; the sequence stopped"
        if row.step > 1:
            previous = await self._previous_sent(db, row)
            if previous is None or previous.sent_at is None:
                return "not due yet"
            sent_at = previous.sent_at if previous.sent_at.tzinfo else previous.sent_at.replace(tzinfo=timezone.utc)
            if (moment or _now()) < sent_at + timedelta(days=row.send_after_days - (previous.send_after_days or 0)):
                return "not due yet"
        return None

    async def _previous_sent(self, db, row: OutreachMessage) -> Optional[OutreachMessage]:
        if row.step <= 1:
            return None
        return (await db.execute(select(OutreachMessage).where(
            OutreachMessage.prospect_id == row.prospect_id, OutreachMessage.direction == "out",
            OutreachMessage.step == row.step - 1, OutreachMessage.status == "sent"))).scalars().first()

    # ----- 8. replies ---------------------------------------------------------------------------------
    async def process_replies(self, db: AsyncSession, workspace_id: UUID, owner: UUID, *,
                              messages: Optional[List[Dict[str, Any]]] = None,
                              complete: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None) -> Dict[str, Any]:
        from app.core.business import mailer

        if messages is None:
            if not mailer.imap_configured():
                raise RuntimeError("Reading replies needs the inbox set up (IMAP settings)")
            messages = await mailer.read_unseen(100)
        prospects = {p.email.lower(): p for p in (await db.execute(select(Prospect).where(
            Prospect.workspace_id == workspace_id, Prospect.email.is_not(None)))).scalars().all()}
        handled = []
        for message in messages:
            sender = str(message.get("from_email") or "").lower()
            body = str(message.get("body") or "")
            prospect = prospects.get(sender)
            if prospect is None and BOUNCE_SENDERS.match(sender):
                prospect = next((p for e, p in prospects.items() if e in body.lower()), None)
                if prospect is not None:
                    await self._close(db, workspace_id, prospect, "bounced", reason="the address bounced")
                    handled.append({"prospect": prospect.name, "class": "bounce"})
                continue
            if prospect is None:
                continue
            kind = await self._classify(message, complete)
            db.add(OutreachMessage(id=uuid4(), workspace_id=workspace_id, prospect_id=prospect.id, direction="in",
                                   step=0, subject=str(message.get("subject") or "")[:300], body=body[:20000],
                                   status="received", classification=kind,
                                   message_id=str(message.get("message_id") or "")[:500], meta={}))
            if kind == "opt_out":
                await self._close(db, workspace_id, prospect, "opted_out", reason="asked not to be emailed")
            elif kind == "auto_reply":
                pass  # an out-of-office: the sequence carries on as planned
            else:
                await self._cancel_pending(db, prospect.id)
                prospect.stage = {"interested": "interested", "question": "replied", "objection": "objection",
                                  "not_interested": "not_interested", "referral": "replied"}.get(kind, "replied")
                if kind == "interested":
                    await self._deal(db, workspace_id, prospect, "qualified", owner=owner)
                if kind in ("interested", "question", "objection", "referral"):
                    db.add(OutreachMessage(
                        id=uuid4(), workspace_id=workspace_id, prospect_id=prospect.id, direction="out", step=9,
                        subject=f"Re: {str(message.get('subject') or '')}"[:300],
                        body=await self._answer(prospect, body, kind, complete), status="draft",
                        meta={"reply_to": message.get("message_id"), "class": kind}))
            handled.append({"prospect": prospect.name, "class": kind})
        await db.flush()
        return {"read": len(messages), "handled": handled,
                "answers_drafted": sum(1 for h in handled if h["class"] in ("interested", "question", "objection",
                                                                          "referral"))}

    async def _classify(self, message: Dict[str, Any], complete) -> str:
        text = f"{message.get('subject') or ''}\n{message.get('body') or ''}"
        if OPT_OUT.search(text):
            return "opt_out"
        if AUTO_REPLY.search(text):
            return "auto_reply"
        from app.core.agents.specialists import _helpers as helpers

        if complete is None:
            if not helpers.provider_configured():
                return "question"
            complete = helpers.llm_complete
        reply = await complete(str(settings.LIGHT_MODEL or "gpt-6-luna"),
                               "Classify this reply to a sales email as exactly one word from: "
                               + ", ".join(REPLY_CLASSES) + f".\n\n{text[:4000]}",
                               system="You classify email replies. Answer with one word.", temperature=0.0,
                               max_tokens=5)
        word = str((reply or {}).get("text") or "").strip().lower().strip(".")
        return word if word in REPLY_CLASSES else "question"

    async def _answer(self, prospect: Prospect, body: str, kind: str, complete) -> str:
        from app.core.agents.specialists import _helpers as helpers

        footer, _missing = compliance_footer()
        complete = complete or (helpers.llm_complete if helpers.provider_configured() else None)
        if complete is not None:
            reply = await complete(str(settings.LIGHT_MODEL or "gpt-6-luna"),
                                   f"Draft a short, helpful answer to this {kind} reply from {prospect.name}. Answer "
                                   f"what they asked; where a fact is needed write [confirm: ...]; propose one next "
                                   f"step. No signature.\n\n{body[:4000]}",
                                   system="You write short, warm, specific business replies.", temperature=0.3,
                                   max_tokens=500)
            text = str((reply or {}).get("text") or "").strip()
            if text:
                return text + footer
        return f"Hi {prospect.name.split()[0]},\n\nThanks for coming back to me. [confirm: the answer]" + footer

    # ----- 9. report ----------------------------------------------------------------------------------
    async def report(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, Any]:
        prospects = (await db.execute(select(Prospect).where(Prospect.workspace_id == workspace_id))).scalars().all()
        stages: Dict[str, int] = {}
        for p in prospects:
            stages[p.stage] = stages.get(p.stage, 0) + 1
        contacted = [p for p in prospects if p.last_contacted_at is not None]
        replied = [p for p in contacted if p.stage in ("replied", "interested", "objection", "not_interested", "won",
                                                        "lost", "opted_out")]
        positive = [p for p in contacted if p.stage in ("interested", "won")]
        by_signal: Dict[str, Dict[str, int]] = {}
        companies = {c.id: c for c in (await db.execute(select(ProspectCompany).where(
            ProspectCompany.workspace_id == workspace_id))).scalars().all()}
        for p in contacted:
            for name, result in ((companies.get(p.company_id).signals or {}) if companies.get(p.company_id) else {}).items():
                if isinstance(result, dict) and result.get("matched"):
                    entry = by_signal.setdefault(name, {"contacted": 0, "positive": 0})
                    entry["contacted"] += 1
                    entry["positive"] += p in positive
        reply_rate = len(replied) / len(contacted) if contacted else 0.0
        positive_rate = len(positive) / len(contacted) if contacted else 0.0
        advice = []
        if contacted and reply_rate < 0.05:
            advice.append("Under 5% reply: sharpen the first line around the strongest signal and shorten email 1.")
        if stages.get("bounced", 0) > max(1, len(contacted) // 20):
            advice.append("Over 5% bounced: verify addresses again before sending; keep to verified ones.")
        best = max(by_signal.items(), key=lambda kv: kv[1]["positive"] / kv[1]["contacted"], default=None)
        if best and best[1]["positive"]:
            advice.append(f"'{best[0]}' brings the most interest: find more companies with that signal.")
        if not contacted:
            advice.append("Nothing sent yet: approve the drafted outbox to start.")
        return {"prospects": len(prospects), "by_stage": stages, "contacted": len(contacted),
                "reply_rate": round(reply_rate, 3), "positive_rate": round(positive_rate, 3),
                "by_signal": by_signal, "opted_out": stages.get("opted_out", 0), "advice": advice}

    # ----- suppressions and helpers ------------------------------------------------------------------
    async def suppress(self, db: AsyncSession, workspace_id: UUID, value: str, reason: str = "opted out") -> Dict:
        value = value.strip().lower()
        if not value or (" " in value):
            raise ValueError("Give one email address or a domain")
        kind = "email" if "@" in value else "domain"
        row = (await db.execute(select(OutreachSuppression).where(
            OutreachSuppression.workspace_id == workspace_id, OutreachSuppression.value == value))).scalar_one_or_none()
        if row is None:
            row = OutreachSuppression(id=uuid4(), workspace_id=workspace_id, value=value, kind=kind, reason=reason[:200])
            db.add(row)
        for prospect in (await db.execute(select(Prospect).where(Prospect.workspace_id == workspace_id))).scalars().all():
            email = (prospect.email or "").lower()
            if email and (email == value or email.endswith("@" + value)):
                await self._cancel_pending(db, prospect.id)
                if prospect.stage not in ("won", "lost"):
                    prospect.stage = "opted_out"
        await db.flush()
        return {"value": value, "kind": kind, "reason": row.reason}

    async def record_consent(self, db: AsyncSession, workspace_id: UUID, company_id: str, evidence: str) -> Dict:
        """Record that a business (an individual subscriber under PECR) consented to marketing email, with where
        and when; without it JAI never emails a business that is not shown to be a company or LLP."""
        if not str(evidence or "").strip():
            raise ValueError("Say where the consent came from (a form, an email, a call) and when.")
        company = (await self._companies(db, workspace_id, [company_id]))[0]
        signals = dict(company.signals or {})
        signals["_pecr"] = {**(signals.get("_pecr") or {"matched": False}), "consent": str(evidence)[:500],
                            "consent_recorded_at": _now().isoformat(timespec="seconds")}
        company.signals = signals
        await db.flush()
        return company_view(company)

    async def suppressed(self, db: AsyncSession, workspace_id: UUID, email: str) -> bool:
        email = (email or "").lower()
        domain = email.split("@", 1)[-1]
        return (await db.execute(select(func.count()).select_from(OutreachSuppression).where(
            OutreachSuppression.workspace_id == workspace_id,
            OutreachSuppression.value.in_([email, domain])))).scalar_one() > 0

    async def _close(self, db, workspace_id, prospect: Prospect, stage: str, *, reason: str) -> None:
        if prospect.email:
            await self.suppress(db, workspace_id, prospect.email, reason=reason)
        prospect.stage = stage
        if stage == "bounced":
            prospect.email_status = "invalid"

    async def _cancel_pending(self, db, prospect_id: UUID) -> None:
        for row in (await db.execute(select(OutreachMessage).where(
                OutreachMessage.prospect_id == prospect_id, OutreachMessage.direction == "out",
                OutreachMessage.status.in_(("draft", "approved"))))).scalars().all():
            row.status = "cancelled"

    async def _deal(self, db, workspace_id, prospect: Prospect, stage: str, owner: Optional[UUID] = None) -> None:
        from app.core.business.pipelines import pipeline_service
        from app.models.workspace import Workspace

        owner = owner or (await db.get(Workspace, workspace_id)).owner_id
        company = await db.get(ProspectCompany, prospect.company_id)
        try:
            async with db.begin_nested():  # a CRM failure never rolls back the outreach around it
                deal = await pipeline_service.update_deal(
                    db, workspace_id, owner, deal_id=str(prospect.deal_id) if prospect.deal_id else None,
                    title=None if prospect.deal_id else f"{company.name}: {prospect.name}"[:200], stage=stage,
                    value=None, notes=None, expected_close_date=None,
                    contact_name=None if prospect.deal_id else prospect.name,
                    contact_email=None if prospect.deal_id else prospect.email,
                    company=None if prospect.deal_id else company.name)
            prospect.deal_id = deal.id
        except Exception as exc:  # noqa: BLE001 - the CRM is kept in step when it can be; outreach never waits on it
            logger.warning("CRM deal not updated for %s: %s", prospect.name, exc)

    async def _companies(self, db, workspace_id, ids: Iterable[str]) -> List[ProspectCompany]:
        wanted = [UUID(str(i)) for i in ids]
        rows = (await db.execute(select(ProspectCompany).where(ProspectCompany.workspace_id == workspace_id,
                                                               ProspectCompany.id.in_(wanted)))).scalars().all()
        if len(rows) != len(set(wanted)):
            raise LookupError("A company was not found in this workspace")
        return list(rows)

    async def _prospect(self, db, workspace_id, prospect_id) -> Prospect:
        row = (await db.execute(select(Prospect).where(Prospect.workspace_id == workspace_id,
                                                       Prospect.id == UUID(str(prospect_id))))).scalar_one_or_none()
        if row is None:
            raise LookupError("Prospect not found in this workspace")
        return row

    async def _messages(self, db, workspace_id, ids) -> List[OutreachMessage]:
        wanted = [UUID(str(i)) for i in ids]
        rows = (await db.execute(select(OutreachMessage).where(
            OutreachMessage.workspace_id == workspace_id, OutreachMessage.id.in_(wanted),
            OutreachMessage.status == "draft", OutreachMessage.direction == "out"))).scalars().all()
        if len(rows) != len(set(wanted)):
            raise LookupError("A message was not found among this workspace's drafts")
        return list(rows)

    async def outbox(self, db: AsyncSession, workspace_id: UUID, status: Optional[str] = None,
                     limit: int = 50) -> List[Dict[str, Any]]:
        query = select(OutreachMessage).where(OutreachMessage.workspace_id == workspace_id,
                                              OutreachMessage.direction == "out")
        if status:
            query = query.where(OutreachMessage.status == status)
        rows = (await db.execute(query.order_by(OutreachMessage.created_at.desc()).limit(limit))).scalars().all()
        return [message_view(m) for m in rows]


def _parse_sequence(text: str) -> List[Tuple[str, str]]:
    out = []
    for block in re.split(r"\n\s*===+\s*\n", text.strip()):
        subject = re.search(r"^SUBJECT:\s*(.+)$", block, re.M)
        body = re.search(r"^BODY:\s*\n?(.*)$", block, re.M | re.S)
        if subject and body and body.group(1).strip():
            out.append((subject.group(1).strip(), body.group(1).strip()))
    return out


def company_view(c: ProspectCompany) -> Dict[str, Any]:
    return {"id": str(c.id), "name": c.name, "website": c.website, "domain": c.domain, "address": c.address,
            "category": c.category, "signals": c.signals or {}, "fit_score": c.fit_score, "status": c.status,
            "published_emails": c.published_emails or [], "source": c.source_ref}


def prospect_view(p: Prospect) -> Dict[str, Any]:
    return {"id": str(p.id), "company_id": str(p.company_id), "name": p.name, "role": p.role,
            "found_on": p.found_on, "email": p.email, "email_status": p.email_status,
            "email_evidence": p.email_evidence, "stage": p.stage,
            "deal_id": str(p.deal_id) if p.deal_id else None}


def message_view(m: OutreachMessage) -> Dict[str, Any]:
    return {"id": str(m.id), "prospect_id": str(m.prospect_id), "direction": m.direction, "step": m.step,
            "send_after_days": m.send_after_days, "subject": m.subject, "body": m.body, "status": m.status,
            "classification": m.classification, "sent_at": m.sent_at.isoformat() if m.sent_at else None,
            "error": m.error}


prospecting_service = ProspectingService()
