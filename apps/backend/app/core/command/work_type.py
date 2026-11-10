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


# A deliverable that is a document, spreadsheet or deck, not software.
_DOCUMENT = re.compile(r"[\w-]\.(xlsx|xls|csv|docx|pptx|pdf|md)\b", re.I)


def specialist_for(brief: str) -> Optional[Dict[str, object]]:
    """The specialist whose work the brief is, with the skills to start from, or None for the Lead Builder:
    {"specialist": "sales", "skills": ("prospecting", ...), "matched": "investor"}."""
    text = richard_brief(brief)
    if _ENGINEERING.search(text) or _BUILDER_KEEPS.search(text):
        return None
    for specialist, pattern, skills in _KINDS:
        found = pattern.search(text)
        if found:
            return {"specialist": specialist, "skills": skills, "matched": found.group(0).lower()}
    # 10 November: a growth list for creators and podcasts matched no word above and went to the Lead Builder, with
    # its software routine and 250 steps. A document to make or change, with nothing about software in the brief, is
    # research and writing: the Research Analyst does it.
    found = _DOCUMENT.search(text)
    if found:
        return {"specialist": "research", "skills": ("deep-research", "market-research"),
                "matched": found.group(0).lower()}
    return None


def first_skills(specialist: str, wanted: Tuple[str, ...]) -> List[str]:
    """The named skills that are really in front of this specialist in the sandbox (installed, not blocked)."""
    from app.core.knowledge.skill_packs import sandbox_skills

    offered = {path.rsplit("/", 1)[-1]: path for path in sandbox_skills(specialist)}
    return [name for name in wanted if name in offered]
