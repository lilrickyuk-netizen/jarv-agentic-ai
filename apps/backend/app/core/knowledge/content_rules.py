"""
JAI Backend - Content is researched before it is made, and follows its product's playbook

22 November. Richard on a quote video made from four stills and a cliché: "absolutely terrible for the cost and the
time... I can make better than that myself in 10 minutes for free". His rules: "it must search competitors first",
"it must not use generic content quotes and stories", and JAI finds the competitors itself from what the product
is. So every content mission (a video, a carousel, a script, a post) gets:

1. research_rule: the niche's outliers first, with the free research skills (skill_packs: video-agent-skills'
   studio-script viral research and steal, social-media-skills' competitor-analysis and viral-reverse-engineering),
   YouTube read with yt-dlp in the sandbox, no account and no paid service. The findings are saved in the mission's
   folder (.jai/research/), so the piece names the outliers it adapts and the next mission starts from the
   watchlist instead of from nothing.
2. playbook_for: the product's standing content rules (playbooks/<product>.md), written with Richard, when the
   mission is for that product.
3. content_check: what the independent checker of the piece judges on top of the craft: the research exists and
   the piece traces back to it, and the playbook's rules hold.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

PLAYBOOK_DIR = Path(__file__).resolve().parent / "playbooks"
# A product's playbook applies when the mission or its workspace folder names the product.
PLAYBOOKS = {"plexecute": "plexecute.md"}
RESEARCH_DIR = ".jai/research"
WATCHLIST = f"{RESEARCH_DIR}/watchlist.md"
# A creator's video is an outlier when it beat that creator's own median by this much.
OUTLIER_SCORE = 3
# Only a brief that asks for an ad gets one; everything else is organic, with no call to action.
_AD = re.compile(r"\b(?:ad|ads|advert|adverts|advertisement|advertisements|ad films?|paid ads?)\b", re.IGNORECASE)
_NOT_AD = re.compile(r"\b(?:not|no|never|isn'?t|without)\s+(?:an?\s+)?(?:ad|ads|advert)\b", re.IGNORECASE)


def is_ad(mission: str) -> bool:
    text = mission or ""
    return bool(_AD.search(text)) and not _NOT_AD.search(text)


def product_of(mission: str, workspace_root: Optional[str] = None) -> Optional[str]:
    """The product whose playbook applies, from the mission's words or its workspace folder's name."""
    haystack = f"{mission or ''} {workspace_root or ''}".lower()
    return next((name for name in PLAYBOOKS if name in haystack), None)


def playbook_for(mission: str, workspace_root: Optional[str] = None) -> str:
    """The product's playbook as a brief section, or "" when the mission is for no product with one."""
    name = product_of(mission, workspace_root)
    if name is None:
        return ""
    try:
        text = (PLAYBOOK_DIR / PLAYBOOKS[name]).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    ad = (" This brief asks for an ad, so the playbook's ad exception applies: one clear call to action."
          if is_ad(mission) else
          " This brief is organic content: no call to action, no waiting list, no link and no end card, even where "
          "a skill's own template has one.")
    return (f"\n\nTHE PRODUCT'S CONTENT PLAYBOOK (Richard's standing rules; the brief can add to them, never "
            f"loosen them):{ad}\n\n{text}\n")


def research_rule(mission: str = "", container_root: Optional[Path] = None) -> str:
    """Research before creating: find the niche's outliers, save them, and build the piece from them."""
    watch = container_root / WATCHLIST if container_root is not None else None
    start = (f" Start from {WATCHLIST}, the competitor accounts earlier missions found: refresh their latest videos "
             "and add any new account that keeps appearing, never deleting one."
             if watch is not None and watch.is_file() else
             f" No watchlist exists yet: find the accounts yourself from what the product is and what the brief is "
             f"about, and save them to {WATCHLIST} (handle, link, why it is in the niche) for the missions after this "
             "one.")
    return (
        " RESEARCH BEFORE YOU CREATE, every time: nothing is made from a stock quote, a stock story or a cliché."
        " Invoke the studio-script skill and do its viral research (references/viral-research.md) on YouTube with "
        "yt-dlp, which is free and needs no account: search the brief's theme and the product's topics "
        "(`yt-dlp --flat-playlist --print \"%(channel_url)s\t%(channel)s\" \"ytsearch30:<theme> shorts\"`), keep "
        "the channels that keep appearing, list each one's last 30 Shorts with their view counts, and score every "
        "video against that channel's own median. Skip its Treg route for TikTok and Instagram: that is a paid "
        "service JAI does not use. Use the competitor-analysis and viral-reverse-engineering skills to say why each "
        f"outlier works (hook, structure, pacing, format)." + start +
        f" Write {RESEARCH_DIR}/<today>-<topic>.md: each outlier (a score of {OUTLIER_SCORE} or more) with its link, "
        "channel, views, the channel's median, its score, its first 3 seconds word for word and why it works, then "
        "which outliers this piece adapts and what it takes from each. To match an outlier's pacing and look, use "
        f"the steal skill (yt-dlp and ffmpeg); anything you download of another creator's stays in {RESEARCH_DIR}/ "
        "for measuring and never goes into the piece. Then make the piece from that file: keep the outliers' hook "
        "shape, structure and pacing, and change the topic, the words and the visuals. Never copy a line, a clip or "
        "a frame. When the brief gives the story, that is the story: the research decides how it is told. If "
        "YouTube cannot be reached, say so in the research file and in your report, and work from the watchlist's "
        "saved findings; never invent an outlier or a view count.")


def content_check(mission: str = "", workspace_root: Optional[str] = None) -> str:
    """What the independent checker of a content piece judges besides the craft."""
    organic = "" if is_ad(mission) else (
        " It is organic content, so a call to action, a waiting list, a link or an end card anywhere in it is "
        "unmet.")
    playbook = (" Judge each rule of the product's content playbook (below) against what you see and hear: a "
                "robotic text-to-speech voice, music, a stock motivational quote or story, or a health or money "
                "claim without a named source is unmet." + playbook_for(mission, workspace_root)
                if product_of(mission, workspace_root) else "")
    return (f" Open the newest research file in {RESEARCH_DIR}/: it must list real outliers (each with its link, "
            "views, the channel's median and its score) and say which ones the piece adapts. Missing research, or a "
            "piece whose hook and structure do not trace back to the outliers it names, is unmet." + organic
            + playbook)
