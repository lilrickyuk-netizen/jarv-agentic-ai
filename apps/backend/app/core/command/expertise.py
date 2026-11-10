"""
JAI Backend - Every specialist brings its trade to the work, and Richard says a thing once

Richard, 10 November: "if I'm the founder of a software development company, should I have to tell my marketing
employee how to market? ... I shouldn't have to send it big detailed prompts." That day the Marketing Lead was given
"find free places to market Plexecute" and needed a 200-word brief to do it well: JAI had 137 professional skills
(influencer-marketing, link-building and public-relations among them), a field-knowledge library and Richard's
corrections from that same afternoon, and none of it reached the agent doing the work. The skills made for the job
were not offered to the specialist, the one it was offered it opened once, the field knowledge sat behind a tool it
never called, and every correction Richard made was forgotten by the next mission.

So, before a specialist starts:
1. Richard's standing rules for the product are learned from what he writes (a small model separates "no podcasts",
   "Plexecute has not launched, so never claim customers" from one-off instructions such as "delete the Joe Wicks
   row") and kept as workspace rules, the first time from his recent briefs as well. He says a thing once.
2. JAI writes the job the way a senior specialist would set it out, from his request, the product's own description,
   his standing rules and the specialist's playbooks: deliverable, targets, method, quality bar and exclusions. His
   words always win; the job adds the professional standard he should not have to spell out. The requirements are
   derived from both, so the Verifier holds the work to that standard.
3. The playbooks the job needs (chosen from every skill of the specialist's trade) and its field knowledge go into
   the specialist's brief in full, instead of being listed for it to open if it thinks to.
No model is called in tests (they never spend provider credit): the job is then the request with the rules, and the
playbooks are chosen by matching the request against each skill's name and the phrases it is written for.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

PLAYBOOKS = 3              # skills loaded in full into the specialist's brief
PLAYBOOK_CHARS = 7000      # of each one (its opening sections: when to use it and how the work is done)
FIELD_TOPICS = 4           # field-knowledge topics given in full
MAX_RULES = 25             # standing rules shown for a workspace (most recent first)
HISTORY_BRIEFS = 12        # recent briefs read once per workspace to learn its rules from
RULE_TYPE = "richard_standing"
_LEARNED_FROM_HISTORY = "__learned_from_recent_briefs"

# The fields of knowledge each specialist draws on (its own first).
FIELDS: Dict[str, Sequence[str]] = {
    "marketing": ("marketing", "growth", "content", "community", "partnerships"),
    "sales": ("sales", "partnerships", "business"),
    "partnerships": ("partnerships", "sales", "marketing"),
    "research": ("research", "business", "analytics"),
    "finance": ("finance", "business", "analytics"),
    "business": ("business", "finance", "research"),
    "legal": ("legal",),
    "customer_support": ("customer_support", "onboarding"),
    "content": ("content", "marketing", "creation"),
    # The Lead Builder takes on every engineering role, so it draws on all of their fields.
    "builder": ("coding_agent", "debugging_agent", "qa", "devops", "security", "infrastructure", "documentation",
                "creation"),
}

_WORD = re.compile(r"[a-z0-9][a-z0-9'-]*")
_STOP = set("""a an and are as at be been but by can do does for from has have how i if in into is it its me my
not of on or our so than that the their them then there these they this to too us was we what when where which who
why will with you your please about any all also more most no very via just get make want need some each every
use used using user users wants mention mentions mentioned see also when skill skills help""".split())


def _stem(word: str) -> str:
    for suffix in ("ing", "ers", "er", "es", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def terms(text: str) -> set:
    return {_stem(w.strip("'-")) for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 1}


# ----- the specialist's playbooks ---------------------------------------------------------------------------------

def _front(text: str) -> Dict[str, str]:
    """A SKILL.md's frontmatter name and description."""
    match = re.match(r"\s*---\s*\n(.*?)\n---", text or "", re.S)
    out: Dict[str, str] = {}
    if match:
        for key in ("name", "description"):
            found = re.search(rf"^{key}:\s*(.+)$", match.group(1), re.M)
            if found:
                out[key] = found.group(1).strip().strip('"').strip("'")
    return out


def _body(text: str) -> str:
    return re.sub(r"\A\s*---\s*\n.*?\n---\s*\n", "", text or "", count=1, flags=re.S).strip()


