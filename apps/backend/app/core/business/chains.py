"""
JAI Backend - UK and US chains from open data, for the booking-partner database

Richard, 16 November: thousands of UK and US businesses to email for booking permission, the big chains first.
A specialist has no way to load a list of chains: its command gate blocks downloads (a safety rule kept as it is),
and the page reader summarises a large file. This reads two proven open sources and nothing else:

- the Name Suggestion Index (osmlab/name-suggestion-index, BSD-3-Clause): OpenStreetMap's catalogue of brands,
  one file per kind of business, each brand with the countries it trades in and its Wikidata ID;
- Wikidata (CC0): each brand's official website (property P856), with the country a website is for when Wikidata
  says (qualifier P1001).

Run on Richard's machine on 16 November (chains-probe and chains-probe-2): 1,364 UK and US chains across the
categories below; an official website on Wikidata for 149 of a sample of 150. Some brands' only website is for
another country (Kura Sushi's Japanese site, Galito's South African one): such a chain is listed with that site set
apart and no website, so no email from another country's office is ever taken for the UK or US one.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

NSI_FILE = "https://raw.githubusercontent.com/osmlab/name-suggestion-index/main/data/brands/{}.json"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_BATCH = 50          # wbgetentities takes up to 50 IDs a request
WIKIDATA_PAUSE = 1.0         # seconds between requests (Wikidata's API etiquette)

# Every kind of business Plexecute can book that the index lists (chains-probe-2, 16 November), in the order they
# are listed: food and drink, then stays, then fitness, beauty and cars.
CATEGORIES: Dict[str, str] = {
    "restaurant": "amenity/restaurant", "fast food": "amenity/fast_food", "cafe": "amenity/cafe",
    "pub": "amenity/pub", "bar": "amenity/bar", "ice cream": "amenity/ice_cream",
    "hotel": "tourism/hotel", "motel": "tourism/motel",
    "gym": "leisure/fitness_centre", "sports centre": "leisure/sports_centre",
    "hairdresser": "shop/hairdresser", "beauty": "shop/beauty", "massage": "shop/massage",
    "dentist": "amenity/dentist", "clinic": "amenity/clinic", "physiotherapist": "healthcare/physiotherapist",
    "vet": "amenity/veterinary",
    "car rental": "amenity/car_rental", "car repair": "shop/car_repair", "tyres": "shop/tyres",
    "car wash": "amenity/car_wash", "cinema": "amenity/cinema", "bowling": "leisure/bowling_alley",
}
COUNTRIES = {"uk": "gb", "gb": "gb", "united kingdom": "gb", "us": "us", "usa": "us", "united states": "us"}
COUNTRY_NAME = {"gb": "UK", "us": "US"}
COUNTRY_QID = {"gb": "Q145", "us": "Q30"}          # United Kingdom, United States of America
COUNTRY_TLD = {"gb": "uk", "us": "us"}
# Two-letter endings used as general web addresses, not as a country's.
GENERIC_TWO_LETTER = {"co", "io", "ai", "me", "tv", "fm", "ly", "to", "gg", "so"}
# Each email and phone keeps the page it is published on (16 November: JAI's independent check could not confirm
# emails whose source pages were not recorded beside them).
HEADER = ["Business", "Category", "Country", "Website", "Email", "Email source", "Phone", "Phone source",
          "Contact page", "Source", "Brand site (other country)", "still to check"]


def category_files(categories: Optional[Iterable[str]]) -> List[Tuple[str, str]]:
    """(label, index file) for each category asked for (all when none); an unknown one raises ValueError."""
    if not categories:
        return list(CATEGORIES.items())
    out = []
    for name in categories:
        key = str(name).strip().lower().replace("_", " ")
        key = {"fast_food": "fast food", "fitness centre": "gym", "fitness center": "gym", "cafes": "cafe",
               "restaurants": "restaurant", "hotels": "hotel", "pubs": "pub", "bars": "bar"}.get(key, key)
        if key not in CATEGORIES:
            raise ValueError(f"'{name}' is not a category the brand index lists; use any of: {', '.join(CATEGORIES)}")
        out.append((key, CATEGORIES[key]))
    return out


def country_codes(countries: Optional[Iterable[str]]) -> List[str]:
    codes = []
    for name in countries or ["UK", "US"]:
        code = COUNTRIES.get(str(name).strip().lower())
        if not code:
            raise ValueError(f"'{name}' is not UK or US")
        if code not in codes:
            codes.append(code)
    return codes


def trades_in(item: Dict[str, Any], code: str) -> bool:
    """Whether the index lists the brand in that country (a region of it counts; worldwide brands count too)."""
    where = [str(x).lower() for x in (item.get("locationSet") or {}).get("include") or []]
    return any(w == code or w.startswith(f"{code}-") or w == "001" for w in where)


def brands(items: List[Dict[str, Any]], codes: List[str], label: str) -> List[Dict[str, Any]]:
    """The brands of one index file that trade in the countries asked for and have a Wikidata ID."""
    out = []
    for item in items:
        tags = item.get("tags") or {}
        qid = str(tags.get("brand:wikidata") or "").strip()
        name = str(item.get("displayName") or tags.get("brand") or tags.get("name") or "").strip()
        where = [c for c in codes if trades_in(item, c)]
        if qid.startswith("Q") and name and where:
            out.append({"qid": qid, "name": name, "category": label, "countries": where})
    return out


def _host(url: str) -> str:
    try:
        return (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower()
    except ValueError:
        return ""


def foreign(url: str, code: str) -> bool:
    """A website whose address ends in another country's two-letter code (.co.jp, .co.za, .de)."""
    last = _host(url).rsplit(".", 1)[-1]
    return len(last) == 2 and last not in GENERIC_TWO_LETTER and last != COUNTRY_TLD[code]


