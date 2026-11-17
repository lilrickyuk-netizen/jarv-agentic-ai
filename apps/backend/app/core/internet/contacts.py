"""
JAI Backend - A business's published contact details, read from its own website

14 November: a database of 124 businesses came back with a phone number for 7 and an email for 5. The agent had
read the sites; the page reader (internet.fetch_url) keeps a page's main article only, drops menus and footers and
stops at 8,000 characters, which is right for reading an article and throws away exactly where a business publishes
its phone number, its email address and its "Contact us" and "Partnerships" links.

Here the raw page is read instead, in code, with no model and nothing guessed:

- phone numbers from tel: links, from the page's own structured data (schema.org) and from text beside the words
  phone, tel or call;
- email addresses from mailto: links, from Cloudflare's email protection (decoded) and from the page's text;
- the site's own contact, partnership, leadership, press and investor pages, from its links.

The home page is read, then up to three of its contact and partnership pages (or the usual addresses when the home
page links none). Every value is one the business itself publishes on its own site, kept with the page it was found
on: published business contacts only, never an address built from a pattern (PECR).

Addresses are checked against the same private-network guard as every page JAI reads, and only pages on the
business's own site are followed.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import re
import urllib.parse
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_HTML = 600_000
PAGES_AFTER_HOME = 5
USUAL_PAGES = ("/contact", "/contact-us", "/about")
# Where a large chain publishes an address when its contact page is a form (15 November, from Richard's 50-business
# run: press@leon.co, media@itsu.com and franchise@paul-uk.com on press and franchise pages; PizzaExpress's press
# releases are PDFs on its own site): its press, franchise, partnership, property and events pages, found from its
# own links or its sitemap (sitemaps.org), and the PDFs it links from them, read through Docling.
_WHERE_CHAINS_PUBLISH = re.compile(r"press|media|news[- ]?room|franchis|partner|contact|enquir|propert|landlord|"
                                   r"site[- ]?(?:finder|search)|acquisition|private[- ]?dining|events?\b|corporate|"
                                   r"customer[- ]?(?:care|service)|get[- ]?in[- ]?touch|help", re.I)
SITEMAP_PAGES = 4
BROWSER_SECONDS, FURTHER_SECONDS = 90, 70
# Pages JAI asks the browser for at once. 16 November: ten sites at once, each asking for up to six pages, overran
# Crawl4AI's own page limit (crawler.max_pages, 40 by default, behind one global semaphore in its server) and seven
# sites ran out of time waiting; the browser is asked for a few pages at a time, the home and contact pages first.
BROWSER_AT_ONCE = 6
BROWSER_PAGES_PER_SITE = 2
_BROWSER: Dict[int, asyncio.Semaphore] = {}


def _browser_turn() -> asyncio.Semaphore:
    """One limit per event loop (a Semaphore belongs to the loop it was made on)."""
    loop = id(asyncio.get_running_loop())
    if loop not in _BROWSER:
        _BROWSER.clear()
        _BROWSER[loop] = asyncio.Semaphore(BROWSER_AT_ONCE)
    return _BROWSER[loop]
PDFS_READ = 2
MAX_PDF = 15_000_000
_TWO_PART = ("co.uk", "org.uk", "ac.uk", "gov.uk", "ltd.uk", "plc.uk", "me.uk", "com.au", "co.nz", "co.za")

_EMAIL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9][A-Za-z0-9.-]{0,251}\.[A-Za-z]{2,24}")
# A tracking service's address is never a contact (16 November: Denny's, Checkers, Rally's, Perkins, Chicken
# Express and Europcar were listed with 3b0f...@o17585.ingest.us.sentry.io, Sentry's error-reporting key, which
# their sites carry in their code): such services anywhere in the domain, and a long hexadecimal key before the @.
_NOT_EMAIL = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|avif|css|js|ico|woff2?)$|^(?:your|name|email|user|example|"
                        r"someone|firstname|first\.last|you)@|@(?:example|domain|email|yourdomain|sentry|"
                        r"sentry-next|wixpress|mysite|company|test)\.|@(?:[a-z0-9-]+\.)*(?:sentry|sentry-next|"
                        r"wixpress|ingest)\.|^[0-9a-f]{24,}@|^u002f|@[0-9.]+$|@2x\.", re.I)
_UK = r"(?:\+44[\s.-]?\(?0?\)?[\s.-]?|\(?\b0)\d{2,5}\)?(?:[\s.-]?\d{2,5}){1,3}"
_US = r"(?:\+1[\s.-]?)?\(?\b[2-9]\d{2}\)?[\s.-]\d{3}[\s.-]\d{4}\b"
_PHONE = re.compile(rf"(?:{_UK}|{_US})")
_NEAR_PHONE = re.compile(rf"(?:phone|tel(?:ephone)?|call(?:\s+us)?(?:\s+on)?|t)\s*[:.]?\s*((?:{_UK}|{_US}))", re.I)

KINDS = {
    "partnership": re.compile(r"partner|business[- ]?development|b2b|corporate[- ]?(?:enquir|sales|partner)|"
                              r"franchis|affiliat|work[- ]?with[- ]?us|suppliers?\b", re.I),
    "contact": re.compile(r"contact|get[- ]?in[- ]?touch|enquir|customer[- ]?(?:care|service|support)|"
                          r"help[- ]?(?:centre|center)|support\b", re.I),
    "leadership": re.compile(r"leadership|management[- ]?team|our[- ]?team|executive|board|directors|"
                             r"our[- ]?people|who[- ]?we[- ]?are|about", re.I),
    "press": re.compile(r"press|media|news[- ]?room", re.I),
    "investors": re.compile(r"investor", re.I),
}
# The email a partnership request should go to first, then the press office, then the general address.
_EMAIL_ORDER = (re.compile(r"partner|bizdev|business|b2b|corporate|commercial", re.I),
                re.compile(r"press|media|pr@|comms|communications", re.I),
                re.compile(r"^(?:info|hello|hi|contact|enquir|inquir|office|admin|reception|team|mail|general)", re.I))


def site_of(url: str) -> str:
    """The site an address belongs to: its registered domain ("https://www.nandos.co.uk/contact" -> nandos.co.uk)."""
    host = (urllib.parse.urlparse(url if "://" in url else f"https://{url}").hostname or "").lower().strip(".")
    host = host[4:] if host.startswith("www.") else host
    labels = host.split(".")
    keep = 3 if any(host.endswith("." + ending) or host == ending for ending in _TWO_PART) else 2
    return ".".join(labels[-keep:]) if len(labels) >= keep else host


def tidy_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    return url if re.match(r"^https?://", url, re.I) else f"https://{url.lstrip('/')}"


def _cf_email(encoded: str) -> str:
    """Cloudflare's protected address ("[email protected]" on the page) decoded from its data-cfemail value."""
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except ValueError:
        return ""


