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
4. used_facts_rule (24 November, audit batch 2): every fact, statistic, quote, study, story or named example is used
   once per product. The folder's .jai/used-facts.md lists what earlier pieces used, with the playbook's own "Facts
   already used"; the piece is made without any of them and adds its own. On 23 November every video reused the same
   Ed Sheeran "53%" fact, saved in a research note, because nothing checked it.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

PLAYBOOK_DIR = Path(__file__).resolve().parent / "playbooks"
# A product's playbook applies when the mission or its workspace folder names the product.
PLAYBOOKS = {"plexecute": "plexecute.md"}
RESEARCH_DIR = ".jai/research"
# What earlier pieces for this product used (one line each), in the mission's folder.
USED_FACTS = ".jai/used-facts.md"
# The playbook's own list of facts that are used up (Richard's), read with the folder's list.
PLAYBOOK_USED = "## Facts already used"
USED_FACTS_SHOWN = 80
WATCHLIST = f"{RESEARCH_DIR}/watchlist.md"
# A creator's video is an outlier when it beat that creator's own median by this much.
OUTLIER_SCORE = 3
# OpenMontage's own skill for a video given as a reference ("make me something like this").
STUDIO_REFERENCE_SKILL = "skills/meta/video-reference-analyst.md"
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


# 23 November, Richard: research only when he asks for it. JAI's own research also ran on top of OpenMontage's, so
# an edit spent 25 of its 46 minutes researching twice before it reached the clip.
_ASKS_RESEARCH = re.compile(r"\bresearch", re.IGNORECASE)
_NO_RESEARCH = re.compile(r"\b(no|without|skip|don'?t)\s+research", re.IGNORECASE)


def asks_research(mission: str) -> bool:
    text = mission or ""
    return bool(_ASKS_RESEARCH.search(text)) and not _NO_RESEARCH.search(text)


def studio_research(mission: str) -> str:
    """OpenMontage researches with its own tools, and only when the brief asks; JAI adds no research of its own."""
    if asks_research(mission):
        return (" The brief asks for research: do it once, with OpenMontage's own research tools and skills, and "
                "keep it to what this video needs.")
    return " No research: the brief and its reference are the starting point."


def research_rule(mission: str = "", container_root: Optional[Path] = None, studio: bool = False) -> str:
    """Research before creating: find the niche's outliers, save them, and build the piece from them. In OpenMontage
    (studio) the outliers become the references its own pipeline starts from: its video-reference-analyst and
    research director do the rest, so no second scriptwriting method competes with its stages."""
    watch = container_root / WATCHLIST if container_root is not None else None
    start = (f" Start from {WATCHLIST}, the competitor accounts earlier missions found: refresh their latest videos "
             "and add any new account that keeps appearing, never deleting one."
             if watch is not None and watch.is_file() else
             f" No watchlist exists yet: find the accounts yourself from what the product is and what the brief is "
             f"about, and save them to {WATCHLIST} (handle, link, why it is in the niche) for the missions after this "
             "one.")
    find = (
        " RESEARCH BEFORE YOU CREATE, every time: nothing is made from a stock quote, a stock story or a cliché."
        " First find what is over-performing in this niche, the way the studio-script skill's viral research "
        "(references/viral-research.md) does it, on YouTube with yt-dlp, which is free and needs no account: search "
        "the brief's theme and the product's topics "
        "(`yt-dlp --flat-playlist --print \"%(channel_url)s\t%(channel)s\" \"ytsearch30:<theme> shorts\"`), keep "
        "the channels that keep appearing, list each one's last 30 Shorts with their view counts, and score every "
        "video against that channel's own median. Skip its Treg route for TikTok and Instagram: that is a paid "
        "service JAI does not use." + start +
        f" Write {RESEARCH_DIR}/<today>-<topic>.md: each outlier (a score of {OUTLIER_SCORE} or more) with its link, "
        "channel, views, the channel's median and its score, then which outliers this piece adapts and why.")
    if studio:
        make = (
            f" Then give OpenMontage the one or two strongest outliers that fit this brief as its reference videos "
            f"(their YouTube links): follow its own {STUDIO_REFERENCE_SKILL} so its video_analyzer opens each link "
            "(yt-dlp is installed in its environment) and writes the VideoAnalysisBrief, and its research director "
            "starts from that brief, as its pipeline describes, and makes ours different. When Richard's brief names "
            "a reference video of its own, that one leads and the outliers support it. Add to the research file what "
            "OpenMontage took from each reference. Its music plan: no music unless the brief asks for music; sound "
            "design or silence instead. Keep the references' hook shape, structure and pacing, and change the topic, "
            "the words and the visuals. Never copy a line, a clip or a frame, and nothing downloaded of another "
            "creator's goes into the video.")
    else:
        make = (
            " Use the competitor-analysis and viral-reverse-engineering skills to say why each outlier works (hook, "
            "structure, pacing, format) and put its first 3 seconds, word for word, in the research file. To match "
            "an outlier's pacing and look, use the steal skill (yt-dlp and ffmpeg); anything you download of another "
            f"creator's stays in {RESEARCH_DIR}/ for measuring and never goes into the piece. Then make the piece "
            "from that file: keep the outliers' hook shape, structure and pacing, and change the topic, the words and "
            "the visuals. Never copy a line, a clip or a frame.")
    return (find + make + " When the brief gives the story, that is the story: the research decides how it is "
            "told. If YouTube cannot be reached, say so in the research file and in your report, and work from the "
            "watchlist's saved findings; never invent an outlier or a view count.")


