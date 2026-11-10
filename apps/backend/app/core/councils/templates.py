"""
JAI Backend - Workflow templates and their councils

A workflow is a chain of missions, each done by the specialist its council names, with Richard's approval gates
between them (Richard, 10 November: "you stop writing briefs"). He starts one with a sentence ("run investor outreach
for Plexecute"); JAI fills each step's brief with the product's name and folder, starts the missions one after
another, and stops at each gate until he approves it on the Approvals page. Sending, publishing and paying stay his:
no step sends or posts anything.

Each step's brief is written so the specialist starts fresh work ("new work with its own checklist") and never
inherits an earlier mission's checklist, and it names its specialist ("Specialist: sales."), so routing never
guesses.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

NEW = "This is new work with its own checklist."
HONEST = ("Use only contact details the organisation publishes for this purpose; never guess an email; firms and "
          "published business contacts only, never private individuals' personal emails.")

TEMPLATES: Dict[str, Dict[str, Any]] = {
    "investor_outreach": {
        "title": "Investor outreach",
        "summary": "Find investors and buyers with published pitch routes, write a personal introduction to each, "
                   "wait for Richard to review and send them, then prepare the follow-ups.",
        "council": ["sales", "content"],
        "steps": [
            {"id": "prospects", "specialist": "sales", "title": "Find investors and buyers",
             "brief": ("In {folder}, build or improve outreach/{slug}-Prospects.xlsx for {product}. Keep every "
                       "organisation already there. Find investors (VC funds, angel networks, accelerators, corporate "
                       "venture arms) that back pre-seed or seed companies like {product}, UK and Europe first, and "
                       "companies that could acquire or partner with {product}. For each: organisation, type, "
                       "country, website, its published pitch email or pitch form link from its own website with the "
                       "page it is on, the partner who covers this area where the site names one, a company it has "
                       "backed or bought that is like {product} with the page that shows it, and a fit score from 1 "
                       "to 5. Keep the proven ones (a pitch route and a named similar company) on the main sheets and "
                       "the rest on a sheet called \"Not yet proven\" with what is missing. Aim for 50 proven "
                       "organisations and say how many were found. " + HONEST + " " + NEW)},
            {"id": "introductions", "specialist": "sales", "title": "Write the introductions",
             "brief": ("In {folder}, prepare the first introduction to every organisation on the main sheets of "
                       "outreach/{slug}-Prospects.xlsx, in outreach/introductions.xlsx, using only what is in the "
                       "folder (the prospects sheet, the product's description and the pitch deck); look up nothing "
                       "new and send nothing. One row per organisation: who it goes to, how (email or form link), a "
                       "subject line under 60 characters that names {product}, and an introduction of no more than "
                       "110 words that opens with that firm's own precedent or focus, says the problem {product} "
                       "solves and what it does in one sentence each, says it is raising a pre-seed round with its "
                       "waiting list open, and ends with one clear ask, the founder's sign-off and a line saying they "
                       "can reply to opt out. No two introductions share a sentence apart from the sign-off and "
                       "opt-out. Partners (not investors) get no fundraising line. Add a Priority column: 1 for those "
                       "with a named precedent company, 2 for the rest. " + NEW)},
            {"id": "review", "gate": True, "title": "Richard reviews and sends",
             "ask": ("Read outreach/introductions.xlsx in the {product} folder and send the priority-1 introductions "
                     "yourself (sending stays with you). Approve when you have sent them, and JAI prepares the "
                     "follow-ups; reject to stop the workflow here.")},
            {"id": "follow_ups", "specialist": "content", "title": "Prepare the follow-ups",
             "brief": ("In {folder}, write a short follow-up to each introduction in outreach/introductions.xlsx, to "
                       "send seven days after it if there is no reply, in outreach/follow-ups.xlsx: one row per "
                       "organisation, the same channel, a subject line, and no more than 70 words that add one new, "
                       "true detail about {product} from the folder and repeat the ask. Look up nothing new and send "
                       "nothing. " + NEW)},
        ],
    },
    "waitlist_growth": {
        "title": "Waiting-list growth",
        "summary": "Find the free places where {product}'s users are (creators, blogs that take free guest "
                   "articles, communities and partner businesses), write a pitch to each, wait for Richard to "
                   "review and send them, then prepare two weeks of posts and the lead magnet.",
        "council": ["marketing", "content"],
        "steps": [
            {"id": "growth_list", "specialist": "marketing", "title": "Find the audiences",
             "brief": ("In {folder}, build or update growth/{slug}-Waitlist-Growth.xlsx so people who want {product} "
                       "join its waiting list themselves, at no cost to Richard. Read the product's own description "
                       "first and aim at the people it is for. Keep every row already there that has a published "
                       "contact and costs nothing, then add with JAI's search tools: creators (target 30) in the "
                       "product's own field, UK first, with roughly 10,000 to 500,000 followers, found through "
                       "round-up lists, their talent agency or management pages and their own websites' contact or "
                       "collaborations pages, each with a published business email; blogs and websites that publish "
                       "free guest articles (target 20), shown on their own 'write for us' page; partner businesses "
                       "(target 20) that could recommend {product} to their own customers for free; and communities "
                       "(target 20): "
                       "subreddits (read each one's rules at old.reddit.com/r/NAME/about/rules, which needs no "
                       "login), UK Facebook groups and forums, with their size and rule on self-promotion. No "
                       "employers: {product} reaches them through employee-benefits platforms. Nothing paid: no "
                       "sponsorships, adverts or sponsored posts. Give every row a fit "
                       "score from 1 to 5 and the page each detail is on, sort each sheet by fit, and write at the "
                       "top of each sheet how many were found against its target. "
                       + HONEST + " " + NEW)},
            {"id": "pitches", "specialist": "marketing", "title": "Write the pitches",
             "brief": ("In {folder}, write a short pitch to each creator, blog and partner in "
                       "growth/{slug}-Waitlist-Growth.xlsx, in growth/pitches.xlsx, using only what is in the folder; "
                       "look up nothing new and send nothing. One row per audience: who, how (their published email "
                       "or form), a subject line, and no more than 100 words that name something specific about "
                       "their audience, say what {product} does for that audience in one sentence (its main "
                       "selling point included), and ask for a free collaboration, a guest article or a partnership "
                       "with a link to the waiting list, signed by Richard by name. Claim no customers or results "
                       "the product does not have yet. Add a Priority column from the fit score. " + NEW)},
            {"id": "review", "gate": True, "title": "Richard reviews and sends",
             "ask": ("Read growth/pitches.xlsx in the {product} folder and send the ones you want (sending stays "
                     "with you). Approve when you have, and JAI prepares two weeks of posts and the lead magnet; "
                     "reject to stop the workflow here.")},
            {"id": "launch_content", "specialist": "content", "title": "Two weeks of posts and the lead magnet",
             "brief": ("In {folder}, write growth/launch-content.md for {product}: the free lead magnet from the "
                       "growth plan written out in full, and two weeks of social posts (one a day for LinkedIn and "
                       "one for Instagram or TikTok) that lead people to the waiting list, each with its hook and "
                       "call to action. Use only what is in the folder and publish nothing. " + NEW)},
        ],
    },
}

_SPOKEN = {
    "investor_outreach": re.compile(r"\binvestor\s+outreach\b|\boutreach\s+to\s+investors\b|\bfundrais", re.I),
    "waitlist_growth": re.compile(r"\bwait(?:ing)?[- ]?list\s+growth\b|\bgrow\s+the\s+wait(?:ing)?[- ]?list\b", re.I),
}


def template_named(words: str) -> Optional[str]:
    """Which template Richard's words name ("run investor outreach for Plexecute"), or None."""
    key = (words or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in TEMPLATES:
        return key
    return next((name for name, pattern in _SPOKEN.items() if pattern.search(words or "")), None)


def slug(product: str) -> str:
    """The product's name as it goes in file names (Plexecute, My-App)."""
    words = re.findall(r"[A-Za-z0-9]+", product or "") or ["Product"]
    return "-".join(w[:1].upper() + w[1:] for w in words)


def steps(template: str, *, product: str, folder: str) -> List[Dict[str, Any]]:
    """The template's steps with the product's name and folder filled in; a mission step's brief names its
    specialist first ("Specialist: sales.")."""
    filled = []
    values = {"product": product, "folder": folder, "slug": slug(product)}
    for step in TEMPLATES[template]["steps"]:
        step = dict(step)
        if step.get("gate"):
            step["ask"] = step["ask"].format(**values)
        else:
            step["brief"] = f"Specialist: {step['specialist']}. " + step["brief"].format(**values)
        filled.append(step)
    return filled