def _visible(page: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg|template)\b.*?</\1>", " ", page)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_lib.unescape(text))


def _digits(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    for prefix, national in (("0044", "0"), ("44", "0"), ("001", ""), ("1", "")):
        if digits.startswith(prefix) and len(digits) - len(prefix) >= 9 and (prefix != "1" or len(digits) == 11):
            return national + digits[len(prefix):].lstrip("0") if national else digits[len(prefix):]
    return digits


def _phone_ok(phone: str) -> bool:
    """A number someone can ring: checked against Google's libphonenumber numbering plans (the phonenumbers package,
    its Python port) for the UK, or the US for a North American number. 16 November: Zizzi's and Origin's sites
    print "01483 66420", a Guildford number one digit short, and it was counted as a way to contact them."""
    digits = re.sub(r"\D", "", phone)
    if not (10 <= len(digits) <= 13 and len(set(digits)) > 2 and not re.fullmatch(r"(19|20)\d{6,8}", digits)):
        return False
    try:
        import phonenumbers
    except ImportError:  # the image ships it (Dockerfile); without it the shape check above stands
        return True
    region = None if phone.lstrip().startswith("+") else (
        "US" if re.fullmatch(_US, phone.strip()) and not phone.strip().startswith("0") else "GB")
    try:
        return phonenumbers.is_valid_number(phonenumbers.parse(phone, region))
    except phonenumbers.NumberParseException:
        return False


def _clean_phone(raw: str) -> str:
    phone = urllib.parse.unquote(raw).strip()
    phone = re.sub(r"(?i)^tel:|;.*$|(?:ext|x)\.?\s*\d+$", "", phone).strip()
    return re.sub(r"\s+", " ", phone)


def _structured(page: str) -> Tuple[List[str], List[str]]:
    """Phones and emails the page states as structured data (schema.org JSON-LD)."""
    phones: List[str] = []
    emails: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() == "telephone" and isinstance(value, str):
                    phones.append(value)
                elif key.lower() == "email" and isinstance(value, str):
                    emails.append(re.sub(r"(?i)^mailto:", "", value))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for block in re.findall(r"(?is)<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", page):
        try:
            walk(json.loads(html_lib.unescape(block.strip())))
        except ValueError:
            continue
    return phones, emails


def extract(page: str, url: str) -> Dict[str, Any]:
    """What one page publishes: {"emails", "phones", "links": {kind: [addresses on the same site]}}. page is the
    raw HTML (or, for a page read through the browser, its Markdown: links as [text](address))."""
    page = page[:MAX_HTML]
    site = site_of(url)
    emails: List[str] = []
    phones: List[str] = []

    def add_email(value: str) -> None:
        value = html_lib.unescape(urllib.parse.unquote(value)).strip().strip(".,;:<>()[]\"'").lower()
        if _EMAIL.fullmatch(value) and not _NOT_EMAIL.search(value) and value not in emails:
            emails.append(value)

    def add_phone(value: str) -> None:
        phone = _clean_phone(value)
        if _phone_ok(phone) and _digits(phone) not in {_digits(p) for p in phones}:
            phones.append(phone)

    structured_phones, structured_emails = _structured(page)
    for value in re.findall(r"(?i)href\s*=\s*[\"']\s*tel:([^\"']+)", page) + re.findall(
            r"(?i)\]\(\s*tel:([^)\s]+)\)", page) + structured_phones:
        add_phone(value)
    for value in re.findall(r"(?i)href\s*=\s*[\"']\s*mailto:([^\"'?]+)", page) + re.findall(
            r"(?i)\]\(\s*mailto:([^)?\s]+)", page) + structured_emails:
        add_email(value)
    for encoded in re.findall(r"(?i)data-cfemail\s*=\s*[\"']([0-9a-f]+)[\"']", page) + re.findall(
            r"(?i)/cdn-cgi/l/email-protection#([0-9a-f]+)", page):
        add_email(_cf_email(encoded))
    text = _visible(page)
    for value in _EMAIL.findall(text):
        add_email(value)
    for value in _NEAR_PHONE.findall(text):
        add_phone(value)

    links: Dict[str, List[str]] = {kind: [] for kind in KINDS}
    pdfs: List[str] = []
    anchors = re.findall(r"(?is)<a\b[^>]*?href\s*=\s*[\"']([^\"'#]+)[^\"']*[\"'][^>]*>(.*?)</a>", page)
    anchors += [(href, label) for label, href in re.findall(r"\[([^\]]{1,80})\]\((https?://[^)\s]+)\)", page)]
    for href, label in anchors:
        href = html_lib.unescape(href).strip()
        if re.match(r"(?i)^(?:mailto:|tel:|javascript:|data:)", href):
            continue
        address = urllib.parse.urljoin(url, href).split("#")[0]
        if not address.startswith("http") or site_of(address) != site:
            continue
        if re.search(r"(?i)\.pdf(?:\?|$)|/pdfs?/", address):
            words = f"{urllib.parse.urlparse(address).path} {_visible(label)}"
            if re.search(r"(?i)press|release|media|brochure|event|dining|partner|franchis|contact", words) and \
                    address not in pdfs and len(pdfs) < 6:
                pdfs.append(address)
            continue
        if re.search(r"(?i)\.(?:jpe?g|png|gif|zip|docx?|xlsx?|ashx)(?:\?|$)", address):
            continue
        words = f"{urllib.parse.urlparse(address).path} {_visible(label)}"
        for kind, pattern in KINDS.items():
            if pattern.search(words) and address not in links[kind] and len(links[kind]) < 4:
                links[kind].append(address)
                break
    return {"emails": emails, "phones": phones, "links": links, "pdfs": pdfs}


def best_email(emails: List[str], site: str) -> str:
    """The address a partnership request is best sent to: one on the business's own site first, a partnerships
    address before the press office before the general one."""
    def rank(email: str) -> Tuple[int, int]:
        local = email.split("@")[0]
        kind = next((i for i, pattern in enumerate(_EMAIL_ORDER) if pattern.search(local)), len(_EMAIL_ORDER))
        return (0 if site and site_of(email.split("@")[1]) == site else 1, kind)

    return sorted(emails, key=rank)[0] if emails else ""


Fetch = Callable[[str], Awaitable[Dict[str, Any]]]


async def fetch_raw(url: str) -> Dict[str, Any]:
    """One page as the site sends it: {"ok", "url", "status", "html"}. Private and local addresses are refused, and
    the final address is checked too. A page that refuses a plain read, or is built by JavaScript, is read through
    JAI's browser and its Markdown is returned in "html" (its links and text are found the same way)."""
    import httpx

    from app.core import internet

    ok, reason = internet._ssrf_ok(url)
    if not ok:
        return {"ok": False, "url": url, "reason": reason, "blocked": True}
    out: Dict[str, Any] = {"ok": False, "url": url}
    try:
        async with httpx.AsyncClient(timeout=internet.FETCH_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "JAI-Research/1.0",
                                                      "Accept": "text/html,application/xhtml+xml"})
        final_ok, final_reason = internet._ssrf_ok(str(response.url))
        if not final_ok:
            return {"ok": False, "url": str(response.url), "blocked": True,
                    "reason": f"redirected to a blocked address: {final_reason}"}
        out = {"ok": response.status_code < 400, "url": str(response.url), "status": response.status_code,
               "html": response.text[:MAX_HTML]}
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "url": url, "reason": str(exc)[:200]}
    thin = len(_visible(out.get("html") or "")) < internet.THIN_PAGE_CHARS
    if not out.get("ok") or thin:
        rendered = await fetch_rendered(out.get("url") or url)
        if rendered.get("ok"):
            return rendered
        out.setdefault("reason", rendered.get("reason") or "")
    return out


