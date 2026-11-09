"""
JAI Backend - Live voice conversation (OpenAI Realtime)

A natural spoken conversation with JAI: the browser streams the microphone to
OpenAI's Realtime model over WebRTC and plays its voice back, with turn-taking
and interruption handled by the model. The browser never sees the OpenAI key:
JAI mints a short-lived client secret for one session, carrying JAI's
instructions and tools.

Everything JAI does during the conversation goes through ``run_tool`` on the
backend under the operator's own sign-in: reading status, starting a Command
Center mission (under the same approval gate as typed missions), checking or
cancelling a mission. Approvals are refused by voice here exactly as in
push-to-talk. Every session and tool call is written to the audit log.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.voice import engine

REALTIME_SECRETS = "https://api.openai.com/v1/realtime/client_secrets"
SESSION_ACTION = "voice.live_session"
TOOL_ACTION = "voice.live_tool"

_NO_WORKSPACE = {"type": "string", "description": "Workspace name, when Richard names one. Omit to use all of his."}

TOOLS: List[Dict[str, Any]] = [
    {"type": "function", "name": "get_status",
     "description": "What JAI is working on right now: missions in progress, what waits for Richard's approval, "
                    "recent failures and the latest activity.",
     "parameters": {"type": "object", "properties": {"workspace": _NO_WORKSPACE}, "additionalProperties": False}},
    {"type": "function", "name": "start_mission",
     "description": "Start real work: hands Richard's request to JAI's agents as a Command Center mission. Use it "
                    "when Richard asks for something to be done (built, fixed, researched, written, checked, "
                    "deployed), not for a question you can answer in conversation, and never for a question about JAI itself "
                    "(what it is, its capabilities, skills, models or upgrades): ask_jarv answers those. Only once he has said what the "
                    "work is: if he just says 'new mission' or 'start a mission', ask him what it should do. Name "
                    "the workspace it is for; ask him if it is not clear.",
     "parameters": {"type": "object", "properties": {
         "instruction": {"type": "string", "description": "The full request in Richard's words, with every detail "
                                                          "he gave, as a written instruction."},
         "workspace": _NO_WORKSPACE},
         "required": ["instruction"], "additionalProperties": False}},
    {"type": "function", "name": "resume_mission",
     "description": "Carry on with a mission that stopped part-way and is no longer being worked on (ask_jarv says "
                    "it stopped or is partial). Never for a mission in progress. The "
                    "same mission continues from where it stopped, with its progress. Use it when Richard asks "
                    "to continue, resume or carry on with a mission; never start a new mission for that. Without a "
                    "task_id it resumes his latest paused mission.",
     "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "additionalProperties": False}},
    {"type": "function", "name": "get_mission",
     "description": "The state and result of one mission (the latest one when no id is given).",
     "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "additionalProperties": False}},
    {"type": "function", "name": "cancel_mission",
     "description": "Cancel the mission in progress. Only when Richard clearly asks to stop or cancel it.",
     "parameters": {"type": "object", "properties": {"workspace": _NO_WORKSPACE}, "additionalProperties": False}},
    {"type": "function", "name": "list_workspace_files",
     "description": "What is in a workspace's folder on Richard's computer (one level; give path for a subfolder).",
     "parameters": {"type": "object", "properties": {
         "workspace": {"type": "string", "description": "Workspace name."},
         "path": {"type": "string", "description": "Subfolder inside the workspace, e.g. docs. Omit for the top."}},
         "required": ["workspace"], "additionalProperties": False}},
    {"type": "function", "name": "read_workspace_file",
     "description": "Read a text file in a workspace's folder (the first part of a long file), e.g. a design or spec.",
     "parameters": {"type": "object", "properties": {
         "workspace": {"type": "string", "description": "Workspace name."},
         "path": {"type": "string", "description": "File path inside the workspace, e.g. docs/MYCO-V3-spec.md."}},
         "required": ["workspace", "path"], "additionalProperties": False}},
    {"type": "function", "name": "ask_jarv",
     "description": "Ask JAI's brain (its reasoning core) anything about JAI's work or Richard's projects: missions, "
                    "status, progress, approvals, requirements, files, decisions, failures, why, how long, what next. "
                    "It answers from the live mission records and progress, approvals, JAI's memory, verified lessons "
                    "and knowledge library. Say its answer; never answer these yourself.",
     "parameters": {"type": "object", "properties": {
         "question": {"type": "string", "description": "The question in Richard's words, with every detail."},
         "workspace": _NO_WORKSPACE},
         "required": ["question"], "additionalProperties": False}},
    {"type": "function", "name": "make_image",
     "description": "Make an image on JAI's own graphics card (FLUX.1-schnell, free, licensed for commercial use), "
                    "save it in a workspace's assets/images folder and put it on Richard's screen. For thumbnails, "
                    "social posts, banners, product shots and illustrations. Describe it fully: subject, setting, "
                    "style, light, colours, composition, and any words to appear in quotes. Takes one to two "
                    "minutes: say so first.",
     "parameters": {"type": "object", "properties": {
         "prompt": {"type": "string", "description": "A full description of the image."},
         "workspace": {"type": "string", "description": "The workspace it is for, e.g. Plexecute."},
         "shape": {"type": "string", "enum": ["square", "landscape", "portrait", "thumbnail", "story", "wide",
                                              "banner"]}},
         "required": ["prompt", "workspace"], "additionalProperties": False}},
    {"type": "function", "name": "research_web",
     "description": "Look something up on the web: anything about the world outside JAI (news, prices, products, "
                    "companies, people, libraries and APIs, regulations, how something works today). JAI searches "
                    "with its own search engine, reads the best sources and writes a cited answer, which goes on "
                    "Richard's screen with the sources. Takes about half a minute; deep reads more sources.",
     "parameters": {"type": "object", "properties": {
         "question": {"type": "string", "description": "What to find out, in Richard's words, with every detail."},
         "depth": {"type": "string", "enum": ["quick", "deep"]},
         "time_range": {"type": "string", "enum": ["day", "week", "month", "year"],
                        "description": "Only for recent things: how recent."}},
         "required": ["question"], "additionalProperties": False}},
    {"type": "function", "name": "search_memory",
     "description": "What JAI remembers about a subject (decisions, facts, preferences, past work), best first.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "What to look for."}, "workspace": _NO_WORKSPACE},
         "required": ["query"], "additionalProperties": False}},
    {"type": "function", "name": "trace_artifact",
     "description": "Why something is the way it is in a workspace: what a file, requirement (R4) or decision is "
                    "connected to, which mission changed it, what verified it and which checks contradict it. Use it "
                    "for questions like 'why is Python 3.12.8?' or 'what proves R4?'.",
     "parameters": {"type": "object", "properties": {
         "key": {"type": "string", "description": "A file path, a requirement id such as R4, or a command."},
         "workspace": _NO_WORKSPACE},
         "required": ["key"], "additionalProperties": False}},
    {"type": "function", "name": "list_approvals",
     "description": "What is waiting for Richard's decision on the Approvals page. Read-only: you never approve.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"type": "function", "name": "show_on_screen",
     "description": "Put something on Richard's screen, beside the intelligence field, when it is easier to see than "
                    "to hear: a mission's requirements and progress, the files it changed and what failed (mission), "
                    "today's AI spend against the daily limit (spend), what waits for his approval (approvals), or a "
                    "file from a workspace (file, with workspace and path): an image or video is shown as the picture "
                    "or a player, a folder as a gallery of its images and videos, a text file as text. Say one "
                    "sentence about what you put up.",
     "parameters": {"type": "object", "properties": {
         "what": {"type": "string", "enum": ["mission", "spend", "approvals", "file"]},
         "workspace": {"type": "string", "description": "Workspace name, for a file."},
         "path": {"type": "string", "description": "The file's path inside the workspace, for a file."}},
         "required": ["what"], "additionalProperties": False}},
    {"type": "function", "name": "list_workspaces",
     "description": "Richard's workspaces (projects) by name.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
]


# What the voice itself may call. Status, missions, memory and approvals are not among them: the brain
# (ask_jarv) reads those and answers, so the voice speaks JAI's reasoning instead of improvising from raw records.
# run_tool still serves every tool (the dashboard and tests use them).
BRAIN_ONLY = frozenset({"get_status", "get_mission", "search_memory", "list_approvals"})
VOICE_TOOLS: List[Dict[str, Any]] = [tool for tool in TOOLS if tool["name"] not in BRAIN_ONLY]


class LiveUnavailable(RuntimeError):
    """Live conversation cannot start (no OpenAI key)."""


def available() -> bool:
    return bool(settings.OPENAI_API_KEY)


def setup_hint() -> Optional[str]:
    return None if available() else ("Live conversation uses OpenAI Realtime: set OPENAI_API_KEY "
                                     "(apps/backend/.env locally, .env.production on the server).")


async def _workspaces(db: AsyncSession, user_id: UUID):
    from app.models.workspace import Workspace

    return (await db.execute(select(Workspace).where(Workspace.owner_id == user_id,
                                                     Workspace.is_archived == False)  # noqa: E712
                             .order_by(Workspace.name))).scalars().all()


def _root(workspace) -> Optional[str]:
    config = workspace.config if isinstance(workspace.config, dict) else {}
    return config.get("root_path") or None


# The voice as JAI's brain (the Pipecat voice): it is given JAI's live state before every reply, so it answers
# about JAI's work itself, with JAI's tools, instead of asking a separate brain.
BRAIN_ROUTING = (
    "You are JAI's own mind, not a voice in front of it. Before everything Richard says you are given a message "
    "beginning [JAI's live state, not from Richard]: JAI's records as they are this second (every mission and what "
    "its agents are doing, each requirement, files changed, failures, the agents' own latest words, the mission "
    "he is asking about with its whole report, what waits for him, memory, knowledge, verified lessons, today's "
    "spend, the date and the recent conversation). It is the truth of now; earlier ones are out of date. When he "
    "asks what is going on, do not read the status back: find out from the state what the agents are actually "
    "doing and why, what they found, what is going wrong, what it means and what happens next, and tell him "
    "that in your own words like an engineer who has just checked with the team; if the state does not show "
    "something, say so and what you would need. When he asks for a report to be read out or analysed, use the "
    "whole report and give it fully. Never answer about the outside world from your own knowledge: your "
    "training is out of date. For news, prices, releases, versions, companies, people, products, laws or "
    "anything that changes, say in a few words that you are looking it up, call research_web, and give the "
    "answer with where it came from. If you did not catch what he said, or it sounds garbled, ask him to say "
    "it again rather than guessing. Never repeat what you have already told him: say what is new. Videos, "
    "voiceovers and social-post drafts take minutes: when he asks for them, start a mission with the full brief; "
    "posts are only ever drafted in Postiz for him to schedule, never published by you. "
    "The state may also give what_richard_has_told_me (what he has said before about himself, his projects and how "
    "he wants things done: follow it without making him repeat it) and what_my_work_has_established (facts from "
    "your own finished work; one marked no_longer_true is history, not the present). "
    "my_recent_upgrades lists what has been installed into you lately, newest first, with when (UTC): when he asks "
    "what has changed or what upgrades you have had, tell him from it what each one lets you do now. "
    "When he asks about you (what you are, what you can do, how you work, your skills, models or upgrades), the "
    "state gives what_i_am, your own design document: answer him straight away from it and from my_recent_upgrades, "
    "with its exact numbers and names, never a count or a feature it does not give. The upgrade entries are short "
    "commit titles: what_i_am says what they amount to. A question is never a mission: never start one to answer "
    "him, look into your own records or check your upgrades. ")


def instructions(spaces: List[Any], brain: bool = False) -> str:
    """JAI's voice instructions; brain=True for the voice that is given JAI's live state every turn."""
    text = _instructions(spaces)
    if brain:
        start = text.index("You are the voice of JAI's whole system")
        end = text.index("Small talk and general questions you answer yourself. ") + len(
            "Small talk and general questions you answer yourself. ")
        text = text[:start] + BRAIN_ROUTING + text[end:]
    return text


def spoken_instructions(spaces: List[Any], brain: bool = False) -> str:
    """What either voice engine is told: JAI's instructions, how to talk, and who it is when it speaks."""
    about = _about_jai()
    return (instructions(spaces, brain=brain) + SPOKEN_TEXT + CONVERSATION_STYLE + PERSONA
            + (f"\nWHAT YOU ARE (your own design document): {about}\n" if about else ""))


