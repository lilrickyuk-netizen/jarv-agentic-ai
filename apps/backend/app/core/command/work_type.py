"""
JAI Backend - Which specialist a mission's work belongs to

Richard, 9 November: "I shouldn't really have to mention what skill it needs to use." A prospect database built by
the Lead Builder came back thin because the builder, offered every skill, loaded none of the sales ones; the same
brief opened with "Using your prospecting skill" went to the Sales Lead and used them. So JAI reads the brief itself:
sales, research, marketing, content, business, finance, support, partnership and legal work goes to that specialist,
who works through the acceptance ledger the way the builder does, with its own skills in front of it and told which
to use first. Software work stays with the Lead Builder. A skill Richard names still wins (skill_packs.named_skill).
"""

import re
from typing import Dict, List, Optional, Pattern, Tuple

# Software work: the Lead Builder owns it, whatever else the brief mentions.
_ENGINEERING = re.compile(
    r"\b(code|coding|codebase|repo|repository|refactor|bug|bugs|debug|compile|unit tests?|test suite|"
    r"frontend|backend|api endpoints?|database migrations?|schema migration|docker|kubernetes|deploy|deployment|"
    r"ci pipeline|github actions|typescript|python|react|next\.?js|fastapi|implement|"
    # A product being built in phases from a specification (MYCO): software, whatever else the brief says.
    r"phase\s*\d+|specification|mvp|prototype|"
    r"(?:build|fix|ship|write)\s+(?:the|an?|my|our)?\s*(?:app|website|site|feature|service|endpoint|component|"
    r"screen|page|integration))\b", re.I)

# Video and motion work stays with the Lead Builder too: on 9 November it made a good ad in minutes for about four
# pounds, and BRAG runs only when Richard asks for it.
_BUILDER_KEEPS = re.compile(r"\b(video|videos|animation|animated|motion graphics|ad film|reel|reels)\b",
                            re.I)

# (specialist, what the brief says, the skills to start with, in the order to use them). First match wins, so the
# more specific kinds of work come first.
_KINDS: List[Tuple[str, Pattern[str], Tuple[str, ...]]] = [
    # Making a deck (not sending one: outreach that attaches the deck is sales work).
    ("content", re.compile(r"\b(?:make|create|build|design|produce|redo|rework|update|improve)\s+(?:me\s+)?"
                           r"(?:a|an|the|my|our)?\s*(?:[\w-]+\s+){0,3}(?:pitch deck|slide deck|deck|slides|"
                           r"presentation|one[- ]pager)s?\b", re.I),
     ("investor-materials", "slides", "copywriting", "brand")),
    ("sales", re.compile(
        r"\b(prospects?|prospecting|investors?|buyers?|acquirers?|lead lists?|leads database|outreach|cold emails?|"
        r"sales pipeline|crm|vc funds?|venture capital|angel networks?|fundraising|fund raising|sales sequence)\b",
        re.I), ("prospecting", "lead-intelligence", "investor-outreach", "cold-email")),
    ("partnerships", re.compile(
        r"\b(partnerships?|partner programme|partner program|affiliates?|resellers?|integration partners?|"
        r"business development|bd plan)\b", re.I), ("investor-outreach", "copywriting")),
    ("research", re.compile(
        r"\b(market research|competitors?|competitor analysis|competitive analysis|competitive landscape|"
        r"market size|market sizing|research report|customer research|user research|due diligence)\b", re.I),
     ("deep-research", "market-research", "competitor-profiling", "customer-research")),
    ("finance", re.compile(
        r"\b(financial model|financial forecast|forecasts?|cash ?flow|p&l|profit and loss|unit economics|"
        r"revenue model|runway|burn rate|cap table|valuation)\b", re.I), ("revops", "pricing", "investor-materials")),
    ("business", re.compile(
        r"\b(business plan|business case|operating plan|pricing strategy|pricing tiers|go[- ]to[- ]market|gtm|"
        r"swot|kpis?)\b", re.I), ("market-research", "pricing", "product-lens", "investor-materials")),
    ("legal", re.compile(
        r"\b(privacy policy|terms of service|terms and conditions|t&cs|cookie policy|gdpr|dpa|contract draft|"
        r"legal (?:draft|review|pages?))\b", re.I), ()),
    ("customer_support", re.compile(
        r"\b(help cent(?:re|er)|faqs?|support macros?|support articles?|knowledge base|customer support)\b", re.I),
     ("copywriting",)),
    ("marketing", re.compile(
        r"\b(marketing plans?|launch plans?|marketing campaigns?|campaigns?|positioning|messaging|landing page copy|"
        r"seo|email sequences?|newsletters?|ad copy|social media plans?|brand strategy|growth plans?|waiting[- ]list|"
        r"wait ?list|podcasts?|podcasters?|blogs?|bloggers?|creators?|influencers?|youtubers?|communities|"
        r"subreddits?|sponsors?|sponsorships?|lead magnets?|ambassadors?|affiliate partners?|audience)\b", re.I),
     ("marketing-plan", "launch", "product-marketing", "copywriting")),
    ("content", re.compile(
        r"\b(blog posts?|articles?|content plan|content calendar|social posts?|linkedin posts?|"
        r"case stud(?:y|ies)|whitepaper|white paper|scripts?)\b", re.I),
     ("social", "article-writing", "content-strategy", "copywriting")),
]