async def fetch_rendered(url: str) -> Dict[str, Any]:
    """One page as a browser shows it, read through Crawl4AI (JAI's headless browser): its whole rendered HTML, so the
    footer, the tel: and mailto: links and the schema.org data are all there. 15 November: the browser read used
    internet.render_page, which asks Crawl4AI for its "fit" Markdown (the main content, the footer pruned away) cut to
    8,000 characters: a site that turns plain readers away or builds its page with JavaScript lost exactly the
    details this reader looks for. Crawl4AI's /crawl answer carries the full HTML; its /md answer with the "raw"
    filter (the whole page, nothing pruned) is the second way. {"ok", "url", "status", "html", "rendered"}."""
    from app.core import internet

    base = internet._setting("CRAWL4AI_URL")
    if not base:
        return {"ok": False, "url": url, "reason": "the browser (Crawl4AI) is turned off"}
    async with _browser_turn():
        return await _rendered(url, base)


async def _rendered(url: str, base: str) -> Dict[str, Any]:
    import httpx

    from app.core import internet
    from app.core.config import settings

    ok, reason = internet._ssrf_ok(url)
    if not ok:
        return {"ok": False, "url": url, "reason": reason, "blocked": True}
    token = getattr(settings, "CRAWL4AI_TOKEN", None)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    wait = float(getattr(settings, "RESEARCH_TIMEOUT_SECONDS", 30) or 30) + 25
    reasons: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=wait) as client:
            answer = await client.post(f"{base}/crawl", headers=headers, json={
                "urls": [url], "browser_config": {"type": "BrowserConfig", "params": {"headless": True}},
                "crawler_config": {"type": "CrawlerRunConfig", "params": {"stream": False, "cache_mode": "bypass"}}})
            if answer.status_code < 400:
                result = ((answer.json() or {}).get("results") or [{}])[0] or {}
                page = str(result.get("html") or result.get("cleaned_html") or "")
                final = str(result.get("redirected_url") or result.get("url") or url)
                if result.get("success", True) and len(_visible(page)) >= 1 and internet._ssrf_ok(final)[0]:
                    return {"ok": True, "url": final, "status": int(result.get("status_code") or 200),
                            "html": page[:MAX_HTML], "rendered": True}
                reasons.append(str(result.get("error_message") or "the browser read an empty page")[:120])
            else:
                reasons.append(f"the browser answered {answer.status_code}")
            answer = await client.post(f"{base}/md", headers=headers, json={"url": url, "f": "raw", "c": "0"})
            markdown = str(((answer.json() or {}) if answer.status_code < 400 else {}).get("markdown") or "")
            if markdown.strip():
                return {"ok": True, "url": url, "status": 200, "html": markdown[:MAX_HTML], "rendered": True}
            reasons.append(f"its Markdown answer was empty ({answer.status_code})")
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, IndexError) as exc:
        reasons.append(f"the browser could not be reached: {type(exc).__name__}")
    return {"ok": False, "url": url, "reason": "; ".join(reasons)[:200]}