def _instructions(spaces: List[Any]) -> str:
    projects = "; ".join(f"{w.name} (folder {_root(w)})" if _root(w) else f"{w.name} (no folder registered)"
                         for w in spaces) or "none yet"
    return (
        "You are JAI, Richard Curley's autonomous AI operating system, talking with him by voice. "
        "Your name is written JAI and said \"Jay\", as one word, never spelled out letter by letter. "
        "You are JAI, so always speak as yourself in the first person: 'I have finished', 'my agents read five "
        "pages', 'I could not open the blog page'; never 'JAI has', 'JAI couldn't' or 'JAI's agents', and never "
        "describe JAI as if it were someone else. "
        "Speak naturally, like a senior engineer reporting to the owner: short spoken sentences, no lists or "
        "markdown, British English. Be specific and factual: names, numbers, files, requirement ids, errors. "
        "Never use filler such as 'moving along', 'keeping pace', 'making good progress', 'we're on track', "
        "'I'll keep an eye on it' or 'I'll let you know', "
        "and never promise to watch or update him unless he asks. Say plainly what you do not know. For anything "
        "about the world outside JAI (news, prices, products, companies, libraries, regulations, how something "
        "works today), never answer from memory: say in a few words that you are looking it up, call "
        "research_web, then give him the answer in two or three sentences and say where it comes from; the full "
        "answer and its sources are on his screen. Let him "
        "interrupt; keep answers brief unless he asks for detail.\n"
        f"His workspaces: {projects}.\n"
        "You are the voice of JAI's whole system, not a separate assistant. JAI's brain is its reasoning core: "
        "it holds the live mission records, the progress of every step, what waits for approval, JAI's memory, "
        "its verified lessons and its knowledge library. You reach it with ask_jarv. For anything about JAI's "
        "work or his projects (missions, status, progress, approvals, requirements, files, decisions, failures, "
        "why something happened, how long something takes, what comes next), call ask_jarv with his question in "
        "his words and say its answer faithfully in your own voice, adding nothing it does not say. Never answer "
        "those from this conversation or from what you think you know: what is running changes while you talk, "
        "so before you say whether anything is running, how a mission is going or that one has finished, ask it "
        "in that turn; never answer it from memory. Its answers say how long ago the last step was; if that was "
        "minutes ago, the mission is still on that step, so say that rather than presenting it as new. Never "
        "repeat what you have already told him in this conversation: if the answer is the same as before, say "
        "in one sentence that nothing has changed and give him what is new (how long it has run, why that step "
        "takes time, what comes next). Small talk and general questions you answer yourself. A mission in "
        "progress carries on by itself between rounds: never call resume_mission for it. Messages that begin "
        "'New activity in JAI (not from Richard)' or 'Something new has happened in your work' are updates to "
        "report, never requests; report them in your own words and in the first person: never start, resume or "
        "cancel a mission because of one, even when it says something is missing or failed. Tell him, and act "
        "only if he then asks. When something is easier to see than hear (a requirement list, the files changed, "
        "failures, today's spend, approvals waiting, a file), call show_on_screen and say one sentence about what "
        "you put up; when he asks to see something, always put it on screen. "
        "When he asks for work to "
        "be done, say in one sentence what you'll do and call start_mission with his full request; JAI's agents "
        "then do the work and you'll receive a message beginning [mission update] when it finishes or pauses; "
        "tell him the outcome in a sentence or two. When he asks to continue, resume or carry on with a mission, "
        "call resume_mission; never start a new mission to continue an old one.\n"
        "Each workspace is a folder on his computer that JAI and its agents work in. Never tell him you cannot "
        "access his files: use list_workspace_files and read_workspace_file to look at what is there, and "
        "start_mission for work on it, naming where to look, e.g. 'Read the design in the MYCO workspace's docs "
        "folder and write a build plan to docs/BUILD_PLAN.md'. If a workspace has no folder registered, say so "
        "and offer to register one when he gives the path.\n"
        "If a mission fails, tell him plainly what the error says. Do not claim you will fix it behind the "
        "scenes: you cannot change JAI's own code from a conversation. Restart a failed mission at most once, "
        "and only if he asks.\n"
        "You never approve anything, publish, spend money or send messages for him by voice: those wait on the "
        "Approvals page, because anyone near the microphone could speak. If he asks you to approve, say so and "
        "point him to the Approvals page. Never read out keys, passwords or secrets."
    )


# Talk with JAI remembers the conversation: every spoken turn is kept per operator (newest 60, for 30 days)
# and the recent ones open each new session, so a new conversation carries on from the last one.
HISTORY_TURNS = 60
HISTORY_IN_SESSION = 30
HISTORY_TTL_SECONDS = 30 * 24 * 3600
_SPEAKERS = {"you": "Richard", "jarv": "JAI"}


def _history_key(user_id: UUID) -> str:
    return f"voice:history:{user_id}"