def _skill_text(entry: Dict[str, Any]) -> str:
    from app.core.knowledge.skill_packs import packs_dir, skill_path

    path = packs_dir() / entry["pack"] / skill_path(entry) / "SKILL.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def trade_skills(specialist: str) -> List[Dict[str, Any]]:
    """Every skill of the specialist's trade that is installed and not blocked, one per name (the ones made for its
    missions first)."""
    from app.core.knowledge.skill_packs import SKILLS, blocked, skill_path

    refused = blocked()
    if specialist == "builder":  # the one builder is offered every skill made for missions
        mine = [e for e in SKILLS if e["sandbox"]]
    else:
        mine = [e for e in SKILLS if specialist in e["sandbox"]] + [
            e for e in SKILLS if specialist in e["agents"] and specialist not in e["sandbox"]]
    out, seen = [], set()
    for entry in mine:
        if entry["skill"] in seen or f"{entry['pack']}/{skill_path(entry)}" in refused:
            continue
        seen.add(entry["skill"])
        out.append(entry)
    return out


def _phrases(description: str) -> List[str]:
    """The phrases a skill says it is for ('creator partnerships,' 'guest posting,' ...)."""
    return [p.strip(" ,.") for p in re.findall(r"['‘“\"]([^'’”\"]{3,60})['’”\"]",
                                               description or "")]


def score(entry: Dict[str, Any], wanted: set, description: str) -> float:
    """How well a skill fits the work: its name, then the phrases it is written for, then its description."""
    points = 3.0 * len(terms(entry["skill"].replace("-", " ")) & wanted)
    for phrase in _phrases(description):
        words = terms(phrase)
        if words and words <= wanted:
            points += 2.0 * len(words)
    points += min(3.0, 0.5 * len(terms(description) & wanted))
    return points


# The Lead Builder's playbooks when the brief's words pick none: how it builds, debugs and proves its work.
BUILDER_CORE = ("test-driven-development", "systematic-debugging", "verification-before-completion")
BUILDER_MATCH = 5.0   # a builder skill must fit the brief by more than one shared word ("builder" in its name)


def choose_skills(specialist: str, work: str, starting: Sequence[str] = (), k: int = PLAYBOOKS,
                  minimum: float = 3.0) -> List[str]:
    """The playbooks this piece of work needs, best first: matched against the work, the specialist's usual
    starting skills breaking ties; the starting skills when nothing matches."""
    wanted = terms(work)
    ranked = []
    entries = trade_skills(specialist)
    if specialist == "builder":  # for software work, the engineering roles' skills (not the marketing ones it lists)
        entries = [e for e in entries if set(FIELDS["builder"]) & set(e["sandbox"])]
    for entry in entries:
        description = _front(_skill_text(entry)).get("description", "")
        points = score(entry, wanted, description) + (0.5 if entry["skill"] in starting else 0.0)
        ranked.append((points, entry["skill"]))
    ranked.sort(key=lambda item: -item[0])
    chosen = [name for points, name in ranked if points >= minimum][:k]
    names = {name for _, name in ranked}
    chosen += [name for name in starting if name in names and name not in chosen]
    return chosen[:k]


def catalogue(specialist: str) -> str:
    """The specialist's skills, one line each, for the model that sets out the job."""
    lines = []
    for entry in trade_skills(specialist):
        description = _front(_skill_text(entry)).get("description", "")
        first = re.split(r"(?<=[.!?])\s", description, maxsplit=1)[0] if description else ""
        lines.append(f"- {entry['skill']}: {first[:220]}")
    return "\n".join(lines)


def playbook(name: str, specialist: str, chars: int = PLAYBOOK_CHARS) -> str:
    for entry in trade_skills(specialist):
        if entry["skill"] == name:
            body = _body(_skill_text(entry))
            if len(body) > chars:
                cut = body.rfind("\n## ", 0, chars)
                body = body[: cut if cut > chars // 2 else chars].rstrip() + (
                    f"\n\n(The rest of this playbook: invoke_skill {name}.)")
            return body
    return ""


# ----- field knowledge --------------------------------------------------------------------------------------------

def field_knowledge(specialist: str, work: str, k: int = FIELD_TOPICS) -> List[Dict[str, Any]]:
    """The library's topics for the specialist's fields that bear on the work (its own field first on a tie)."""
    from app.core.knowledge.library import library_entries

    fields = list(FIELDS.get(specialist, (specialist,)))
    wanted = terms(work)
    ranked = []
    for entry in library_entries():
        if entry["agent_name"] not in fields:
            continue
        points = (3 * len(terms(" ".join(entry.get("keywords") or [])) & wanted)
                  + 2 * len(terms(entry["title"]) & wanted) + len(terms(entry["content"]) & wanted))
        if entry["agent_name"] == specialist:
            points += 1
        if points >= 3:
            ranked.append((points, entry))
    ranked.sort(key=lambda item: -item[0])
    return [entry for _, entry in ranked[:k]]