async def site_contacts(url: str, fetch: Optional[Fetch] = None) -> Dict[str, Any]:
    """A business's published contact details, from its own site: the home page and up to three of its contact and
    partnership pages. {"ok", "site", "phones": [{"value", "source"}], "emails": [...], "phone", "email",
    "contact_page", "partnership_page", "leadership_pages", "press_pages", "investor_pages", "pages_read",
    "pages_failed"}. ok is False when the home page could not be read. Never raises."""
    fetch = fetch or fetch_raw
    start = tidy_url(url)
    site = site_of(start)
    out: Dict[str, Any] = {"ok": False, "site": site, "phones": [], "emails": [], "phone": "", "email": "",
                           "contact_page": "", "partnership_page": "", "leadership_pages": [], "press_pages": [],
                           "investor_pages": [], "pages_read": [], "pages_failed": []}
    if not site or "." not in site:
        out["reason"] = "no website address"
        return out
    try:
        home = await fetch(start)
    except Exception as exc:  # noqa: BLE001
        home = {"ok": False, "reason": str(exc)[:200]}
    if not home.get("ok") or not home.get("html"):
        out["pages_failed"].append(start)
        out["reason"] = str(home.get("reason") or f"the site answered {home.get('status')}")[:200]
        return out
    home_url = str(home.get("url") or start)
    if site_of(home_url) != site:  # the business's address forwards to its real site: that site is the business's
        site = out["site"] = site_of(home_url)
    found = extract(home["html"], home_url)
    links: Dict[str, List[str]] = {kind: list(found["links"][kind]) for kind in KINDS}
    links["pdfs"] = list(found.get("pdfs") or [])

    def take(page_url: str, got: Dict[str, Any]) -> None:
        out["pages_read"].append(page_url)
        for kind in ("phones", "emails"):
            have = {(_digits(e["value"]) if kind == "phones" else e["value"]) for e in out[kind]}
            for value in got[kind]:
                key = _digits(value) if kind == "phones" else value
                if key not in have and len(out[kind]) < 8:
                    out[kind].append({"value": value, "source": page_url})
                    have.add(key)

    take(home_url, found)
    follow = (links["partnership"][:2] + links["contact"][:2] + links["press"][:1])[:PAGES_AFTER_HOME]
    if not links["contact"]:  # the home page links no contact page: try the usual addresses
        follow += [urllib.parse.urljoin(home_url, path) for path in USUAL_PAGES][:PAGES_AFTER_HOME - len(follow)]
    follow = [page for page in dict.fromkeys(follow) if page.rstrip("/") != home_url.rstrip("/")]
    pages = await asyncio.gather(*(fetch(page) for page in follow), return_exceptions=True)
    for page_url, page in zip(follow, pages):
        if isinstance(page, dict) and page.get("ok") and page.get("html") and site_of(
                str(page.get("url") or page_url)) == site:
            got = extract(page["html"], str(page.get("url") or page_url))
            take(str(page.get("url") or page_url), got)
            for kind in KINDS:
                links[kind] += [link for link in got["links"][kind] if link not in links[kind]]
            links["pdfs"] += [link for link in got.get("pdfs") or [] if link not in links["pdfs"]]
            if not links["contact"] and KINDS["contact"].search(urllib.parse.urlparse(page_url).path):
                links["contact"].append(str(page.get("url") or page_url))  # a usual address that was really there
        else:
            out["pages_failed"].append(page_url)
    if fetch is fetch_raw and not out["phones"] and not out["emails"]:
        # The plain pages carried no phone or email: a page whose details JavaScript puts in (a shell of menus in the
        # plain HTML) is read again as the browser shows it.
        contact_first = [p for p in out["pages_read"][1:] if p in links["contact"] or p in links["partnership"]]
        again = list(dict.fromkeys([home_url] + contact_first + out["pages_read"][1:]))[:BROWSER_PAGES_PER_SITE]
        try:  # what the browser shows within 45 seconds; a page it is still loading is left
            shown = await asyncio.wait_for(asyncio.gather(*(fetch_rendered(page) for page in dict.fromkeys(again)),
                                                          return_exceptions=True), timeout=BROWSER_SECONDS)
        except asyncio.TimeoutError:
            shown = []
            out["browser"] = f"the browser took longer than {BROWSER_SECONDS} seconds"  # what it read is kept
        for page_url, page in zip(dict.fromkeys(again), shown):
            if isinstance(page, dict) and page.get("ok") and site_of(str(page.get("url") or page_url)) == site:
                got = extract(page["html"], str(page.get("url") or page_url))
                take(str(page.get("url") or page_url), got)
                for kind in KINDS:
                    links[kind] += [link for link in got["links"][kind] if link not in links[kind]]
                links["pdfs"] += [link for link in got.get("pdfs") or [] if link not in links["pdfs"]]
            elif isinstance(page, dict) and page.get("reason"):
                out.setdefault("browser", str(page["reason"])[:200])
        out["read_by_browser"] = True
    if fetch is fetch_raw and not out["emails"]:
        try:  # what is found in the time is kept (take() records each page as it is read)
            await asyncio.wait_for(_where_chains_publish(home_url, site, out, links, take), timeout=FURTHER_SECONDS)
        except asyncio.TimeoutError:
            out["further"] = f"the press, franchise and PDF pages took longer than {FURTHER_SECONDS} seconds"
    # On a contact or partnership page the details beside the form come first; the home page's come after.
    for kind in ("phones", "emails"):
        out[kind].sort(key=lambda entry: 0 if entry["source"].rstrip("/") != home_url.rstrip("/") else 1)
    out["phone"] = out["phones"][0]["value"] if out["phones"] else ""
    out["email"] = best_email([e["value"] for e in out["emails"]], site)
    out["contact_page"] = (links["contact"] or [""])[0]
    out["partnership_page"] = (links["partnership"] or [""])[0]
    out["leadership_pages"], out["press_pages"] = links["leadership"][:3], links["press"][:2]
    out["investor_pages"] = links["investors"][:2]
    out["ok"] = True
    return out