# What JAI adds to Richard's brief on a later round: its own progress (the commands it ran, such as `python ...`)
# and Richard's sign-off. On 9 November a Sales Lead mission's second round read "python" in that progress and went
# back to the Lead Builder; only Richard's own words decide whose work it is.
_JAI_NOTES = ("PROGRESS FROM EARLIER ROUNDS", "RICHARD HAS APPROVED THE SIGN-OFF")


def richard_brief(text: str) -> str:
    """The brief as Richard wrote it, without what JAI appended to it for a later round."""
    cut = len(text or "")
    for marker in _JAI_NOTES:
        at = (text or "").find(marker)
        if at != -1:
            cut = min(cut, at)
    return (text or "")[:cut]


def _by_words(text: str) -> Optional[Tuple[str, Tuple[str, ...], str]]:
    """The specialist whose words the brief uses most (10 November: one "investor" in a growth brief beat seven
    marketing words when the first match won). A tie goes to the earlier kind of work in _KINDS (a deck to make
    before the sales words in it). Returns (specialist, skills, the words that matched)."""
    scores: Dict[str, List[str]] = {}
    order: List[str] = []
    skills_of: Dict[str, Tuple[str, ...]] = {}
    for specialist, pattern, skills in _KINDS:
        found = [m.group(0).lower() for m in pattern.finditer(text)]
        if found:
            if specialist not in scores:
                order.append(specialist)
                skills_of[specialist] = skills
            scores.setdefault(specialist, []).extend(found)
    if not scores:
        return None
    winner = max(order, key=lambda name: (len(set(scores[name])), -order.index(name)))
    return winner, skills_of[winner], ", ".join(dict.fromkeys(scores[winner]))


# A deliverable that is a document, spreadsheet or deck, not software.
_DOCUMENT = re.compile(r"[\w-]\.(xlsx|xls|csv|docx|pptx|pdf|md)\b", re.I)


# A workflow step names its specialist outright (its council decides, not the words): "Specialist: sales." first.
_NAMED = re.compile(r"^\s*Specialist:\s*([a-z_]+)\.", re.I)


def named_specialist(brief: str) -> Optional[str]:
    """The specialist a workflow step was given ("builder" for software), or None."""
    found = _NAMED.match(brief or "")
    name = found.group(1).lower() if found else None
    return name if name in _NAMED_OK else None