def voice_rule(studio: bool = False, root: Optional[Path] = None) -> str:
    """The narration: a natural human voice from JAI's voice library, chosen for the piece, or no voice at all."""
    from app.core.creative import voice_library

    listed = voice_library.describe(root)
    if not listed:
        return (" VOICE: JAI's voice library is not built on this computer, so this piece has no voice: tell it with "
                "on-screen text and sound. Never a text-to-speech voice (Kokoro, Piper, `npx hyperframes tts`).")
    where = (" In OpenMontage, make each narration section with make_voiceover into the project's "
             "assets/narration/ folder instead of its tts_selector, record make_voiceover (Chatterbox Turbo) and the "
             "voice as each narration asset's source_tool, and run its own sample, timing and flat-voice checks on "
             "them." if studio else "")
    return (" VOICE: a natural human voice or none. When the piece is narrated, use JAI's make_voiceover tool with "
            "one voice from JAI's voice library, chosen to fit this piece and the references it adapts (gender, "
            "pace and energy), and a different voice from the last pieces when another fits as well: " + listed
            + ". Write the narration the way that person would say it, with [chuckle] or [laugh] only where "
            "a real person would. Never Kokoro, Piper, `npx hyperframes tts` or another text-to-speech voice in a "
            "finished piece: they sound robotic." + where + " Check the first section (its length and loudness "
            "with ffmpeg, and the words against the script) before making the rest, and say in the research file "
            "which voice was chosen and why.")


def _playbook_used(mission: str, workspace_root: Optional[str]) -> List[str]:
    name = product_of(mission, workspace_root)
    if name is None:
        return []
    try:
        text = (PLAYBOOK_DIR / PLAYBOOKS[name]).read_text(encoding="utf-8")
    except OSError:
        return []
    if PLAYBOOK_USED not in text:
        return []
    section = text.split(PLAYBOOK_USED, 1)[1].split("\n## ", 1)[0]
    return [line.strip() for line in section.splitlines() if line.strip().startswith("- ")]


def used_facts(container_root: Optional[Path], mission: str = "", workspace_root: Optional[str] = None) -> List[str]:
    """The facts already used for this product: the playbook's, then the folder's list, newest last."""
    found = _playbook_used(mission, workspace_root)
    path = container_root / USED_FACTS if container_root is not None else None
    try:
        if path is not None and path.is_file():
            found += [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                      if line.strip().startswith("- ")]
    except OSError:
        pass
    return list(dict.fromkeys(found))


def used_facts_rule(container_root: Optional[Path], mission: str = "", workspace_root: Optional[str] = None) -> str:
    """Every content mission: never reuse a fact, and record the ones this piece uses."""
    listed = used_facts(container_root, mission, workspace_root)
    shown = listed[-USED_FACTS_SHOWN:]
    already = (" These are used already; use none of them again, in any wording or framing:\n" + "\n".join(shown)
               + "\n" if shown else f" None is recorded yet ({USED_FACTS} does not exist in this folder).")
    return (" USED FACTS: each fact, statistic, quote, study, story and named example is used in one piece only."
            + already + f" Before you finish, add every one this piece uses to {USED_FACTS} in the mission's folder, "
            "one line each: `- <the fact in a few words> (<its source>; <the piece's file>; <today's date>)`, "
            "creating the file when it is missing and never changing or deleting a line already there.")


def content_check(mission: str = "", workspace_root: Optional[str] = None) -> str:
    """What the independent checker of a content piece judges besides the craft."""
    organic = "" if is_ad(mission) else (
        " It is organic content, so a call to action, a waiting list, a link or an end card anywhere in it is "
        "unmet.")
    playbook = (" Judge each rule of the product's content playbook (below) against what you see and hear: a "
                "robotic text-to-speech voice, music, a stock motivational quote or story, or a health or money "
                "claim without a named source is unmet." + playbook_for(mission, workspace_root)
                if product_of(mission, workspace_root) else "")
    research = (f" Open the newest research file in {RESEARCH_DIR}/: it must list real outliers (each with its "
                "link, views, the channel's median and its score) and say which ones the piece adapts. Missing "
                "research, or a piece whose hook and structure do not trace back to the outliers it names, is unmet."
                if asks_research(mission) else "")
    used = (f" A fact, statistic, quote, study, story or named example already on the used-facts list ({USED_FACTS} "
            "and the playbook's Facts already used) is unmet, and so is one the piece uses that the list does not "
            "now record.")
    return (research + used + " A narrated piece "
            "must be narrated with make_voiceover in a voice from JAI's voice library (ASSET_LICENCES.md names the "
            "voice); any other text-to-speech voice, or narration with no voice named there, is unmet."
            + organic
            + playbook)