async def fetch_text(url: str) -> Dict[str, Any]:
    """A plain file of the site (robots.txt, a sitemap) as it is sent, never through the browser."""
    import httpx

    from app.core import internet

    if not internet._ssrf_ok(url)[0]:
        return {"ok": False, "url": url}
    try:
        async with httpx.AsyncClient(timeout=internet.FETCH_TIMEOUT, follow_redirects=True) as client:
            answer = await client.get(url, headers={"User-Agent": "JAI-Research/1.0"})
        if not internet._ssrf_ok(str(answer.url))[0]:
            return {"ok": False, "url": url}
        return {"ok": answer.status_code < 400, "url": str(answer.url), "html": answer.text[:MAX_HTML]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": url, "reason": str(exc)[:200]}


async def sitemap_pages(home_url: str, fetch: Fetch, wanted: "re.Pattern[str]", most: int) -> List[str]:
    """Pages of the site's own sitemap (the sitemaps.org protocol: robots.txt names it, /sitemap.xml by default; a
    sitemap index lists further sitemaps) whose address matches ``wanted``, up to ``most``."""
    from xml.etree import ElementTree

    site = site_of(home_url)
    queue = [urllib.parse.urljoin(home_url, "/sitemap.xml")]
    robots = await fetch(urllib.parse.urljoin(home_url, "/robots.txt"))
    if robots.get("ok") and not robots.get("rendered"):
        named = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", str(robots.get("html") or ""))
        queue = [u for u in named if site_of(u) == site][:3] or queue
    found: List[str] = []
    seen = 0
    while queue and seen < 6 and len(found) < most:
        url = queue.pop(0)
        seen += 1
        page = await fetch(url)
        text = str(page.get("html") or "") if page.get("ok") and not page.get("rendered") else ""
        try:
            root = ElementTree.fromstring(text.encode("utf-8")) if text.lstrip().startswith("<") else None
        except ElementTree.ParseError:
            root = None
        if root is None:
            continue
        locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
        if root.tag.endswith("sitemapindex"):
            queue += [u for u in locs if site_of(u) == site and wanted.search(u + " pages")][:2] + [
                u for u in locs if site_of(u) == site][:2]
            continue
        for loc in locs:
            path = urllib.parse.urlparse(loc).path
            if site_of(loc) == site and wanted.search(path) and loc not in found:
                found.append(loc)
                if len(found) >= most:
                    break
    return found


async def fetch_pdf(url: str) -> Dict[str, Any]:
    """A PDF on the business's own site, read through Docling (JAI's document reader, IBM's open-source converter):
    {"ok", "url", "html": its Markdown}."""
    import httpx

    from app.core import documents, internet

    ok, reason = internet._ssrf_ok(url)
    if not ok:
        return {"ok": False, "url": url, "reason": reason}
    try:
        async with httpx.AsyncClient(timeout=internet.FETCH_TIMEOUT * 2, follow_redirects=True) as client:
            answer = await client.get(url, headers={"User-Agent": "JAI-Research/1.0"})
        if answer.status_code >= 400 or len(answer.content) > MAX_PDF or not internet._ssrf_ok(str(answer.url))[0]:
            return {"ok": False, "url": url, "reason": f"the PDF answered {answer.status_code}"}
        name = urllib.parse.urlparse(str(answer.url)).path.rsplit("/", 1)[-1] or "page.pdf"
        name = name if name.lower().endswith(".pdf") else f"{name}.pdf"
        converted = await documents.convert(name, answer.content)
        return {"ok": True, "url": str(answer.url), "html": str(converted.get("markdown") or "")[:MAX_HTML]}
    except Exception as exc:  # noqa: BLE001 - one PDF that cannot be read leaves the others
        return {"ok": False, "url": url, "reason": str(exc)[:200]}


async def _where_chains_publish(home_url: str, site: str, out: Dict[str, Any], links: Dict[str, List[str]],
                                take: Callable[[str, Dict[str, Any]], None]) -> None:
    """No email on the home, contact and partnership pages: the site's own press, franchise, partnership and
    events pages from its sitemap, then the PDFs (press releases, brochures) its pages link, read for the address
    the business publishes there."""
    read = {page.rstrip("/") for page in out["pages_read"]}
    try:
        more = [page for page in await sitemap_pages(home_url, fetch_text, _WHERE_CHAINS_PUBLISH, SITEMAP_PAGES * 2)
                if page.rstrip("/") not in read][:SITEMAP_PAGES]
    except Exception as exc:  # noqa: BLE001
        more = []
        out["sitemap"] = f"not read: {type(exc).__name__}"
    pages = await asyncio.gather(*(fetch_raw(page) for page in more), return_exceptions=True)
    pdfs: List[str] = []
    for page_url, page in zip(more, pages):
        if isinstance(page, dict) and page.get("ok") and site_of(str(page.get("url") or page_url)) == site:
            got = extract(page["html"], str(page.get("url") or page_url))
            take(str(page.get("url") or page_url), got)
            pdfs += got.get("pdfs") or []
    out["sitemap_pages"] = more
    if out["emails"]:
        return
    pdfs = [p for p in dict.fromkeys(list(links.get("pdfs") or []) + pdfs)][:PDFS_READ]
    found = await asyncio.gather(*(fetch_pdf(p) for p in pdfs), return_exceptions=True)
    for pdf_url, got in zip(pdfs, found):
        if isinstance(got, dict) and got.get("ok"):
            take(str(got.get("url") or pdf_url), extract(got["html"], str(got.get("url") or pdf_url)))
    out["pdfs_read"] = pdfs


def source_of(found: Dict[str, Any], kind: str, value: str) -> str:
    """The page a phone number or email address was found on."""
    return next((entry["source"] for entry in found.get(kind) or [] if entry["value"] == value), "")