def specialist_for(brief: str) -> Optional[Dict[str, object]]:
    """The specialist whose work the brief is, with the skills to start from, or None for the Lead Builder:
    {"specialist": "sales", "skills": ("prospecting", ...), "matched": "investor"}."""
    text = richard_brief(brief)
    named = named_specialist(text)
    if named:
        return _route(named, "workflow", 1.0, "the workflow's council")
    if _ENGINEERING.search(text) or _BUILDER_KEEPS.search(text):
        return None
    best = _by_words(text)
    if best:
        specialist, skills, matched = best
        return {"specialist": specialist, "skills": skills, "matched": matched}
    # 10 November: a growth list for creators and podcasts matched no word above and went to the Lead Builder, with
    # its software routine and 250 steps. A document to make or change, with nothing about software in the brief, is
    # research and writing: the Research Analyst does it.
    found = _DOCUMENT.search(text)
    if found:
        return {"specialist": "research", "skills": ("deep-research", "market-research"),
                "matched": found.group(0).lower()}
    return None


# ----- two-stage routing (Richard, 10 November: take AskRich's router) ---------------------------------------------
# Stage 1 is the rules above: software words, then each specialist's words. When they find nothing, stage 2 asks a
# small, cheap model to choose, with a confidence; below CONFIDENT it falls back to the document rule. A correction
# Richard makes ("that should have been the Sales Lead") is kept and wins next time for a brief like it.

CONFIDENT = 0.6
CORRECTIONS_KEY = "routing:corrections"
CORRECTIONS_KEPT = 200
LEARNED_OVERLAP = 0.6
ROUTER_SECONDS = 8.0
# What each specialist does, for the model that chooses (and the skills it starts from).
DESCRIBED: Dict[str, str] = {
    "sales": "prospect and investor lists, buyers, contact details, outreach and introductions",
    "partnerships": "partner programmes, affiliates, resellers, business development",
    "research": "market, competitor and customer research, reports, fact-finding, tidying documents",
    "finance": "financial models, forecasts, unit economics, pricing maths",
    "business": "business plans, pricing strategy, go-to-market, KPIs",
    "legal": "privacy policies, terms, contracts and other legal drafts",
    "customer_support": "help centre, FAQs, support replies",
    "marketing": "growth, waiting lists, newsletters, podcasts, creators, communities, campaigns, launch plans",
    "content": "decks, posts, articles, scripts and other writing",
    "builder": ("software: code, apps, websites, building or continuing a product from its specification or phases "
                "(MYCO), builds, tests, deployment, and video or animation"),
}
_NAMED_OK = frozenset(DESCRIBED)
_STARTING_SKILLS: Dict[str, Tuple[str, ...]] = {}
for _name, _pattern, _skills in _KINDS:
    _STARTING_SKILLS.setdefault(_name, _skills)


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower())}


def _overlap(a: str, b: str) -> float:
    x, y = _words(a), _words(b)
    return len(x & y) / max(1, min(len(x), len(y))) if x and y else 0.0


def _route(specialist: Optional[str], source: str, confidence: float, matched: str) -> Optional[Dict[str, object]]:
    if not specialist or specialist == "builder":
        return None
    return {"specialist": specialist, "skills": _STARTING_SKILLS.get(specialist, ()), "matched": matched,
            "source": source, "confidence": round(confidence, 2)}


async def _redis():
    from app.core.redis import get_redis

    return await get_redis()


async def corrections() -> List[Dict[str, str]]:
    import json

    try:
        rows = await (await _redis()).lrange(CORRECTIONS_KEY, 0, CORRECTIONS_KEPT - 1)
        return [json.loads(r) for r in rows]
    except Exception:  # noqa: BLE001 - routing works without what was learned
        return []


async def learn(brief: str, specialist: str) -> None:
    """Richard's correction: briefs like this one are this specialist's work ("builder" for software)."""
    import json

    if specialist not in DESCRIBED:
        raise ValueError(f"unknown specialist {specialist!r}")
    redis = await _redis()
    await redis.lpush(CORRECTIONS_KEY, json.dumps({"brief": richard_brief(brief)[:2000], "specialist": specialist}))
    await redis.ltrim(CORRECTIONS_KEY, 0, CORRECTIONS_KEPT - 1)