async def remember_turn(user_id: UUID, who: str, text: str) -> Dict[str, Any]:
    """Keep one spoken turn ("you" is Richard, "jarv" is JAI). Secrets never enter the history."""
    import json
    from datetime import datetime, timezone

    from app.core.redis import get_redis
    from app.core.security import redact_text

    if who not in _SPEAKERS:
        raise ValueError("who must be 'you' or 'jarv'")
    clean = redact_text(" ".join(str(text or "").split()))[:1500]
    if not clean:
        return {"kept": False}
    redis = await get_redis()
    key = _history_key(user_id)
    await redis.lpush(key, json.dumps({"who": who, "text": clean,
                                       "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
    await redis.ltrim(key, 0, HISTORY_TURNS - 1)
    await redis.expire(key, HISTORY_TTL_SECONDS)
    return {"kept": True}


async def recent_turns(user_id: UUID, limit: int = HISTORY_IN_SESSION) -> List[Dict[str, Any]]:
    """The latest spoken turns, oldest first."""
    import json

    from app.core.redis import get_redis

    try:
        raw = await (await get_redis()).lrange(_history_key(user_id), 0, max(0, limit - 1))
    except Exception:  # noqa: BLE001 - a conversation starts without history rather than not at all
        return []
    turns = []
    for item in reversed(raw or []):
        try:
            turns.append(json.loads(item))
        except (TypeError, ValueError):
            continue
    return turns


def now_block() -> str:
    """Today's date and time where Richard is (Europe/London), so JAI knows how long ago things happened."""
    from datetime import datetime, timezone

    try:
        from zoneinfo import ZoneInfo

        now, zone = datetime.now(ZoneInfo("Europe/London")), "UK time"
    except Exception:  # noqa: BLE001 - no time-zone database in the image: say UTC rather than guess
        now, zone = datetime.now(timezone.utc), "UTC"
    return (f"\nIt is now {now:%A %-d %B %Y, %H:%M} {zone}. Times in the conversation below are UTC; "
            "when he spoke to you earlier today, say so, and never greet him as if it were a new day "
            "when it is not.")


def history_block(turns: List[Dict[str, Any]]) -> str:
    if not turns:
        return ""
    lines = [f"[{str(t.get('at', ''))[:16].replace('T', ' ')}] {_SPEAKERS.get(t.get('who'), 'JAI')}: {t.get('text', '')}"
             for t in turns]
    return ("\nYOUR RECENT CONVERSATION WITH RICHARD (earlier sessions, oldest first). Carry on from it as one "
            "continuous relationship: remember what he told you and what you said, and do not re-introduce "
            "yourself. Check facts about missions with your tools, because they may have moved on since:\n"
            + "\n".join(lines))


async def record_usage(usage: Dict[str, Any]) -> Dict[str, Any]:
    """One live voice reply's usage, as OpenAI reports it on response.done: priced, added to today's spend, and
    whether the conversation must stop because today's limit is now reached."""
    from app.core import spend

    cost = spend.realtime_cost(settings.OPENAI_REALTIME_MODEL, usage if isinstance(usage, dict) else {})
    await spend.record("voice", cost)
    state = await spend.today()
    return {"cost_usd": round(cost, 5), "today": state, "stop": state["limit_reached"],
            "reason": (f"Today's AI spending limit is reached (${state['total_usd']:.2f} of ${state['limit_usd']:.2f}); "
                       f"the conversation has ended.") if state["limit_reached"] else None}


# Words Richard uses that a transcriber would otherwise get wrong.
# Words that make a request sound like a mission without saying what it is ("New mission, Jay, keep me updated").
_NOT_THE_TASK = re.compile(r"\b(new|a|the|start|begin|another|mission|task|job|please|jay|jai|j|ok|okay|right|so|"
                           r"and|can|could|would|you|will|keep|me|updated|update|posted|informed|let|know|now|go|"
                           r"for|it|on|to|do|that|this|one|up|us)\b", re.I)


def mission_brief_is_real(instruction: str) -> bool:
    """Whether a mission brief says what the work is (not just 'new mission, keep me updated')."""
    rest = _NOT_THE_TASK.sub(" ", re.sub(r"[^\w\s]", " ", instruction or ""))
    return len(rest.split()) >= 2


def _letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def workspace_named_in(spaces: List[Any], text: str):
    """The workspace a request names, as heard ('MYCO' heard as 'my co' or 'my core'): letters only, so spacing and
    punctuation do not matter; the longest name heard wins. None when none is named."""
    heard = _letters(text)
    found = [w for w in spaces if len(_letters(w.name)) >= 4 and _letters(w.name) in heard]
    return max(found, key=lambda w: len(_letters(w.name)), default=None)


STT_VOCABULARY = ("Richard talking to JAI (said Jay), his AI operating system, in British English, about his "
                  "projects MYCO (said my-co; it is never 'my core'), Plexecute, Pardosa, MystaAI, Secundas, ContractusAI and AURELIUS: missions, "
                  "agents, Phase 0, approvals, workspaces, deploy, Docker, Pipecat, ComfyUI, GitHub.")


async def live_context(db: AsyncSession, user_id: UUID, text: str) -> Dict[str, Any]:
    """JAI's live state for the brain voice's next reply, as compact text."""
    import json

    import asyncio

    # Mem0 and Graphiti are asked while the rest is gathered, not after it: one after the other they took the read
    # past the voice's four seconds whenever a mission was running (9 November: every reply said "I can't read the
    # live state").
    recalled = asyncio.create_task(_recalled(text, await _active_spaces(db, user_id)))
    try:
        facts = await brain_facts(db, user_id, text, None)
    except BaseException:
        recalled.cancel()
        raise
    facts.pop("recent_conversation", None)  # the conversation itself is already in the voice's context
    facts.update(await recalled)
    return {"state": voice_state_text(compact_for_voice(facts))}


# The voice reads the live state before every reply, so its size is time Richard waits: it carries what a spoken
# answer needs (the mission he means keeps its whole report, for read-outs), and the rest in short.
VOICE_STATE_CHARS = 20000


def voice_state_text(facts: Dict[str, Any]) -> str:
    """The state as JSON within VOICE_STATE_CHARS, always whole JSON: when it is too long, the report of the mission
    he asked about is shortened to fit, then the rest is dropped piece by piece."""
    import json

    def dump(value):
        return json.dumps(value, default=str, separators=(",", ":"))

    text = dump(facts)
    if len(text) <= VOICE_STATE_CHARS:
        return text
    facts = dict(facts)
    asked = facts.get("mission_asked_about")
    if isinstance(asked, dict) and asked.get("result"):
        over = len(text) - VOICE_STATE_CHARS
        report = str(asked["result"])
        facts["mission_asked_about"] = {**asked, "result": report[:max(2000, len(report) - over - 40)] + " [...]"}
        text = dump(facts)
    for key in ("knowledge", "memories", "what_my_work_has_established", "recent_missions", "my_recent_upgrades"):
        if len(text) <= VOICE_STATE_CHARS:
            break
        facts.pop(key, None)
        text = dump(facts)
    return text


def compact_for_voice(facts: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(facts)
    out["recent_missions"] = [{**m, **({"last_report": str(m["last_report"])[:350]} if m.get("last_report") else {})}
                              for m in (facts.get("recent_missions") or [])[:5]]
    out["memories"] = [{"content": str(m.get("content", ""))[:240], "type": m.get("type")}
                       for m in facts.get("memories") or [] if m.get("type") != "source"][:5]
    out["knowledge"] = [{**k, "content": str(k.get("content", ""))[:300]} for k in facts.get("knowledge") or []][:3]
    return out


_KEEPING: set = set()  # what Richard said, on its way to Mem0


async def _remembered(db: AsyncSession, user_id: UUID, text: str) -> Dict[str, Any]:
    """What Richard has told JAI before and what JAI knows from its work that bear on what he just said (Wave 6:
    Mem0 and Graphiti), and what he said now kept for next time. A slow or stopped knowledge service adds nothing
    and never holds the reply up."""
    return await _recalled(text, await _active_spaces(db, user_id))


async def _active_spaces(db: AsyncSession, user_id: UUID) -> List[Any]:
    from app.core import knowledge_service as ks
    from app.models.workspace import Workspace

    if not ks.enabled():
        return []
    return list((await db.execute(select(Workspace.id).where(Workspace.owner_id == user_id,
                                                             Workspace.is_active.is_(True)))).scalars().all())


async def _recalled(text: str, spaces: List[Any]) -> Dict[str, Any]:
    """Mem0 and Graphiti's part of _remembered, which needs no database session (so it runs alongside one)."""
    import asyncio

    from app.core import knowledge_service as ks

    said = (text or "").strip()
    if not ks.enabled() or len(said) < 3:
        return {}
    told, known = await asyncio.gather(
        ks.quietly(ks.recall(said, 6, timeout=2.5), []),
        ks.quietly(ks.search_graph(said, list(spaces), 8, timeout=2.5), []) if spaces else asyncio.sleep(0, []))
    if len(said) >= 12:
        keeping = asyncio.create_task(ks.quietly(ks.remember(said, metadata={"from": "voice"}, timeout=4.0), None))
        _KEEPING.add(keeping)
        keeping.add_done_callback(_KEEPING.discard)
    out: Dict[str, Any] = {}
    if told:
        out["what_richard_has_told_me"] = [m["memory"] for m in told]
    if known:
        out["what_my_work_has_established"] = [
            {"fact": f["fact"], **({"no_longer_true": True} if f.get("no_longer_true") else {}),
             **({"since": f["valid_from"]} if f.get("valid_from") else {})} for f in known]
    return out


async def record_pipeline_usage(kind: str, usage: Dict[str, Any]) -> Dict[str, Any]:
    """One use by the Pipecat voice (model, speech-to-text or text-to-speech): priced, added to today's spend as
    voice, and whether the conversation must stop because today's limit is now reached."""
    from app.core import spend

    if kind not in {"llm", "tts", "stt"}:
        raise ValueError(f"Unknown voice usage kind: {kind}")
    cost = spend.pipeline_cost(kind, usage if isinstance(usage, dict) else {})
    await spend.record("voice", cost)
    state = await spend.today()
    return {"cost_usd": round(cost, 6), "today": state, "stop": state["limit_reached"],
            "reason": (f"Today's AI spending limit is reached (${state['total_usd']:.2f} of ${state['limit_usd']:.2f}); "
                       f"the conversation has ended.") if state["limit_reached"] else None}


# The Pipecat voice speaks the model's text through text-to-speech, so the text must read aloud well.
# How the voice talks (Richard: "not robotic, conversational, the Jarvis direction"). Last, so it governs the tone.
CONVERSATION_STYLE = (
    "\nHOW YOU TALK. You are talking with Richard, not reading to him: think of a composed, quick, dryly witty "
    "British aide who knows everything going on and gets to the point. Start every reply with a short sentence of "
    "under ten words, so he hears you at once, then at most two more. Answer what he asked first. Never recite: "
    "do not read out lists, records, field names, ids, statuses or timestamps; pick what matters most and say it "
    "in your own words, and if there is more, offer it ('Want the rest?') rather than listing it. When he says "
    "'what else' or 'carry on', give the next most important thing in a sentence or two, never the whole list "
    "again. Say times the way a person does ('this morning', 'about an hour ago'), not clock readings. Use "
    "contractions and everyday words, vary how you begin, use his name only now and then, and keep the odd light "
    "touch of humour. If he interrupts or changes the subject, follow him at once. Silence is fine: never fill it.\n")

# Who Jay is when it speaks: a JARVIS-style aide, Richard's own, for his AI operating system.
# Jay's personality is shared with the Command Center's written replies (app/core/identity).
from app.core.identity import PERSONA, summary as _about_jai  # noqa: E402

SPOKEN_TEXT = ("\nYour replies are spoken aloud by a text-to-speech voice: plain sentences only, never markdown, "
               "lists, headings, emoji, code or URLs; say numbers and ids the way a person would read them. "
               "Open the conversation with one short sentence that tells him what matters right now, from the "
               "picture below, without a generic greeting.\n")


def engine_choice() -> Dict[str, Any]:
    """Which voice the dashboard should use: the Pipecat service (with the Realtime voice as its fallback) or
    the Realtime voice only."""
    choice = (settings.VOICE_ENGINE or "pipecat").strip().lower()
    return {"engine": "realtime" if choice == "realtime" else "pipecat",
            "url": settings.VOICE_PIPELINE_PUBLIC_URL, "fallback": "realtime", "available": available(),
            "setup": setup_hint()}


PIPELINE_VOICES = ("chatterbox", "kokoro", "openai", "fish")


def pipeline_voice() -> tuple[str, str]:
    """(engine, voice) for the Pipecat conversation. Fish Audio (Upgrade 7) needs FISH_API_KEY; without it the
    conversation speaks with Kokoro, the local British voice, so a missing key never silences JAI."""
    choice = (settings.VOICE_PIPELINE_TTS or "chatterbox").strip().lower()
    engine = choice if choice in PIPELINE_VOICES else "chatterbox"
    if engine == "fish" and not settings.FISH_API_KEY:
        engine = "kokoro"
    voice = {"chatterbox": settings.VOICE_PIPELINE_CHATTERBOX_VOICE, "kokoro": settings.VOICE_PIPELINE_KOKORO_VOICE,
             "openai": settings.VOICE_PIPELINE_TTS_VOICE, "fish": settings.FISH_VOICE_ID}[engine]
    return engine, voice


async def pipeline_brief(db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
    """Everything the Pipecat voice needs for one conversation: JAI's instructions with the current picture and
    the recent conversation, the voice tools, the model and voice. Refused when today's limit is reached."""
    from app.core import spend
    from app.core.audit import AuditLogger

    if not available():
        raise LiveUnavailable(setup_hint())
    state = await spend.today()
    if state["limit_reached"]:
        raise LiveUnavailable(f"Today's AI spending limit is reached (${state['total_usd']:.2f} of "
                              f"${state['limit_usd']:.2f}), so the live conversation cannot start until it is raised "
                              f"(DAILY_SPEND_LIMIT_USD) or the day turns over.")
    spaces = await _workspaces(db, user_id)
    text = (spoken_instructions(spaces, brain=True) + now_block() + history_block(await recent_turns(user_id)))
    await AuditLogger.log_system_event(db, action=SESSION_ACTION, result="ok", resource_type="voice",
                                       user_id=user_id, details={"engine": "pipecat",
                                                                 "model": settings.VOICE_PIPELINE_MODEL})
    await db.commit()
    engine, voice = pipeline_voice()
    return {"engine": "pipecat", "instructions": text, "model": settings.VOICE_PIPELINE_MODEL,
            # The voice is the brain: it has JAI's tools, and no ask_jarv (it is given what ask_jarv knows).
            "tools": [t for t in VOICE_TOOLS if t["name"] != "ask_jarv"],
            "reasoning": settings.VOICE_PIPELINE_REASONING or None,
            "stt_model": settings.VOICE_PIPELINE_STT_MODEL, "stt_prompt": STT_VOCABULARY,
            "tts_engine": engine, "tts_voice": voice, "fallback_voice": settings.VOICE_PIPELINE_KOKORO_VOICE,
            "tts_speed": settings.VOICE_PIPELINE_SPEED,
            "tts_model": settings.FISH_MODEL if engine == "fish" else settings.VOICE_PIPELINE_TTS_MODEL,
            "tts_instructions": "Accent: Received Pronunciation, an educated southern English British accent, "
                                "never American. Tone: calm, warm and assured, like a trusted chief of staff "
                                "reporting. Pace: natural, unhurried.",
            "spend": state}


async def situation_block(db: AsyncSession, user_id: UUID) -> str:
    """What JAI is doing as the conversation opens: missions in progress with their latest step, and what waits
    for Richard's approval. It is a starting picture; the instructions say to check again before answering."""
    try:
        missions = [m for m in await _recent_missions(db, user_id, limit=8) if m.get("in_progress")]
        waiting = (await _approvals(db, user_id))["count"]
    except Exception:  # noqa: BLE001 - the picture is an addition; the tools still answer
        return ""
    if missions:
        lines = []
        for m in missions[:4]:
            state = "between rounds, next round queued" if m.get("between_rounds") else m.get("status")
            latest = (m.get("latest_activity") or ["no steps recorded yet"])[0]
            facts = m.get("progress") or {}
            timing = (f"; running {facts['minutes_running']} min, last step {facts.get('minutes_since_last_step')} min ago"
                      if facts.get("minutes_running") is not None else "")
            where = (f"{timing}; {facts.get('phase')}, round {facts.get('round')} step {facts.get('step')}, "
                     f"{facts.get('requirements_done')} of {facts.get('requirements_total')} requirements done, "
                     f"{facts.get('files_changed')} files changed, {facts.get('commands_failed')} commands failed"
                     if facts else "")
            lines.append(f"- {m['title']} ({state}; started {m.get('started')}{where}; latest: {latest})")
        doing = "Missions in progress:\n" + "\n".join(lines)
    else:
        doing = "No mission is in progress."
    return (f"\nWhat JAI is doing as this conversation opens (check get_status for the latest):\n{doing}\n"
            f"Waiting for Richard's approval: {waiting}.\n")


async def create_session(db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
    """A short-lived Realtime client secret for this operator, carrying JAI's instructions and tools."""
    if not available():
        raise LiveUnavailable(setup_hint())
    from app.core import spend
    from app.core.audit import AuditLogger

    state = await spend.today()
    if state["limit_reached"]:
        raise LiveUnavailable(f"Today's AI spending limit is reached (${state['total_usd']:.2f} of "
                              f"${state['limit_usd']:.2f}), so the live conversation cannot start until it is raised "
                              f"(DAILY_SPEND_LIMIT_USD) or the day turns over.")
    spaces = await _workspaces(db, user_id)
    model, voice = settings.OPENAI_REALTIME_MODEL, settings.OPENAI_REALTIME_VOICE
    body = {"session": {
        "type": "realtime", "model": model,
        "instructions": (spoken_instructions(spaces) + now_block() + await situation_block(db, user_id)
                         + history_block(await recent_turns(user_id))),
        "tools": VOICE_TOOLS, "tool_choice": "auto",
        "audio": {"input": {"transcription": {"model": settings.OPENAI_REALTIME_TRANSCRIBE_MODEL},
                            "turn_detection": {"type": "semantic_vad"}},
                  "output": {"voice": voice}},
    }}
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json",
               # A stable, hashed operator id for OpenAI's abuse monitoring; never the user's name.
               "OpenAI-Safety-Identifier": hashlib.sha256(f"jarv:{user_id}".encode()).hexdigest()}
    try:
        async with engine.http_client(timeout=httpx.Timeout(20.0)) as client:
            response = await client.post(REALTIME_SECRETS, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise RuntimeError(engine._unreachable("openai", exc)) from exc
    if response.status_code >= 400:
        raise engine._error(response, "Starting the live conversation (openai)")
    payload = response.json()
    secret = payload.get("value") or (payload.get("client_secret") or {}).get("value")
    if not secret:
        raise RuntimeError("OpenAI returned no client secret for the live conversation")
    await AuditLogger.log_system_event(db, action=SESSION_ACTION, result="ok", resource_type="voice",
                                       user_id=user_id, details={"model": model, "voice": voice})
    await db.commit()
    return {"client_secret": secret, "expires_at": payload.get("expires_at"), "model": model, "voice": voice,
            "calls_url": "https://api.openai.com/v1/realtime/calls"}


async def _resolve_workspace(db: AsyncSession, user_id: UUID, name: Optional[str]):
    if not name:
        return None, None
    wanted = name.strip().lower()
    spaces = await _workspaces(db, user_id)
    match = next((w for w in spaces if w.name.lower() == wanted or w.slug.lower() == wanted), None) or \
        next((w for w in spaces if wanted in w.name.lower()), None)
    if match is None:
        return None, f"No workspace called {name}. His workspaces: {', '.join(w.name for w in spaces) or 'none'}."
    return match.id, None


def _inside(root: str, relative: Optional[str]) -> Optional[str]:
    """root joined with a relative path that stays inside it (None if it would leave)."""
    rel = (relative or "").strip().replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p and p != "."]
    if any(p == ".." for p in parts) or (rel and (":" in parts[0] if parts else False)):
        return None
    if not parts:
        return root
    sep = "\\" if ("\\" in root or ":" in root[:3]) else "/"
    return root.rstrip("\\/") + sep + sep.join(parts)


async def _workspace_files(db: AsyncSession, user_id: UUID, name: str, args: Dict[str, Any],
                           read: bool) -> Dict[str, Any]:
    from app.core.workspaces import fs_inspector

    workspace_id, problem = await _resolve_workspace(db, user_id, name)
    if problem or workspace_id is None:
        return {"error": problem or "Name the workspace."}
    workspace = next(w for w in await _workspaces(db, user_id) if w.id == workspace_id)
    root = _root(workspace)
    if not root:
        return {"error": f"{workspace.name} has no folder registered."}
    target = _inside(root, args.get("path"))
    if target is None:
        return {"error": "That path is outside the workspace."}
    if read:
        found = fs_inspector.read_file(target, max_bytes=12000)
        if not found.accessible or not found.exists:
            return {"error": found.reason or f"No file at {args.get('path')}."}
        return {"path": args.get("path"), "content": found.data.get("content", ""),
                "truncated": bool(found.data.get("truncated")), "size_bytes": found.data.get("size_bytes")}
    listed = fs_inspector.list_dir(target)
    if not listed.accessible or not listed.exists:
        return {"error": listed.reason or f"No folder at {args.get('path') or 'the top of the workspace'}."}
    entries = listed.data.get("entries", [])
    return {"workspace": workspace.name, "folder": target, "count": len(entries),
            "entries": [{"name": e["name"], "folder": e["is_dir"]} for e in entries[:200]]}


def _working(status: Optional[str]) -> bool:
    """Whether a mission is still being worked on: running, queued, recovering, about to start, or between two
    rounds of a long mission (needs_continuation: the next round is queued and starts by itself)."""
    from app.core.runtime import lifecycle

    return lifecycle.normalise(status) in lifecycle.IN_FLIGHT


def _between_rounds(status: Optional[str]) -> bool:
    from app.core.runtime import lifecycle

    return lifecycle.normalise(status) == lifecycle.NEEDS_CONTINUATION


MISSION_REPORT_CHARS = 12000
_MISSION_ID = re.compile(r"\b([0-9a-f]{8})(?:-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?\b", re.I)


async def _mission_named_in(db: AsyncSession, user_id: UUID, text: str) -> Optional[Dict[str, Any]]:
    """The mission a question is about: one whose id (or its first eight characters) it names, otherwise the
    latest; with its whole report."""
    compact = re.sub(r"[\s-]", "", text or "")
    for match in _MISSION_ID.finditer(text or "") or []:
        full = await _full_id(db, user_id, match.group(1).lower())
        if full:
            return await _mission(db, user_id, str(full))
    for match in _MISSION_ID.finditer(compact):
        full = await _full_id(db, user_id, match.group(1).lower())
        if full:
            return await _mission(db, user_id, str(full))
    return await _mission(db, user_id, None)


async def _mission(db: AsyncSession, user_id: UUID, task_id: Optional[str]) -> Dict[str, Any]:
    from app.core.scoping import owned_workspaces
    from app.models.task import Task

    query = select(Task).where(Task.workspace_id.in_(owned_workspaces(user_id)), Task.task_type != "subtask")
    if task_id:
        try:
            query = query.where(Task.id == UUID(str(task_id)))
        except ValueError:
            return {"error": "That is not a mission id."}
        task = (await db.execute(query)).scalar_one_or_none()
    else:
        # "The mission" is the one still being worked on, if any; otherwise the latest one that is not archived.
        recent = (await db.execute(query.order_by(Task.created_at.desc()).limit(50))).scalars().all()
        visible = [t for t in recent if not (t.meta_data or {}).get("archived_at")]
        working = [t for t in visible if _working(t.status)]
        task = (working or visible or [None])[0]
    if task is None:
        return {"error": "No mission found."}
    result = task.result if isinstance(task.result, dict) else {}
    if _working(task.status):
        # A mission being worked on is described by what it is doing now; its last report and error are
        # from an earlier round (a pause it has since come back from) and would mislead.
        note = "Still being worked on. Describe it from latest_activity; earlier pauses are over."
        if _between_rounds(task.status):
            note = ("Still being worked on: one round has finished and the next is queued and starts by itself. "
                    "Describe it from latest_activity; the last round's report is not the result.")
        from app.core.command import progress

        return {"task_id": str(task.id), "title": task.title, "status": task.status, "in_progress": True,
                "rounds_done": int(result.get("continuation_count") or 0) or None,
                "folder": result.get("workspace_path"), "latest_activity": await _activity(db, task.id),
                "progress": (lambda p: {**p, **progress.age(p)} if p else None)(await progress.load(task.id)),
                "note": note + (" Report from progress: phase, round and step, requirements done and open (by id), "
                                "files changed, commands that failed and why, and what it is doing now.")}
    # Missions store their report under "response".
    summary = (result.get("response") or result.get("response_text") or result.get("output")
               or result.get("summary") or "")
    return {"task_id": str(task.id), "title": task.title, "status": task.status,
            "folder": result.get("workspace_path"),
            # The whole report: Richard asks for it to be read out or analysed, and a cut one cannot be.
            "result": str(summary)[:MISSION_REPORT_CHARS], "error": (task.error_message or "")[:300] or None,
            # The evidence report (Upgrade 4): say what is shown done with evidence, nothing more.
            "report": _spoken_report(result.get("report"))}


async def _memories(db: AsyncSession, user_id: UUID, query: str, workspace_id: Optional[UUID],
                    limit: int = 8) -> List[Dict[str, Any]]:
    """JAI's memories that match, from the named workspace or all of his, best first (never another owner's)."""
    from app.core.jarv_memory import memory_service

    scopes = [workspace_id] if workspace_id else [w.id for w in await _workspaces(db, user_id)]
    hits: List[Any] = []
    for scope in scopes:
        hits += await memory_service.search_scored(db, query, limit=limit, workspace_id=scope)
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return [{"content": str(hit.memory.content)[:600], "type": hit.memory.memory_type,
             "category": hit.memory.memory_category, "score": round(hit.score, 3)} for hit in hits[:limit]]


async def _approvals(db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
    from app.core.richard.workflow import RichardBoundaryWorkflow

    pending = await RichardBoundaryWorkflow(db).list_pending_decisions(owner=user_id)
    return {"count": len(pending), "waiting": [
        {"action": str(item.get("action_description") or "")[:200], "type": item.get("boundary_type"),
         "expires_at": item.get("expires_at")} for item in pending[:10]],
        "note": "Richard approves these on the Approvals page; never by voice."}


async def _activity(db: AsyncSession, task_id, limit: int = 12) -> List[str]:
    """What a running mission did most recently, from the operations feed (newest first)."""
    from app.models.company_operations import LiveOperationsFeedItem

    rows = (await db.execute(select(LiveOperationsFeedItem).where(
        LiveOperationsFeedItem.related_task_id == task_id)
        .order_by(LiveOperationsFeedItem.created_at.desc()).limit(limit))).scalars().all()
    return [f"{r.created_at:%H:%M} {r.title}: {(r.message or '')[:160]}" for r in rows if r.created_at]


async def _progress_of(task_id) -> Optional[Dict[str, Any]]:
    from app.core.command import progress

    return await progress.load(task_id)


def _brief(progress: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A mission's progress in a few facts: phase, round and step, requirements, files, failures, latest step."""
    if not progress:
        return None
    reqs = progress.get("requirements") or {}
    by_status = reqs.get("by_status") or {}
    from app.core.command.progress import age

    check = progress.get("check") or {}
    return {**age(progress),
            "phase": progress.get("phase"), "round": progress.get("round"), "step": progress.get("step"),
            "check_step": check.get("step"), "check_steps": check.get("steps"),
            "check_doing_now": check.get("doing_now"), "check_failures": check.get("recent_failures"),
            "requirements_done": by_status.get("done", 0), "requirements_total": reqs.get("total", 0),
            "open": [f"{r.get('id')} {r.get('text')}" for r in reqs.get("items") or []
                     if r.get("status") != "done"][:6],
            "files_changed": progress.get("files_changed_count", 0),
            "commands_failed": progress.get("commands_failed", 0),
            "last_failure": (progress.get("recent_failures") or [None])[-1],
            "doing_now": progress.get("doing_now"), "updated_at": progress.get("updated_at"),
            # A mission run by a team: who is on it and what each specialist is doing.
            "team": [{"who": f"{p.get('id')} {p.get('role')}", "package": p.get("title"), "status": p.get("status"),
                      "step": p.get("step"), "doing_now": (p.get("doing_now") or "")[:160]}
                     for p in ((progress.get("team") or {}).get("packages") or [])][:12] or None}


async def _recent_missions(db: AsyncSession, user_id: UUID, limit: int = 6) -> List[Dict[str, Any]]:
    from app.core.scoping import owned_workspaces
    from app.models.task import Task

    rows = (await db.execute(select(Task).where(
        Task.workspace_id.in_(owned_workspaces(user_id)), Task.task_type == "command")
        .order_by(Task.created_at.desc()).limit(limit * 3))).scalars().all()
    missions = []
    for task in rows:
        if (task.meta_data or {}).get("archived_at"):
            continue
        result = task.result if isinstance(task.result, dict) else {}
        entry = {"id": str(task.id)[:8], "title": (task.title or "")[:120], "status": task.status,
                 "started": task.created_at.isoformat(timespec="minutes") if task.created_at else None,
                 "folder": result.get("workspace_path"),
                 "last_report": str(result.get("response") or task.error_message or "")[:700]}
        if _working(task.status):
            entry["in_progress"] = True
            entry["latest_activity"] = await _activity(db, task.id)
            if _between_rounds(task.status):
                entry["between_rounds"] = True
            entry["progress"] = _brief(await _progress_of(task.id))
            entry.pop("last_report")  # an earlier round's report would be mistaken for the result
        missions.append(entry)
        if len(missions) == limit:
            break
    return missions


async def brain_facts(db: AsyncSession, user_id: UUID, question: str,
                      workspace_id: Optional[UUID] = None) -> Dict[str, Any]:
    """JAI's live state as it bears on what Richard just said: workspaces, every mission with what is being worked
    on now (full progress), the mission he is asking about with its whole report, what waits for him, today's
    spend, the status line, memories, knowledge and verified lessons relevant to it, the date and the recent
    conversation. The voice receives this on every turn; ask_jarv answers from it too."""
    from app.core.learning import learning_service

    facts: Dict[str, Any] = {
        "workspaces": [{"name": w.name, "folder": _root(w), "authority_level": w.authority_level}
                       for w in await _workspaces(db, user_id)],
        "recent_missions": await _recent_missions(db, user_id),
        "waiting_for_approval": (await _approvals(db, user_id))["waiting"],
        "memories": await _memories(db, user_id, question, workspace_id),
        "now": now_block().strip(),
        "recent_conversation": [f"[{str(t.get('at', ''))[:16]}] {_SPEAKERS.get(t.get('who'), 'JAI')}: "
                                f"{t.get('text', '')[:300]}" for t in await recent_turns(user_id, 16)],
    }
    # The live picture: every mission still being worked on, with its full progress record (each requirement,
    # files changed, failures, the independent check) and how old it is; and the overall status line.
    from app.core.command import progress as mission_progress

    working = []
    for mission in facts["recent_missions"]:
        if mission.get("in_progress"):
            task_id = await _full_id(db, user_id, mission["id"])
            record = await mission_progress.load(task_id) if task_id else None
            working.append({"title": mission["title"], "status": mission["status"],
                            "between_rounds": mission.get("between_rounds", False),
                            "progress": {**record, **mission_progress.age(record)} if record else None,
                            "latest_activity": mission.get("latest_activity")})
    facts["working_now"] = working
    # The mission the question is about, with its whole report, so "read it out" or "analyse the last report"
    # has the report itself to work from (the mission list carries only the start of each report).
    try:
        async with db.begin_nested():
            facts["mission_asked_about"] = await _mission_named_in(db, user_id, question)
    except Exception:  # noqa: BLE001 - an addition; the mission list still answers
        facts["mission_asked_about"] = None
    # What has been installed into JAI lately (from Richard's repository history), so "what upgrades have you had
    # today?" has a true answer.
    from app.core import upgrades

    facts["my_recent_upgrades"] = await upgrades.recent(3, 15)
    # A question about JAI itself is answered from its own design document, in full, not a mission.
    from app.core.identity import asks_about_me, capabilities

    if asks_about_me(question):
        facts["what_i_am"] = capabilities()
    try:
        from app.core import spend

        facts["ai_spend_today"] = await spend.today()  # so "what have I spent today?" has a true answer
    except Exception:  # noqa: BLE001
        facts["ai_spend_today"] = None
    try:
        async with db.begin_nested():  # an optional lookup never spoils the session for the rest
            facts["status"] = (await engine._status_reply(db, user_id, workspace_id))["reply"]
    except Exception:  # noqa: BLE001 - the status line is an addition
        facts["status"] = None
    # JAI's knowledge library and the workspace's specification passages, for why and how questions.
    try:
        from app.core.knowledge.search import search_everything

        async with db.begin_nested():
            hits = await search_everything(db, question, workspace_id=workspace_id, limit=5)
        facts["knowledge"] = [{"kind": hit.get("kind"), "title": hit.get("title"),
                               "content": str(hit.get("content") or "")[:600], "cite": hit.get("citation")}
                              for hit in hits[:5]]
    except Exception:  # noqa: BLE001
        facts["knowledge"] = []
    if workspace_id is not None:
        try:
            facts["verified_lessons"] = [
                {"lesson": item["lesson"], "outcome": item["polarity"]} for item in
                await learning_service.retrieve_lessons(db, workspace_id=workspace_id, agent_name="orchestrator",
                                                        query=question, limit=3)]
        except Exception:  # noqa: BLE001 - lessons are an addition, never a reason to fail the answer
            facts["verified_lessons"] = []
    return facts


async def _ask_jarv(db: AsyncSession, user_id: UUID, question: str, workspace_id: Optional[UUID]) -> Dict[str, Any]:
    """Answer from JAI's own memory, lessons, missions and approvals with JAI's reasoning model."""
    import json
    import logging
    import time

    timing = logging.getLogger("jai.voice.timing")
    started = time.monotonic()

    from app.core.command import CommandService
    from app.core.providers import CompletionRequest, Message, get_router

    facts = await brain_facts(db, user_id, question, workspace_id)
    gathered = time.monotonic()
    service = CommandService()
    response = await get_router().complete(CompletionRequest(
        # Low effort: a spoken answer must come in seconds; the facts already carry the live picture.
        model=service.model, max_tokens=1400, temperature=0.2, reasoning_effort="low",
        system=("You are JAI's reasoning core answering Richard Curley's spoken question; your answer is spoken "
                "aloud by JAI's voice, so speak as JAI, in the first person ('I am on step 7 of the check'). Answer "
                "only from the facts given (what_i_am, your own design document, for any question about you, your "
                "capabilities or your upgrades, with its exact numbers and names; working_now with each mission's live progress, the status line, "
                "recent missions, approvals, JAI's memory, verified lessons, the knowledge library and your recent "
                "conversation with him); when they do not contain the answer, say so plainly and say what JAI would "
                "need to find out. Be specific: requirement ids, file names, commands, exit codes, numbers, minutes. "
                "Explain why, not only what: what a step does, why it takes the time it does, what it means for the "
                "mission and what comes next. Never use filler ('moving along', 'on track', 'I'll keep an eye on "
                "it'), never promise updates, and never repeat what the recent conversation already told him: say "
                "what is new or, if nothing is, say that in one sentence and add something useful. A mission marked "
                "in_progress is still running: describe it only from its own "
                "latest_activity, never from another mission's last_report, and do not say it committed, passed "
                "or finished unless its own activity shows that. Each last_report belongs only to its own "
                "mission. Use the timing facts (minutes running, minutes since the last step) to explain how "
                "long things take and why; a step that has run for minutes is usually a full build, test or verify "
                "run. Answer the question asked, with what is new; do not restate the whole status. Two to five "
                "spoken sentences, British English, no lists or markdown; but when he asks for a report to be read "
                "out, for the details, or for an analysis, give it from mission_asked_about's whole report, in full "
                "and in order, up to about 350 words, still as spoken prose."),
        messages=[Message(role="user", content=f"Question: {question}\n\nFacts:\n{json.dumps(facts, default=str)}")]))
    timing.info(f"timing ask_jarv facts {gathered - started:.2f}s, model {time.monotonic() - gathered:.2f}s "
                f"({len(json.dumps(facts, default=str))} characters of facts)")
    return {"answer": (response.content or "").strip() or "I could not form an answer from what I know.",
            "missions_considered": len(facts["recent_missions"]), "memories_considered": len(facts["memories"])}


async def show_on_screen(db: AsyncSession, user_id: UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    """What JAI puts on Richard's screen: a card of titled sections (rows, items or text) built from JAI's own
    records, so the dashboard shows the facts themselves, never the voice's paraphrase of them."""
    from app.core import spend as daily
    from app.core.command import progress as mission_progress

    what = str(args.get("what") or "")
    if what == "mission":
        mission = await _mission(db, user_id, None)
        if mission.get("error"):
            return {"error": mission["error"]}
        task_id = mission.get("task_id")
        record = await mission_progress.load(task_id) if task_id else None
        record = {**record, **mission_progress.age(record)} if record else {}
        reqs = (record.get("requirements") or {}).get("items") or []
        check = record.get("check") or {}
        subtitle = " · ".join(str(x) for x in (
            mission.get("status"), record.get("phase"),
            f"round {record['round']}, step {record['step']} of {record.get('step_budget')}" if record.get("round") else None,
            f"check step {check['step']} of {check['steps']}" if check.get("step") else None,
            f"running {record['minutes_running']} min" if record.get("minutes_running") is not None else None,
            f"last step {record['minutes_since_last_step']} min ago" if record.get("minutes_since_last_step") is not None
            else None) if x)
        sections = []
        if reqs:
            sections.append({"heading": f"Requirements ({sum(1 for r in reqs if r.get('status') == 'done')} of "
                                        f"{len(reqs)} done)",
                             "columns": ["", "Status", "Requirement"],
                             "rows": [[r.get("id"), r.get("status"), r.get("text")] for r in reqs]})
        doing = check.get("doing_now") or record.get("doing_now")
        if doing:
            sections.append({"heading": "Doing now", "items": [f"{doing.get('tool')} {doing.get('target')} — "
                                                               f"{doing.get('result')}"]})
        if record.get("files_changed"):
            sections.append({"heading": f"Files changed ({record.get('files_changed_count')})",
                             "items": record["files_changed"]})
        failures = (check.get("recent_failures") or []) + (record.get("recent_failures") or [])
        if failures:
            sections.append({"heading": "Recent failures", "columns": ["Tool", "Target", "Why"],
                             "rows": [[f.get("tool"), f.get("target"), f.get("why")] for f in failures[-5:]]})
        if not mission.get("in_progress") and mission.get("result"):
            sections.append({"heading": "Report", "code": str(mission["result"])})
        if not sections:
            sections.append({"heading": "Latest activity", "items": mission.get("latest_activity")
                             or ["No steps recorded yet."]})
        card = {"kind": "mission", "title": mission.get("title") or "Mission", "subtitle": subtitle,
                "sections": sections}
    elif what == "spend":
        state = await daily.today()
        rows = [["Text models", f"${state['text_usd']:.2f}"], ["Live voice", f"${state['voice_usd']:.2f}"],
                ["Total", f"${state['total_usd']:.2f}"],
                ["Daily limit", f"${state['limit_usd']:.2f}" if state["limit_usd"] else "off"]]
        if state["remaining_usd"] is not None:
            rows.append(["Left today", f"${state['remaining_usd']:.2f}"])
        card = {"kind": "spend", "title": f"AI spend today ({state['date']})",
                "subtitle": f"{state['calls']} calls" + (" · limit reached" if state["limit_reached"] else ""),
                "sections": [{"heading": "", "columns": ["", "US dollars"], "rows": rows}]}
    elif what == "approvals":
        waiting = (await _approvals(db, user_id))["waiting"]
        card = {"kind": "approvals", "title": f"Waiting for your approval ({len(waiting)})",
                "subtitle": "Approve or reject on the Approvals page", "link": "/dashboard/approvals",
                "sections": [{"heading": "", "items": [w["action"] for w in waiting] or ["Nothing is waiting."]}]}
    elif what == "file" and (str(args.get("path") or "").lower().endswith(IMAGE_TYPES + VIDEO_TYPES + DOCUMENT_TYPES)
                             or await _is_folder(db, user_id, args)):
        media = await _media_card(db, user_id, args)
        if media.get("error"):
            return {"error": media["error"]}
        card = media
    elif what == "file":
        found = await _workspace_files(db, user_id, str(args.get("workspace") or ""), {"path": args.get("path")},
                                       read=True)
        if found.get("error"):
            return {"error": found["error"]}
        card = {"kind": "file", "title": str(found.get("path")),
                "subtitle": f"{args.get('workspace')} · {found.get('size_bytes')} bytes"
                            + (" · first part" if found.get("truncated") else ""),
                "sections": [{"heading": "", "code": str(found.get("content") or "")[:12000]}]}
    else:
        return {"error": "Say what to show: mission, spend, approvals or file."}
    return {"shown": True, "card": card,
            "note": "It is on his screen now: say one sentence about it, do not read it all out."}


IMAGE_LINK_SECONDS = 24 * 3600
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
VIDEO_TYPES = (".mp4", ".webm", ".mov", ".m4v")
# A PDF is shown as the document itself, never as its bytes (9 November: the pitch deck came up as PDF source).
DOCUMENT_TYPES = (".pdf",)
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif", ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
               ".m4v": "video/mp4", ".pdf": "application/pdf"}
GALLERY_LIMIT = 12


async def _media_target(db: AsyncSession, user_id: UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    """The workspace and the container path of what was asked for, confined to the workspace's folder."""
    from app.core.workspaces import fs_inspector

    workspace_id, problem = await _resolve_workspace(db, user_id, str(args.get("workspace") or ""))
    if problem or workspace_id is None:
        return {"error": problem or "Name the workspace."}
    workspace = next(w for w in await _workspaces(db, user_id) if w.id == workspace_id)
    root = _root(workspace)
    if not root:
        return {"error": f"{workspace.name} has no folder registered."}
    target = _inside(root, args.get("path"))
    if target is None:
        return {"error": "That path is outside the workspace."}
    container = fs_inspector.host_to_container(target)
    if container is None:
        return {"error": "That path is outside the workspace."}
    return {"workspace": workspace.name, "host": target, "container": container}


async def _is_folder(db: AsyncSession, user_id: UUID, args: Dict[str, Any]) -> bool:
    found = await _media_target(db, user_id, args)
    return not found.get("error") and found["container"].is_dir()


_SKIP_FOLDERS = {"node_modules", ".git", ".next", "dist", "build", "__pycache__", ".venv", "venv"}


def _media_in(folder, depth: int = 3, limit: int = 3000):
    """Images and videos in a folder and its subfolders (a few levels down), skipping build and dependency
    folders and hidden ones."""
    found, seen = [], 0
    stack = [(folder, 0)]
    while stack and seen < limit:
        current, level = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if entry.is_dir():
                if level < depth and entry.name not in _SKIP_FOLDERS and not entry.name.startswith("."):
                    stack.append((entry, level + 1))
            elif entry.suffix.lower() in IMAGE_TYPES + VIDEO_TYPES:
                found.append(entry)
    return found


async def _media_card(db: AsyncSession, user_id: UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    """An image or video as itself, or a folder as a gallery of its images and videos (newest first)."""
    found = await _media_target(db, user_id, args)
    if found.get("error"):
        return found
    path, where = found["container"], str(args.get("path") or "")
    if path.is_dir():
        files = sorted(_media_in(path), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            return {"error": f"There are no images or videos in {where or 'that folder'}."}
        sections = []
        for f in files[:GALLERY_LIMIT]:
            link = await image_link(str(f))
            sections.append({"heading": str(f.relative_to(path)), **({"video": link} if f.suffix.lower() in VIDEO_TYPES
                                                    else {"image": link})})
        more = f" · showing the newest {GALLERY_LIMIT}" if len(files) > GALLERY_LIMIT else ""
        return {"kind": "gallery", "title": where or found["workspace"],
                "subtitle": f"{found['workspace']} · {len(files)} image(s) and video(s){more}", "sections": sections}
    if not path.is_file():
        return {"error": f"No file at {where}."}
    link = await image_link(str(path))
    suffix = path.suffix.lower()
    kind = "video" if suffix in VIDEO_TYPES else "pdf" if suffix in DOCUMENT_TYPES else "image"
    return {"kind": kind, "title": path.name,
            "subtitle": f"{found['workspace']} · {where} · {round(path.stat().st_size / 1e6, 1)} MB",
            "sections": [{"heading": "", kind: link}]}


async def image_link(container_path: str) -> str:
    """A link to an image JAI made, for Richard's screen: a random token kept for a day (an <img> cannot send his
    sign-in, and the token reveals nothing about where the file is)."""
    import secrets

    from app.core.redis import get_redis

    token = secrets.token_urlsafe(24)
    await (await get_redis()).set(f"voice:image:{token}", container_path, ex=IMAGE_LINK_SECONDS)
    return f"/api/backend/api/voice/image/{token}"


async def image_for(token: str) -> Optional[str]:
    """The file behind an image link, if the link is current and the file is still inside the workspaces."""
    import os

    from app.core.redis import get_redis

    if not token or len(token) > 64:
        return None
    path = await (await get_redis()).get(f"voice:image:{token}")
    if not path:
        return None
    path = path.decode() if isinstance(path, bytes) else str(path)
    from app.core.workspaces.fs_inspector import SANDBOX_CONTAINER_ROOT

    roots = [os.path.normpath(r) for r in (settings.WORKSPACE_CONTAINER_ROOT, SANDBOX_CONTAINER_ROOT)]
    real = os.path.realpath(path)
    inside = any(real.startswith(os.path.realpath(root) + os.sep) for root in roots)
    if not (inside and real.lower().endswith(tuple(MEDIA_TYPES)) and os.path.isfile(real)):
        return None
    return real


def media_type(path: str) -> str:
    import os

    return MEDIA_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


async def _make_image(db: AsyncSession, user_id: UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    """Make an image for one of Richard's workspaces, save it there, and give back the card that shows it."""
    from pathlib import PurePosixPath, PureWindowsPath

    from app.core.command.tool_runtime import ToolRuntime
    from app.core.creative import images

    spaces = await _workspaces(db, user_id)
    wanted = str(args.get("workspace") or "").strip().lower()
    chosen = [w for w in spaces if w.name.lower() == wanted] or [w for w in spaces if wanted and wanted in w.name.lower()]
    if not chosen:
        return {"error": f"Say which workspace the image is for: {', '.join(w.name for w in spaces) or 'none yet'}."}
    space = chosen[0]
    root = _root(space)
    if not root:
        return {"error": f"The {space.name} workspace has no folder registered, so the image has nowhere to go."}
    prompt = str(args.get("prompt") or "")
    relative = images.default_path(prompt)
    join = (lambda *p: str(PureWindowsPath(root, *p))) if (":" in root[:3] or "\\" in root) else \
        (lambda *p: str(PurePosixPath(root, *p)))
    runtime = ToolRuntime(db, space.id, None, operator=f"voice:{user_id}",
                          authority_level=max(2, int(space.authority_level or 2)), user_id=user_id)
    width, height = images.size_of(args.get("shape"))
    made = await runtime.generate_image(join(*relative.split("/")), prompt, width, height,
                                        licence_file=join("ASSET_LICENCES.md"), shown_as=relative)
    if not made.get("success"):
        return {"error": made.get("error") or made.get("reason") or "The image could not be made."}
    await db.commit()
    card = {"kind": "image", "title": prompt[:90], "subtitle": f"{space.name} · {relative} · {made['seconds']}s",
            "sections": [{"heading": "", "image": await image_link(made["container_path"])}]}
    return {"made": True, "workspace": space.name, "path": relative, "seconds": made["seconds"], "card": card,
            "note": "The image is on his screen and saved in the workspace: say one short sentence about it."}


async def _full_id(db: AsyncSession, user_id: UUID, short: str) -> Optional[UUID]:
    """A mission's full id from the 8-character one the mission list shows, within the operator's workspaces."""
    from app.core.scoping import owned_workspaces
    from app.models.task import Task

    rows = (await db.execute(select(Task.id).where(Task.workspace_id.in_(owned_workspaces(user_id)),
                                                   Task.task_type == "command")
                             .order_by(Task.created_at.desc()).limit(40))).scalars().all()
    return next((task_id for task_id in rows if str(task_id).startswith(str(short))), None)


def _spoken_report(report: Any) -> Optional[Dict[str, Any]]:
    """The mission's evidence report in short form for speech: the overall line and each requirement's status."""
    if not isinstance(report, dict):
        return None
    return {"overall": report.get("overall"), "confidence": report.get("confidence"),
            "risks": (report.get("risks") or [])[:5],
            "requirements": [f"{i.get('id')} {i.get('status')}: {str(i.get('text'))[:120]}"
                             for i in (report.get("items") or [])[:30]],
            "hard_checks_failing": len(report.get("hard_failures") or []),
            "waiting_on_richard": report.get("waiting") or []}


_IN_FLIGHT = ("running", "queued", "recovering")
_CANCEL_WORDS = re.compile(r"\b(cancel|stop|kill|abort|halt|scrap|end)\b", re.I)


async def richard_asked_to_cancel(user_id: UUID) -> bool:
    """Whether the last thing Richard said asks to stop something. On 9 November the voice cancelled the running
    Plexecute mission on its own, right after resuming the wrong one."""
    turns = await recent_turns(user_id, 6)
    said = next((t for t in reversed(turns) if t.get("who") == "you"), None)
    return bool(said and _CANCEL_WORDS.search(str(said.get("text") or "")))


def _best_to_resume(candidates: List[Any]) -> Optional[Any]:
    """The mission "carry on" means: the newest mission that works in a folder and is not archived, whether it
    paused at its step limit or stopped part-way. Status never outranks age: preferring step-limit pauses made
    "carry on" restart days-old Phase 0 missions instead of the one Richard had just been running. A mission
    without a folder (for example one created by asking to resume) is never chosen: it has nothing to work on.
    ``candidates`` are newest first."""
    usable = [t for t in candidates if not (t.meta_data or {}).get("archived_at")
              and isinstance(t.result, dict) and t.result.get("workspace_path")]
    return usable[0] if usable else None


async def _resume(db: AsyncSession, user_id: UUID, task_id: Optional[str]) -> Dict[str, Any]:
    from app.core.command.continuation import RESUMABLE, queue_resume
    from app.core.scoping import owned_workspaces
    from app.models.task import Task

    query = select(Task).where(Task.workspace_id.in_(owned_workspaces(user_id)), Task.task_type != "subtask")
    if task_id:
        try:
            query = query.where(Task.id == UUID(str(task_id)))
        except ValueError:
            return {"error": "That is not a mission id."}
        task = (await db.execute(query)).scalar_one_or_none()
    else:
        # A mission still being worked on is what "carry on" means, and it carries on by itself: nothing else is
        # resumed. On 9 November "continue" while the Plexecute BRAG run was working resumed a finished MYCO
        # mission instead.
        working = (await db.execute(query.where(Task.status.in_(_IN_FLIGHT)).order_by(Task.created_at.desc())
                                    .limit(1))).scalars().first()
        if working is not None:
            return {"error": f"\"{working.title[:120]}\" is still being worked on and carries on by itself between "
                             "rounds, so nothing was resumed. Tell Richard that.", "task_id": str(working.id),
                    "title": working.title}
        task = _best_to_resume((await db.execute(
            query.where(Task.status.in_(RESUMABLE)).order_by(Task.created_at.desc()).limit(50))).scalars().all())
    if task is None:
        return {"error": "There is no paused mission to carry on with."}
    try:
        return {**await queue_resume(db, task, operator=str(user_id), reason="resumed by voice"),
                "title": task.title}
    except ValueError as exc:
        return {"error": f"{exc} It can only carry on when it has paused part-way.", "task_id": str(task.id)}


async def _start_mission(db: AsyncSession, user_id: UUID, instruction: str,
                         workspace_id: Optional[UUID]) -> Dict[str, Any]:
    """Start a mission in the workspace he named, or the one his words name (as heard), or ask which: never in
    whichever workspace was used last."""
    spaces = await _workspaces(db, user_id)
    if workspace_id is None:
        from app.core.command import workspace_choice

        held = [workspace_choice.holder(spaces, f) for f in workspace_choice.folders_in(instruction)]
        named = next((w for w in held if w is not None), None) or workspace_named_in(spaces, instruction)
        with_folders = [w for w in spaces if _root(w)]
        if named is not None:
            workspace_id = named.id
        elif len(with_folders) > 1:
            return {"error": "Ask Richard which workspace this is for: " + ", ".join(w.name for w in with_folders)
                             + "."}
    chosen = next((w for w in spaces if w.id == workspace_id), None)
    if chosen is not None and chosen.name.lower() not in instruction.lower():
        instruction = f"{instruction}\n(Workspace: {chosen.name})"
    return await engine.route(db, instruction, user_id=user_id, workspace_id=workspace_id)


async def run_tool(db: AsyncSession, user_id: UUID, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Carry out one tool call from the live conversation as the signed-in operator; audit-logged."""
    from app.core.audit import AuditLogger

    args = arguments if isinstance(arguments, dict) else {}
    if name == "list_workspaces":
        output: Dict[str, Any] = {"workspaces": [w.name for w in await _workspaces(db, user_id)]}
    elif name == "show_on_screen":
        output = await show_on_screen(db, user_id, args)
    elif name == "make_image":
        output = await _make_image(db, user_id, args)
    elif name == "research_web":
        from app.core.internet.research import research, research_card

        found = await research(str(args.get("question") or ""), str(args.get("depth") or "quick"),
                               None, args.get("time_range"))
        if not found.get("ok"):
            output = {"error": found.get("reason") or "The research found nothing."}
        else:
            output = {"answer": found["report"][:4000],
                      "sources": [f"[{s['n']}] {s['title']} ({s['url']})" for s in found["sources"]],
                      "card": research_card(found),
                      "note": "The answer and sources are on his screen now: tell him the answer in two or three "
                              "sentences and name the main source; do not read out the sources or the links."}
    elif name in ("list_workspace_files", "read_workspace_file"):
        output = await _workspace_files(db, user_id, str(args.get("workspace") or ""), args,
                                        read=name == "read_workspace_file")
    elif name == "get_mission":
        output = await _mission(db, user_id, args.get("task_id"))
    elif name == "resume_mission":
        output = await _resume(db, user_id, args.get("task_id"))
    elif name == "list_approvals":
        output = await _approvals(db, user_id)
    elif name == "trace_artifact":
        workspace_id, problem = await _resolve_workspace(db, user_id, args.get("workspace"))
        key = str(args.get("key") or "").strip()
        if problem:
            output = {"error": problem}
        elif not key:
            output = {"error": "Say which file, requirement or command to trace."}
        else:
            from app.core.graph import graph_service

            # A named workspace, or each of Richard's own workspaces in turn (never anyone else's).
            ids = [workspace_id] if workspace_id else [w.id for w in await _workspaces(db, user_id)]
            links: List[str] = []
            records = 0
            for wid in ids:
                trace = await graph_service.trace(db, wid, key)
                if trace["nodes"]:
                    records += len(trace["nodes"])
                    links += graph_service.describe(trace).splitlines()
            output = {"key": key, "links": links[:30] or ["Nothing is recorded for that yet."], "records": records}
    elif name in ("ask_jarv", "search_memory"):
        workspace_id, problem = await _resolve_workspace(db, user_id, args.get("workspace"))
        if problem:
            output = {"error": problem}
        elif name == "search_memory":
            query = str(args.get("query") or "").strip()
            output = {"memories": await _memories(db, user_id, query, workspace_id)} if query else \
                {"error": "Say what to look for."}
        else:
            question = str(args.get("question") or "").strip()
            output = await _ask_jarv(db, user_id, question, workspace_id) if question else \
                {"error": "The question is empty."}
    elif name in ("get_status", "start_mission", "cancel_mission"):
        workspace_id, problem = await _resolve_workspace(db, user_id, args.get("workspace"))
        if problem:
            output = {"error": problem}
        elif name == "get_status":
            output = await engine._status_reply(db, user_id, workspace_id)
        elif name == "cancel_mission":
            if not await richard_asked_to_cancel(user_id):
                output = {"error": "Richard did not ask to cancel anything, so nothing was cancelled. Only cancel a "
                                   "mission when he says to stop or cancel it."}
            else:
                output = await engine.route(db, "cancel the current mission", user_id=user_id,
                                            workspace_id=workspace_id)
        else:
            instruction = str(args.get("instruction") or "").strip()
            if not mission_brief_is_real(instruction):
                output = {"error": "That is not a task yet: ask Richard what the mission should do, and for which "
                                   "project, before starting it."}
            else:
                output = await _start_mission(db, user_id, instruction, workspace_id)
    else:
        raise LookupError(f"Unknown tool: {name}")
    await AuditLogger.log_system_event(
        db, action=TOOL_ACTION, result="error" if "error" in output else "ok", resource_type="voice",
        user_id=user_id, details={"tool": name, "arguments": {k: str(v)[:300] for k, v in args.items()},
                                  "intent": output.get("intent"), "task_id": output.get("task_id")})
    await db.commit()
    return output