# ----- the product's own description ------------------------------------------------------------------------------

def product_file(workspace_root: Optional[str], name: str = "", chars: int = 8000) -> str:
    """The product's description from its folder (PLEXECUTE.md, README.md), as the job's facts."""
    if not workspace_root:
        return ""
    try:
        from app.core.workspaces import fs_inspector

        root = fs_inspector.host_to_container(workspace_root)
    except Exception:  # noqa: BLE001
        return ""
    if root is None or not root.is_dir():
        return ""
    letters = re.sub(r"[^a-z0-9]", "", (name or "").lower())

    def rank(path) -> tuple:
        stem = re.sub(r"[^a-z0-9]", "", path.stem.lower())
        named = bool(letters) and len(stem) >= 4 and (stem in letters or letters in stem)
        return (0 if named else 1 if stem == "readme" else 2, path.name)

    candidates = sorted((p for p in root.glob("*.md") if p.is_file()), key=rank)
    for path in candidates[:1]:
        try:
            return f"{path.name}:\n" + path.read_text(encoding="utf-8")[:chars]
        except OSError:
            return ""
    return ""


# ----- Richard's standing rules -----------------------------------------------------------------------------------

_RULES_PROMPT = (
    "Richard is the founder. Below is something he wrote to JAI, his AI company, about work for one of his "
    "products. Pick out only his STANDING rules: preferences and facts that should apply to all future work for "
    "this product (for example 'no podcasts', 'never claim customers: the product has not launched', 'nothing that "
    "costs money', 'always include the AI Coach and accountability calls', 'UK first'). Leave out instructions "
    "that only make sense for this one piece of work (delete a particular row, use a particular file, a word "
    "limit for this list). Write each rule as one short sentence in plain English. Answer with JSON only: "
    '{"rules": ["...", "..."]} and an empty list when there are none.\n\nWHAT HE WROTE:\n')


def _clean_rules(items: Any) -> List[str]:
    out = []
    for item in items or []:
        text = " ".join(str(item or "").split()).strip(" -")
        if 4 <= len(text) <= 300 and text.lower() not in {o.lower() for o in out}:
            out.append(text)
    return out[:10]


async def extract_rules(router, model: str, text: str) -> List[str]:
    """Richard's standing rules in what he wrote (a small model separates them from one-off instructions)."""
    from app.core.config import settings
    from app.core.providers.base import CompletionRequest, Message

    if getattr(settings, "TESTING", False) or not (text or "").strip():
        return []
    response = await router.complete(CompletionRequest(
        model=model, messages=[Message(role="user", content=_RULES_PROMPT + text[:6000])],
        temperature=0.0, max_tokens=600))
    found = re.search(r"\{.*\}", response.content or "", re.S)
    return _clean_rules((json.loads(found.group(0)) or {}).get("rules")) if found else []


async def standing_rules(db, workspace_id: Optional[UUID]) -> List[str]:
    """The product's standing rules, most recent first."""
    if db is None or workspace_id is None:
        return []
    from sqlalchemy import select

    from app.models.workspace_rules import WorkspaceRule

    rows = (await db.execute(select(WorkspaceRule).where(
        WorkspaceRule.workspace_id == workspace_id, WorkspaceRule.rule_type == RULE_TYPE,
        WorkspaceRule.is_active.is_(True)).order_by(WorkspaceRule.created_at.desc()))).scalars().all()
    return [str((r.rule_content or {}).get("text") or r.description or "") for r in rows
            if r.rule_name != _LEARNED_FROM_HISTORY][:MAX_RULES]


def _same(a: str, b: str) -> bool:
    ta, tb = terms(a), terms(b)
    return bool(ta and tb) and len(ta & tb) / max(1, min(len(ta), len(tb))) >= 0.8


async def save_rules(db, workspace_id: UUID, rules: List[str], *, source: str,
                     task_id: Optional[UUID] = None) -> List[str]:
    """Keep the rules not already held (by meaning, roughly); returns the ones added."""
    from app.models.workspace_rules import WorkspaceRule

    held = await standing_rules(db, workspace_id)
    added = []
    for text in rules:
        if any(_same(text, old) for old in held + added):
            continue
        db.add(WorkspaceRule(id=uuid4(), workspace_id=workspace_id, rule_name=text[:255], rule_type=RULE_TYPE,
                             description=text, rule_content={"text": text, "source": source,
                                                             "task_id": str(task_id) if task_id else None},
                             is_active=True, priority=3, meta_data={"learned_by": "expertise"}))
        added.append(text)
    if added:
        await db.flush()
    return added