async def _ask_model(text: str) -> Optional[Dict[str, object]]:
    """Stage 2: a small model chooses the specialist, with a confidence from 0 to 1."""
    import asyncio
    import json

    from app.core.config import settings
    from app.core.providers.base import CompletionRequest, Message
    from app.core.providers.router import get_router

    if getattr(settings, "TESTING", False):
        return None  # tests never spend provider credit; they stand a model in for this function
    options = "\n".join(f"- {name}: {what}" for name, what in DESCRIBED.items())
    prompt = (f"Which of JAI's specialists should do this piece of work?\n{options}\n\nThe brief:\n{text[:4000]}\n\n"
              'Answer with JSON only: {"specialist": "<one name from the list>", "confidence": <0 to 1>, '
              '"why": "<a few words>"}')
    model = str(getattr(settings, "ROUTER_MODEL", "") or "claude-haiku-5-5")
    response = await asyncio.wait_for(get_router().complete(CompletionRequest(
        model=model, messages=[Message(role="user", content=prompt)], temperature=0.0, max_tokens=120)),
        timeout=ROUTER_SECONDS)
    found = re.search(r"\{.*\}", response.content or "", re.S)
    if not found:
        return None
    answer = json.loads(found.group(0))
    name = str(answer.get("specialist") or "").strip().lower()
    if name not in DESCRIBED:
        return None
    return {"specialist": name, "confidence": float(answer.get("confidence") or 0), "why": str(answer.get("why") or "")}


async def classify(brief: str) -> Dict[str, object]:
    """Who does this brief: {"route": specialist_for's answer or None (the Lead Builder), "source": rules, keywords,
    learned, model or document, "confidence", "matched"}."""
    text = richard_brief(brief)
    named = named_specialist(text)
    if named:
        return {"route": _route(named, "workflow", 1.0, "the workflow's council"), "source": "workflow",
                "confidence": 1.0, "matched": "the workflow's council"}
    hit = _ENGINEERING.search(text) or _BUILDER_KEEPS.search(text)
    if hit:
        return {"route": None, "source": "rules", "confidence": 1.0, "matched": hit.group(0).lower()}
    # Richard's correction of a brief like this one wins over the word lists.
    best = max(((_overlap(text, c.get("brief", "")), c) for c in await corrections()), default=(0.0, None),
               key=lambda pair: pair[0])
    if best[1] is not None and best[0] >= LEARNED_OVERLAP:
        name = str(best[1].get("specialist"))
        return {"route": _route(name, "learned", best[0], "your earlier correction"), "source": "learned",
                "confidence": round(best[0], 2), "matched": "your earlier correction"}
    words = _by_words(text)
    if words:
        specialist, skills, matched = words
        return {"route": _route(specialist, "keywords", 1.0, matched), "source": "keywords",
                "confidence": 1.0, "matched": matched}
    try:
        chosen = await _ask_model(text)
    except Exception:  # noqa: BLE001 - the model is a second opinion; the rules still decide without it
        chosen = None
    if chosen and chosen["confidence"] >= CONFIDENT:
        why = str(chosen.get("why") or "the model's choice")
        return {"route": _route(str(chosen["specialist"]), "model", float(chosen["confidence"]), why),
                "source": "model", "confidence": round(float(chosen["confidence"]), 2), "matched": why}
    route = specialist_for(text)  # the document rule, or the Lead Builder
    return {"route": route, "source": "document" if route else "default",
            "confidence": round(float(chosen["confidence"]), 2) if chosen else 0.0,
            "matched": route["matched"] if route else ""}


def first_skills(specialist: str, wanted: Tuple[str, ...]) -> List[str]:
    """The named skills that are really in front of this specialist in the sandbox (installed, not blocked)."""
    from app.core.knowledge.skill_packs import sandbox_skills

    offered = {path.rsplit("/", 1)[-1]: path for path in sandbox_skills(specialist)}
    return [name for name in wanted if name in offered]