def official_site(claims: Dict[str, Any], code: str) -> Tuple[str, str]:
    """(website for that country, a website for another country) from a brand's Wikidata claims.

    Preference: the website Wikidata says is for that country (P1001); then one ending in that country's code;
    then the preferred or first website with no country of its own and a general ending (.com). A brand whose only
    website is another country's returns ("", that website)."""
    sites = []
    for claim in claims.get("P856") or []:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if not isinstance(value, str) or not value.strip() or claim.get("rank") == "deprecated":
            continue
        juris = {((s.get("datavalue") or {}).get("value") or {}).get("id")
                 for s in (claim.get("qualifiers") or {}).get("P1001") or []}
        sites.append({"url": value.strip(), "juris": juris - {None}, "preferred": claim.get("rank") == "preferred"})
    if not sites:
        return "", ""
    for site in sites:
        if COUNTRY_QID[code] in site["juris"]:
            return site["url"], ""
    for site in sites:
        if _host(site["url"]).endswith(f".{COUNTRY_TLD[code]}"):
            return site["url"], ""
    general = sorted((s for s in sites if not s["juris"] and not foreign(s["url"], code)),
                     key=lambda s: not s["preferred"])
    if general:
        return general[0]["url"], ""
    return "", sites[0]["url"]


async def read_index(client, files: List[Tuple[str, str]], codes: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every brand of the categories asked for, each once (a brand in two categories keeps its first)."""
    found: Dict[str, Dict[str, Any]] = {}
    unread: List[str] = []
    for label, path in files:
        answer = await client.get(NSI_FILE.format(path))
        if answer.status_code != 200:
            unread.append(f"{label} (the index answered {answer.status_code})")
            continue
        for brand in brands(answer.json().get("items") or [], codes, label):
            found.setdefault(brand["qid"], brand)
    return list(found.values()), unread


WIKIDATA_TRIES = 6           # a busy answer is retried after the wait Wikidata gives
WIKIDATA_LEAST_WAIT = 5.0    # Manual:Maxlag_parameter: wait at least 5 seconds with maxlag=5


def _busy(answer) -> float:
    """Seconds to wait when Wikidata answers busy, 0 when it did not.

    16 November, first chains check: 1,194 of 1,689 chains came back without a website (the probe found one for
    149 of 150). Wikidata answers a request it cannot serve because its replicas lag with HTTP 200 and an error
    {"code": "maxlag"} and a Retry-After header (mediawiki.org, Manual:Maxlag_parameter); those answers were read
    as brands with no claims. A 429 or 503 with Retry-After is waited out the same way."""
    retry = answer.headers.get("retry-after")
    try:
        wait = max(WIKIDATA_LEAST_WAIT, float(retry)) if retry else WIKIDATA_LEAST_WAIT
    except ValueError:
        wait = WIKIDATA_LEAST_WAIT
    if answer.status_code in (429, 503):
        return wait
    if answer.status_code == 200:
        try:
            error = (answer.json() or {}).get("error") or {}
        except ValueError:
            return 0.0
        if error.get("code") == "maxlag":
            return wait
    return 0.0


async def read_websites(client, qids: List[str], pause: Optional[float] = None) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Each brand's Wikidata claims, 50 at a time: ({qid: claims}, [qids that could not be read and why]).
    pause 0 (tests) skips every wait."""
    pause = WIKIDATA_PAUSE if pause is None else pause
    claims: Dict[str, Dict[str, Any]] = {}
    unread: List[str] = []
    for start in range(0, len(qids), WIKIDATA_BATCH):
        batch = qids[start:start + WIKIDATA_BATCH]
        reason = ""
        for attempt in range(WIKIDATA_TRIES):
            answer = await client.get(WIKIDATA_API, params={
                "action": "wbgetentities", "ids": "|".join(batch), "props": "claims", "format": "json", "maxlag": 5})
            wait = _busy(answer)
            if wait:
                reason = f"Wikidata busy after {WIKIDATA_TRIES} tries"
                if attempt + 1 < WIKIDATA_TRIES and pause:
                    await asyncio.sleep(wait)
                continue
            if answer.status_code != 200:
                reason = f"Wikidata answered {answer.status_code}"
                break
            body = answer.json() or {}
            if body.get("error"):
                reason = f"Wikidata error {str(body['error'].get('code') or '')[:40]}"
                break
            for qid, entity in (body.get("entities") or {}).items():
                claims[qid] = entity.get("claims") or {}
            reason = ""
            break
        if reason:
            unread += [f"{q} ({reason})" for q in batch]
        if pause and start + WIKIDATA_BATCH < len(qids):
            await asyncio.sleep(pause)
    return claims, unread


def chain_rows(found: List[Dict[str, Any]], claims: Dict[str, Dict[str, Any]], known_sites: Iterable[str],
               known_names: Iterable[str] = ()) -> Tuple[List[List[str]], Dict[str, int]]:
    """One row per chain and website: a chain with the same site in both countries is one row (UK, US); with a
    different site for each, one row each. Sites already in the workbook are left out, and so is a chain with no
    website whose name is already listed."""
    known = {_host(s).removeprefix("www.") for s in known_sites if s}
    names = {str(n).strip().lower() for n in known_names if n}
    rows: List[List[str]] = []
    counts = {"chains": 0, "with_website": 0, "other_country_only": 0, "no_website": 0, "already_listed": 0,
              "wikidata_not_read": 0}
    for brand in found:
        counts["chains"] += 1
        if brand["qid"] not in claims:
            counts["wikidata_not_read"] += 1
            continue
        by_site: Dict[str, List[str]] = {}
        elsewhere = ""
        for code in brand["countries"]:
            site, other = official_site(claims.get(brand["qid"]) or {}, code)
            if site:
                by_site.setdefault(site, []).append(COUNTRY_NAME[code])
            elif other:
                elsewhere = other
        source = f"https://www.wikidata.org/wiki/{brand['qid']}"
        if not by_site:
            if brand["name"].lower() in names:
                counts["already_listed"] += 1
                continue
            counts["other_country_only" if elsewhere else "no_website"] += 1
            where = ", ".join(COUNTRY_NAME[c] for c in brand["countries"])
            note = ("only website on Wikidata is for another country: find its " + where + " site" if elsewhere
                    else "no official website on Wikidata: find its site")
            rows.append([brand["name"], brand["category"], where, "", "", "", "", "", "", source, elsewhere, note])
            continue
        for site, where in by_site.items():
            if _host(site).removeprefix("www.") in known:
                counts["already_listed"] += 1
                continue
            known.add(_host(site).removeprefix("www."))
            counts["with_website"] += 1
            rows.append([brand["name"], brand["category"], ", ".join(where), site, "", "", "", "", "", source, "", ""])
    return rows, counts