async def learn(router, model: str, db, workspace_id: Optional[UUID], brief: str,
                task_id: Optional[UUID] = None) -> List[str]:
    """Learn the standing rules in this brief and, the first time for a workspace, in its recent briefs."""
    from app.core.config import settings

    if db is None or workspace_id is None or getattr(settings, "TESTING", False):
        return []
    from sqlalchemy import select

    from app.core.command.work_type import richard_brief
    from app.models.task import Task
    from app.models.workspace_rules import WorkspaceRule

    added: List[str] = []
    try:
        seen = (await db.execute(select(WorkspaceRule.id).where(
            WorkspaceRule.workspace_id == workspace_id,
            WorkspaceRule.rule_name == _LEARNED_FROM_HISTORY))).first()
        if seen is None:
            query = select(Task.description).where(Task.workspace_id == workspace_id, Task.description.isnot(None))
            if task_id is not None:
                query = query.where(Task.id != task_id)
            earlier = (await db.execute(query.order_by(Task.created_at.desc()).limit(HISTORY_BRIEFS))).scalars().all()
            history = "\n\n---\n\n".join(richard_brief(str(d))[:1500] for d in earlier if d)
            if history.strip():
                added += await save_rules(db, workspace_id, await extract_rules(router, model, history),
                                          source="Richard's recent briefs")
            db.add(WorkspaceRule(id=uuid4(), workspace_id=workspace_id, rule_name=_LEARNED_FROM_HISTORY,
                                 rule_type=RULE_TYPE, description="Recent briefs read for standing rules",
                                 rule_content={"text": ""}, is_active=False, priority=9))
        added += await save_rules(db, workspace_id, await extract_rules(router, model, richard_brief(brief)),
                                  source="Richard's brief", task_id=task_id)
    except Exception as exc:  # noqa: BLE001 - the mission runs with the rules it already has
        logger.info(f"standing rules not learned: {exc}")
    return added


# ----- the job, set out as a senior specialist would -------------------------------------------------------------

_JOB_SYSTEM = (
    "You are JAI's {role}, a senior professional in your field, working for Richard, a busy non-technical founder. "
    "He gives you requests the way a founder briefs an experienced employee: often one line. Set out the job as you "
    "would for yourself before starting, to a professional standard: the deliverable (file name and layout in the "
    "product's folder), sensible targets (how many of what), the method a professional uses (where to look and in "
    "what order, what to check before adding anything), the quality bar, and what to leave out. Keep to everything "
    "Richard wrote and to his standing rules: his words always win. Use only facts about the product from its own "
    "description. Contact, send, post, publish and spend nothing: drafts and lists only, for Richard to use. "
    "Aim at the product's own customers and the people who reach them (creators, blogs, newsletters, communities "
    "and partner businesses in its field), not at founders or the startup trade, unless he asks for that; his "
    "recent requests for the product say what he is after. A list is one .xlsx workbook in the product's folder "
    "with a sheet per kind of entry; a document is .md or .docx. Targets are aims for about an hour's work. Never "
    "make an entry earn its place by passing every check: an entry goes in with a column saying what is still to "
    "check, and only paid, closed or off-topic ones are left out. Pick "
    "up to {k} of your skills (by their exact names) whose method the job needs. Answer with JSON only: "
    '{{"job": "<the job, at most 300 words, in plain sentences>", "skills": ["<skill>", ...]}}')


async def _recent_requests(db, workspace_id: Optional[UUID], task_id: Optional[UUID], limit: int = 6) -> str:
    """Richard's last few requests for the product, in his words, so a one-line request is read the way he means
    it (10 November: "find free places to market Plexecute" came an hour after he asked for blogs, creators and
    partnerships, and the job was written for startup directories)."""
    if db is None or workspace_id is None:
        return ""
    try:
        from sqlalchemy import select

        from app.core.command.work_type import richard_brief
        from app.models.task import Task

        query = select(Task.description).where(Task.workspace_id == workspace_id, Task.description.isnot(None))
        if task_id is not None:
            query = query.where(Task.id != task_id)
        rows = (await db.execute(query.order_by(Task.created_at.desc()).limit(limit))).scalars().all()
        return "\n".join(f"- {' '.join(richard_brief(str(r)).split())[:400]}" for r in rows if r)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"recent requests unavailable: {exc}")
        return ""


@dataclass
class Job:
    specialist: str
    text: str = ""                      # the job as the specialist set it out ("" when only the request stands)
    skills: List[str] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    learned: List[str] = field(default_factory=list)   # rules learned this time
    knowledge: List[Dict[str, Any]] = field(default_factory=list)
    tokens: int = 0

    def requirement_guidance(self) -> str:
        """For the requirements analyst: the job and the rules, so the professional standard is checked too."""
        parts = []
        if self.text:
            parts.append(f"THE JOB AS JAI'S SPECIALIST SET IT OUT (from Richard's request):\n{self.text}")
        if self.rules:
            parts.append("RICHARD'S STANDING RULES FOR THIS PRODUCT (every one applies):\n"
                         + "\n".join(f"- {r}" for r in self.rules))
        return "\n\n".join(parts)

    def brief_for_team(self) -> str:
        """For everyone on the mission, the Verifier included."""
        return self.requirement_guidance()

    def brief_for_specialist(self) -> str:
        """The specialist's own playbooks and field knowledge, in full."""
        parts = []
        books = [(name, playbook(name, self.specialist)) for name in self.skills]
        books = [(name, text) for name, text in books if text]
        if books:
            parts.append("YOUR PLAYBOOKS FOR THIS JOB (your trade's method: follow them):\n" + "\n\n".join(
                f"=== {name} ===\n{text}" for name, text in books))
        if self.knowledge:
            parts.append("YOUR FIELD KNOWLEDGE THAT BEARS ON THIS JOB:\n" + "\n".join(
                f"- {t['title']} ({t['source_title']}, {t['url']}): {t['content']}" for t in self.knowledge))
        return "\n\n".join(parts)


async def job_for(router, model: str, mission: str, specialist: str, *, starting: Sequence[str] = (),
                  workspace_root: Optional[str] = None, workspace_name: str = "", db=None,
                  workspace_id: Optional[UUID] = None, task_id: Optional[UUID] = None, rules_model: str = "",
                  set_out: bool = True) -> Job:
    """The job for a specialist: Richard's standing rules (learned first), the job set out to a professional
    standard (set_out, for new work), the playbooks it needs and the field knowledge that bears on it. Never raises:
    without it the specialist still has Richard's request."""
    from app.core.command.mission_org import SPECIALISTS
    from app.core.command.work_type import richard_brief

    job = Job(specialist=specialist)
    request = richard_brief(mission)
    try:
        job.learned = await learn(router, rules_model or model, db, workspace_id, mission, task_id)
        job.rules = await standing_rules(db, workspace_id)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"standing rules unavailable: {exc}")
    from app.core.config import settings

    if set_out and not getattr(settings, "TESTING", False):
        try:
            from app.core.providers.base import CompletionRequest, Message

            role = SPECIALISTS.get(specialist, {}).get("title", "specialist")
            facts = product_file(workspace_root, workspace_name)
            recent = await _recent_requests(db, workspace_id, task_id)
            prompt = (f"RICHARD'S REQUEST:\n{request[:6000]}\n\n"
                      + (f"HIS RECENT REQUESTS FOR THIS PRODUCT (newest first):\n{recent}\n\n" if recent else "")
                      + ("HIS STANDING RULES FOR THIS PRODUCT:\n" + "\n".join(f"- {r}" for r in job.rules) + "\n\n"
                         if job.rules else "")
                      + (f"THE PRODUCT'S OWN DESCRIPTION ({facts[:12000]})\n\n" if facts else "")
                      + f"YOUR SKILLS:\n{catalogue(specialist)}\n\nSet out the job now.")
            response = await router.complete(CompletionRequest(
                model=model, messages=[Message(role="user", content=prompt)],
                system=_JOB_SYSTEM.format(role=role, k=PLAYBOOKS), temperature=0.2, max_tokens=1500))
            job.tokens = int((response.usage or {}).get("total_tokens", 0) or 0)
            found = re.search(r"\{.*\}", response.content or "", re.S)
            data = json.loads(found.group(0)) if found else {}
            job.text = " ".join(str(data.get("job") or "").split())[:3000]
            names = {e["skill"] for e in trade_skills(specialist)}
            job.skills = [s for s in (data.get("skills") or []) if s in names][:PLAYBOOKS]
        except Exception as exc:  # noqa: BLE001 - the request alone still runs
            logger.info(f"job not set out: {exc}")
    work = " ".join([request, job.text])
    if not job.skills and specialist == "builder":
        job.skills = choose_skills(specialist, work, starting or BUILDER_CORE, minimum=BUILDER_MATCH)
    elif not job.skills:
        job.skills = choose_skills(specialist, work, starting)
    try:
        job.knowledge = field_knowledge(specialist, work)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"field knowledge unavailable: {exc}")
    return job
