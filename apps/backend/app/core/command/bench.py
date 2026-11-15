"""
JAI Backend - The bench: small fixed jobs from Richard's real missions, run the way Richard runs a mission, scored
in code

Richard, 14 November: "I am not running any missions and wasting my money until every problem is fixed." Every
change to how a mission is done is proved here first. Each job is one of Richard's own kinds of mission, cut down so
it costs at most its allowance (£1 by default): the booking-partners database, free places to market Plexecute, an
investor list, a partnership job that needs a second specialist, and a mission cancelled part-way.

A job goes the whole real way: CommandService.submit (JAI reads the request, chooses the workspace and the
specialist), the worker runs it (the specialist on the mission engine, the requirement list, the independent
Verifier, the report, the automatic rounds), and the result is read from the mission's own record and from the
files in its folder. The scores are worked out here, in code, from those files: rows counted, cells really filled,
every email checked against the business's own website, every address the work gives tried on the web. Nothing a
model says about its own work is taken as a score.

The jobs work in their own folder (Projects\\_jai_bench\\<job>), made fresh for each run; nothing else of Richard's
is read or changed. Each job's allowance is enforced by the mission itself and, as a hard stop, by the bench, which
cancels a job whose spend passes it. Nothing is sent, posted or published by any job.

    python -m app.core.command.bench                 every job
    python -m app.core.command.bench booking cancel  the jobs named
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

FOLDER = "_jai_bench"
SLUG = "jai-bench"
GBP_PER_USD = 0.78
ALLOWANCE_GBP = 1.0
POLL_SECONDS = 10
JOB_MINUTES = 35          # a job still working after this is cancelled and scored as it stands
SETTLED_SECONDS = 180     # a mission left waiting to carry on, with no change for this long, has ended its run
HARD_STOP = 1.15          # the bench cancels a job whose spend passes its allowance by this much


@dataclass
class Job:
    name: str
    title: str
    request: Callable[[str], str]
    score: Callable[["Outcome"], List["Check"]]
    cancel_after_seconds: Optional[int] = None  # the cancel job: cancelled once it has started writing


@dataclass
class Check:
    what: str
    passed: bool
    detail: str = ""


@dataclass
class Outcome:
    job: str
    task_id: str = ""
    status: str = ""
    verified: bool = False
    engine: str = ""
    specialist: str = ""
    delegated: List[Dict[str, str]] = field(default_factory=list)
    child_tasks: int = 0
    minutes: float = 0.0
    cost_usd: float = 0.0
    stopped_by_bench: str = ""
    unmet: List[str] = field(default_factory=list)
    answer: str = ""
    folder: Optional[Path] = None
    cancelled_at: Optional[float] = None
    checks: List[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)


# ----- reading what a job made -------------------------------------------------------------------------------------

def _sheets(folder: Optional[Path], name: str) -> List[Dict[str, Any]]:
    """The workbook a job was asked for (by name, else the newest workbook in its folder), as sheets of rows."""
    from app.core.agents.workspace_ops import xlsx_read

    if folder is None or not folder.is_dir():
        return []
    wanted = [p for p in folder.rglob("*.xlsx") if p.name.lower() == name.lower()]
    found = wanted or sorted(folder.rglob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in found:
        try:
            return xlsx_read(path.read_bytes())
        except Exception:  # noqa: BLE001 - an unreadable workbook is scored as no workbook
            continue
    return []


def _column(header: List[Any], *words: str) -> Optional[int]:
    for word in words:
        for number, cell in enumerate(header):
            if word in str(cell or "").lower():
                return number
    return None


def table(sheets: List[Dict[str, Any]], name_words: tuple) -> Dict[str, Any]:
    """The workbook's main list: the sheet with most rows whose header names its entries. {"header", "rows",
    "sheet"}; empty when there is none."""
    best: Dict[str, Any] = {"header": [], "rows": [], "sheet": ""}
    for sheet in sheets:
        rows = [r for r in (sheet.get("rows") or []) if any(str(c or "").strip() for c in r)]
        if len(rows) < 2:
            continue
        header = [str(c or "").strip().lower() for c in rows[0]]
        if _column(header, *name_words) is None:
            continue
        if len(rows) - 1 > len(best["rows"]):
            best = {"header": header, "rows": rows[1:], "sheet": sheet.get("name", "")}
    return best


def cell(row: List[Any], column: Optional[int]) -> str:
    from app.core.agents.workspace_ops import unfilled

    if column is None or column >= len(row):
        return ""
    value = str(row[column] if row[column] is not None else "").strip()
    return "" if unfilled(value) else value


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_URL = re.compile(r"https?://[^\s|,;\"'<>]+|(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:/[^\s|,;\"'<>]*)?",
                  re.I)


def first_url(text: str) -> str:
    found = _URL.search(text or "")
    if not found:
        return ""
    url = found.group(0).rstrip(".)")
    return url if url.lower().startswith("http") else f"https://{url}"


def email_matches_site(email_cell: str, website: str) -> Optional[bool]:
    """An email address belongs to the business when its domain is the business's own site (or a part of it).
    None when the cell holds no address."""
    from app.core.internet.contacts import site_of

    found = _EMAIL.search(email_cell or "")
    if not found or not website:
        return None
    return site_of("https://" + found.group(1)) == site_of(first_url(website) or website)


async def reachable(urls: List[str]) -> Dict[str, bool]:
    """Whether each address answers on the web: a site that exists answers, even with a refusal to robots; an
    address that was made up does not resolve, or its page is not found."""
    import httpx

    from app.core import internet

    async def one(client, url: str) -> bool:
        ok, _ = internet._ssrf_ok(url)
        if not ok:
            return False
        try:
            response = await client.get(url)
        except Exception:  # noqa: BLE001 - no answer is the answer
            return False
        return response.status_code < 500 and response.status_code not in (404, 410)

    out: Dict[str, bool] = {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/131.0 Safari/537.36"}
    async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=headers) as client:
        results = await asyncio.gather(*(one(client, u) for u in urls))
    for url, ok in zip(urls, results):
        out[url] = ok
    return out


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole}"


# ----- the jobs ----------------------------------------------------------------------------------------------------

def _common(outcome: Outcome) -> List[Check]:
    return [
        Check("ran on the Claude engine", outcome.engine == "claude",
              outcome.engine or "the engine did not run (JAI's own loop, or no specialist)"),
        Check("finished and passed JAI's independent check", outcome.status == "completed" and outcome.verified,
              f"status {outcome.status}, verified {outcome.verified}"
              + (f"; still open: {'; '.join(outcome.unmet[:3])}" if outcome.unmet else "")),
        Check("stayed within its £1 allowance", outcome.cost_usd <= _allowance_usd() * HARD_STOP,
              f"${outcome.cost_usd:.2f} (about £{outcome.cost_usd * GBP_PER_USD:.2f})"),
    ]


async def _score_contacts(outcome: Outcome, book: str, wanted: int, name_words: tuple) -> List[Check]:
    main = table(_sheets(outcome.folder, book), name_words)
    header, rows = main["header"], main["rows"]
    name = _column(header, *name_words)
    site = _column(header, "website", "site", "web", "url")
    phone = _column(header, "phone", "tel")
    email = _column(header, "email", "e-mail")
    source = _column(header, "source", "evidence", "checked")
    named = [r for r in rows if cell(r, name)]
    sites = [first_url(cell(r, site)) for r in named if first_url(cell(r, site))]
    contacts = [r for r in named if cell(r, phone) or _EMAIL.search(cell(r, email))]
    emails = [email_matches_site(cell(r, email), cell(r, site)) for r in named]
    emails = [e for e in emails if e is not None]
    sourced = [r for r in named if first_url(cell(r, source))]
    answers = await reachable(sites) if sites else {}
    live = sum(1 for ok in answers.values() if ok)
    return [
        Check(f"{book} lists at least {wanted}", len(named) >= wanted,
              f"{len(named)} in sheet '{main['sheet']}'" if main["sheet"] else f"no {book} with a list was found"),
        Check("every entry has its website", bool(named) and len(sites) == len(named), _share(len(sites), len(named))),
        Check("every website is real (it answers on the web)", bool(sites) and live == len(sites),
              _share(live, len(sites)) + ("" if live == len(sites) else ": not answering "
                                          + ", ".join(u for u, ok in answers.items() if not ok)[:300])),
        Check("at least 7 in 10 have a published phone or email",
              bool(named) and len(contacts) * 10 >= len(named) * 7, _share(len(contacts), len(named))),
        Check("no email is guessed: each is on the business's own domain",
              all(emails), f"{sum(emails)} of {len(emails)} emails match their website"),
        Check("every entry has its source page", bool(named) and len(sourced) == len(named),
              _share(len(sourced), len(named))),
    ]


async def _score_places(outcome: Outcome, book: str, wanted: int, name_words: tuple, route_words: tuple
                        ) -> List[Check]:
    main = table(_sheets(outcome.folder, book), name_words)
    header, rows = main["header"], main["rows"]
    name = _column(header, *name_words)
    site = _column(header, "url", "website", "address", "link", "site")
    route = _column(header, *route_words)
    source = _column(header, "source", "checked", "evidence")
    named = [r for r in rows if cell(r, name)]
    urls = [first_url(cell(r, site)) for r in named if first_url(cell(r, site))]
    routed = [r for r in named if cell(r, route)]
    sourced = [r for r in named if first_url(cell(r, source)) or first_url(cell(r, site))]
    answers = await reachable(urls) if urls else {}
    live = sum(1 for ok in answers.values() if ok)
    from app.core.internet.contacts import site_of

    distinct = len({site_of(u) for u in urls})
    return [
        Check(f"{book} lists at least {wanted}", len(named) >= wanted,
              f"{len(named)} in sheet '{main['sheet']}'" if main["sheet"] else f"no {book} with a list was found"),
        Check("every entry has its address", bool(named) and len(urls) == len(named), _share(len(urls), len(named))),
        Check("every address is real (it answers on the web)", bool(urls) and live == len(urls),
              _share(live, len(urls)) + ("" if live == len(urls) else ": not answering "
                                         + ", ".join(u for u, ok in answers.items() if not ok)[:300])),
        Check("no entry is listed twice", distinct == len(urls), f"{distinct} different sites"),
        Check("each says how to take part (what is allowed, how to post or pitch)",
              bool(named) and len(routed) == len(named), _share(len(routed), len(named))),
        Check("each has the page it was checked on", bool(named) and len(sourced) == len(named),
              _share(len(sourced), len(named))),
    ]


def _folder_line(folder: str) -> str:
    return f"Work in {folder} and save everything there."


def _booking(folder: str) -> str:
    return (f"{_folder_line(folder)} Build partners.xlsx: 10 UK restaurant or café chains that could become "
            "booking partners for Plexecute (a productivity app that books time for what matters). For each: the "
            "company, its website, its published phone number, its published email address, its official contact "
            "or partnership page, and the source page for each detail. Only details the business publishes itself; "
            "never guess an email address.")


def _places(folder: str) -> str:
    return (f"{_folder_line(folder)} Find 8 free places to promote Plexecute, a productivity app, before its "
            "launch: communities, directories and launch sites where posting costs nothing. Save them in "
            "free-places.xlsx with each place's name, its address (URL), what is allowed there and how to post, and "
            "the page you checked that on. Nothing paid, and no podcasts.")


def _investors(folder: str) -> str:
    return (f"{_folder_line(folder)} List 6 UK investors (angel investors, angel networks or seed funds) who back "
            "early-stage consumer apps like Plexecute, a productivity app. Save investors.xlsx with each one's "
            "name, website, what they invest in (stage, and the typical cheque if they publish it), their published "
            "way to pitch (a form, page or email on their own site) and the source page. Published contacts only.")


def _team(folder: str) -> str:
    return (f"{_folder_line(folder)} Partnerships: find 5 UK co-working chains that could partner with Plexecute, a "
            "productivity app, with each one's website, its published partnership or business contact and the "
            "source page, in partners.xlsx. Then have JAI's Sales Lead write a short, friendly first email to each "
            "into outreach.md, using only what partners.xlsx says about them. Drafts only: send nothing.")


def _long(folder: str) -> str:
    return (f"{_folder_line(folder)} Build chains.xlsx: 40 UK restaurant chains with each one's website, published "
            "phone number, published email address and the source page for each detail. Only details the business "
            "publishes itself.")


async def score_booking(outcome: Outcome) -> List[Check]:
    return _common(outcome) + await _score_contacts(outcome, "partners.xlsx", 10, ("company", "chain", "name",
                                                                                   "business"))


async def score_places(outcome: Outcome) -> List[Check]:
    return _common(outcome) + await _score_places(outcome, "free-places.xlsx", 8, ("place", "name", "community",
                                                                                   "site", "platform"),
                                                  ("allowed", "how", "rule", "post", "format"))


async def score_investors(outcome: Outcome) -> List[Check]:
    return _common(outcome) + await _score_places(outcome, "investors.xlsx", 6, ("investor", "name", "fund",
                                                                                 "network"),
                                                  ("pitch", "apply", "contact", "form", "route", "how"))


async def score_team(outcome: Outcome) -> List[Check]:
    checks = _common(outcome) + (await _score_contacts(outcome, "partners.xlsx", 5, ("company", "chain", "name",
                                                                                     "operator", "brand")))[:3]
    names = [cell(r, _column(table(_sheets(outcome.folder, "partners.xlsx"), ("company", "chain", "name")
                                   )["header"], "company", "chain", "name"))
             for r in table(_sheets(outcome.folder, "partners.xlsx"), ("company", "chain", "name"))["rows"]]
    names = [n for n in names if n]
    drafts = ""
    if outcome.folder is not None and outcome.folder.is_dir():
        found = [p for p in outcome.folder.rglob("*.md") if "outreach" in p.name.lower()]
        drafts = found[0].read_text(errors="replace") if found else ""
    covered = [n for n in names if n.split()[0].lower() in drafts.lower()]
    checks += [
        Check("outreach.md has a first email for each partner", bool(names) and len(covered) == len(names),
              _share(len(covered), len(names)) if drafts else "outreach.md was not written"),
        Check("a second specialist did part of the work",
              bool(outcome.delegated) or outcome.child_tasks > 0,
              ("handed to " + ", ".join(d.get("to") or "a colleague" for d in outcome.delegated))
              if outcome.delegated else (f"split into {outcome.child_tasks} missions" if outcome.child_tasks
                                         else "one specialist did it all")),
    ]
    return checks


async def score_cancel(outcome: Outcome) -> List[Check]:
    late: List[str] = []
    if outcome.folder is not None and outcome.folder.is_dir() and outcome.cancelled_at is not None:
        late = [p.name for p in outcome.folder.rglob("*")
                if p.is_file() and ".jai" not in p.parts and p.stat().st_mtime > outcome.cancelled_at + 20]
    return [
        Check("the mission was cancelled while it worked", outcome.cancelled_at is not None,
              "cancelled" if outcome.cancelled_at is not None else "it ended before the bench could cancel it"),
        Check("it shows as cancelled", outcome.status == "cancelled", f"status {outcome.status}"),
        Check("nothing was written after the cancel", not late, ", ".join(late)[:300] or "no file changed"),
        Check("it spent little", outcome.cost_usd <= _allowance_usd() * HARD_STOP,
              f"${outcome.cost_usd:.2f} (about £{outcome.cost_usd * GBP_PER_USD:.2f})"),
    ]


JOBS: Dict[str, Job] = {
    "booking": Job("booking", "Booking partners with published contacts", _booking, score_booking),
    "places": Job("places", "Free places to market Plexecute", _places, score_places),
    "investors": Job("investors", "UK investors with their pitch routes", _investors, score_investors),
    "team": Job("team", "Partners found, emails drafted by a second specialist", _team, score_team),
    "cancel": Job("cancel", "A mission cancelled part-way stops", _long, score_cancel, cancel_after_seconds=150),
}


# ----- running a job the way Richard does --------------------------------------------------------------------------

def _allowance_usd() -> float:
    return round(ALLOWANCE_GBP / GBP_PER_USD, 2)


def _host_folder(name: str = "") -> str:
    from app.core.config import settings

    root = str(settings.WORKSPACE_HOST_ROOT).rstrip("\\/")
    windows = "\\" in root or ":" in root[:3]
    sep = "\\" if windows else "/"
    return sep.join(p for p in (root, FOLDER, name) if p)


async def _workspace(db) -> tuple:
    """Richard's user and the bench workspace (made on the first run)."""
    from uuid import uuid4

    from sqlalchemy import select

    from app.models.user import User
    from app.models.workspace import Workspace

    user = (await db.execute(select(User).where(User.is_active.is_(True))
                             .order_by(User.is_admin.desc(), User.created_at.asc()))).scalars().first()
    if user is None:
        raise RuntimeError("No user to own the bench workspace.")
    workspace = (await db.execute(select(Workspace).where(Workspace.slug == SLUG))).scalars().first()
    if workspace is None:
        workspace = Workspace(id=uuid4(), name="JAI bench", slug=SLUG, owner_id=user.id,
                              description="Where each change to JAI is proved on small fixed jobs before Richard "
                                          "runs a mission.", workspace_type="business", authority_level=3,
                              is_active=True, config={"root_path": _host_folder()})
        db.add(workspace)
    else:
        workspace.config = {**(workspace.config or {}), "root_path": _host_folder()}
    await db.commit()
    return user, workspace


async def _live_cost(task_id: str) -> float:
    from app.core.command import mission_budget, progress

    record = await progress.load(task_id) or {}
    live = float(((record.get("usage") or {}).get("cost_usd")) or 0)
    return max(live, await mission_budget.spent(task_id))


async def _cancel(task_id: str, why: str) -> bool:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.core.runtime.missions import cancel_mission
    from app.models.task import Task

    async with AsyncSessionLocal() as db:
        task = (await db.execute(select(Task).where(Task.id == UUID(task_id)))).scalar_one_or_none()
        if task is None:
            return False
        done = await cancel_mission(db, task, actor="bench", reason=why)
        await db.commit()
        return done


def _files_written(folder: Path) -> bool:
    return folder.is_dir() and any(p.is_file() and ".jai" not in p.parts for p in folder.rglob("*"))


async def _missions(workspace_id, since: datetime) -> List[Any]:
    """Every mission this job started: its own, and any the Orchestrator split it into (in the bench workspace,
    since the job began)."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.task import Task

    async with AsyncSessionLocal() as db:
        return list((await db.execute(select(Task).where(Task.workspace_id == workspace_id, Task.created_at >= since)
                                      .order_by(Task.created_at))).scalars().all())


def _split(own: str) -> bool:
    """The job's own mission ended by handing its work to the Orchestrator's steps (seen on its record)."""
    return _SPLIT.get(own, False)


_SPLIT: Dict[str, bool] = {}


def _result_of(task: Any) -> Dict[str, Any]:
    result = task.result if isinstance(task.result, dict) else {}
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    role = result.get("role") if isinstance(result.get("role"), dict) else {}
    engine = role.get("engine") if isinstance(role.get("engine"), dict) else {}
    return {"result": result, "verified": bool(verification.get("verified")),
            "unmet": [str(u)[:200] for u in (verification.get("unmet") or [])], "role": role, "engine": engine}


async def run_job(job: Job, say: Callable[[str], None] = print) -> Outcome:
    from app.core.command import mission_budget
    from app.core.command.service import CommandService
    from app.core.database import AsyncSessionLocal
    from app.core.runtime import lifecycle
    from app.core.runtime.dispatcher import dispatch_mission
    from app.core.workspaces import fs_inspector

    outcome = Outcome(job=job.name)
    host = _host_folder(job.name)
    folder = fs_inspector.host_to_container(host)
    if folder is None:
        outcome.answer = f"{host} is not inside JAI's workspaces."
        outcome.checks = [Check("the bench folder is inside JAI's workspaces", False, host)]
        return outcome
    shutil.rmtree(folder, ignore_errors=True)  # the bench's own job folder, made fresh for each run
    folder.mkdir(parents=True)
    outcome.folder = folder
    started = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        user, workspace = await _workspace(db)
        workspace_id = workspace.id
        submitted = await CommandService().submit(command_text=job.request(host), db=db, workspace_id=workspace_id,
                                                  operator=str(user.id), user_id=user.id)
        await db.commit()
    outcome.task_id = submitted.task_id
    say(f"   mission {submitted.task_id[:8]}: {submitted.status}")
    if submitted.status != lifecycle.QUEUED:
        outcome.status = submitted.status
        outcome.answer = submitted.approval_reason or submitted.response_text[:600]
        outcome.checks = await job.score(outcome)
        return outcome
    await mission_budget.set_allowance(submitted.task_id, _allowance_usd())
    await dispatch_mission(submitted.task_id, reason="bench")

    clock = asyncio.get_event_loop().time
    seen: Dict[str, str] = {}
    last_change = clock()
    allowanced = {submitted.task_id}
    while True:
        await asyncio.sleep(POLL_SECONDS)
        missions = await _missions(workspace_id, started)
        states = {str(t.id): lifecycle.normalise(t.status) for t in missions}
        for t in missions:
            if str(t.id) == submitted.task_id and isinstance(t.result, dict):
                _SPLIT[submitted.task_id] = bool(t.result.get("workflow") or t.result.get("workflow_run_id")
                                                 or "Orchestrator has split" in str(t.result.get("response") or ""))
        for task_id in states:
            if task_id not in allowanced:  # a step the Orchestrator started: the same £1 allowance each
                await mission_budget.set_allowance(task_id, _allowance_usd())
                allowanced.add(task_id)
        if states != seen:
            last_change = clock()
            for task_id, state in states.items():
                if seen.get(task_id) != state:
                    say(f"   {datetime.now(timezone.utc):%H:%M:%S} mission {task_id[:8]} {state}")
            seen = dict(states)
        cost = sum([await _live_cost(t) for t in states])
        minutes = (datetime.now(timezone.utc) - started).total_seconds() / 60
        working = [t for t, st in states.items() if st in (lifecycle.PENDING, lifecycle.QUEUED, lifecycle.RUNNING,
                                                            lifecycle.RECOVERING)]
        if job.cancel_after_seconds is not None and outcome.cancelled_at is None and working \
                and (clock() - last_change > job.cancel_after_seconds or _files_written(folder)):
            for task_id in working:
                await _cancel(task_id, "the bench's cancel job")
            outcome.cancelled_at = datetime.now(timezone.utc).timestamp()
            say(f"   cancelled at {datetime.now(timezone.utc):%H:%M:%S}; watching that nothing more is written")
            await asyncio.sleep(75)
            continue
        # A split mission's next step is started by the workflow tick (once a minute): a split job is given time
        # for it; a mission waiting to be carried on is given time for its automatic round.
        quiet = SETTLED_SECONDS if (len(states) > 1 or any(st == lifecycle.NEEDS_CONTINUATION
                                                           for st in states.values())
                                    or _split(submitted.task_id)) else 2 * POLL_SECONDS
        if not working and clock() - last_change > quiet:
            break  # every mission the job started has ended its run (or waits for Richard, or to be carried on)
        if cost > _allowance_usd() * HARD_STOP * max(1, len(states)):
            outcome.stopped_by_bench = f"spent ${cost:.2f}, past its allowance: the bench cancelled it"
            break
        if minutes > JOB_MINUTES:
            outcome.stopped_by_bench = f"still working after {JOB_MINUTES} minutes: the bench cancelled it"
            break

    missions = await _missions(workspace_id, started)
    for task in missions:
        if lifecycle.normalise(task.status) in lifecycle.IN_FLIGHT:
            # A bench job never carries on later by itself.
            await _cancel(str(task.id), outcome.stopped_by_bench or "bench job scored; not to be carried on")
    missions = await _missions(workspace_id, started)
    own = next((t for t in missions if str(t.id) == submitted.task_id), None)
    steps = [t for t in missions if str(t.id) != submitted.task_id]
    worked = steps or ([own] if own is not None else [])  # a split mission's work is done by its steps
    reads = [_result_of(t) for t in worked]
    states = [lifecycle.normalise(t.status) for t in worked]
    outcome.child_tasks = len(steps)
    outcome.status = (lifecycle.COMPLETED if states and all(s == lifecycle.COMPLETED for s in states) else
                      next((s for s in states if s != lifecycle.COMPLETED), "")) if states else ""
    outcome.verified = bool(reads) and all(r["verified"] for r in reads)
    outcome.unmet = [u for r in reads for u in r["unmet"]][:8]
    engines = [r["engine"].get("name") for r in reads if r["engine"].get("name")]
    outcome.engine = "claude" if engines and len(engines) == len(reads) and set(engines) == {"claude"} else \
        ",".join(dict.fromkeys(engines))
    outcome.delegated = [d for r in reads for d in (r["engine"].get("delegated") or [])]
    outcome.specialist = ", ".join(dict.fromkeys(str(r["role"].get("title") or "") for r in reads
                                                 if r["role"].get("title")))
    outcome.cost_usd = sum([await _live_cost(str(t.id)) for t in missions])
    outcome.minutes = round((datetime.now(timezone.utc) - started).total_seconds() / 60, 1)
    head = _result_of(own)["result"] if own is not None else {}
    outcome.answer = str(head.get("response") or head.get("answer") or "")[:1200]
    outcome.checks = await job.score(outcome)
    return outcome


def render(outcomes: List[Outcome]) -> str:
    lines: List[str] = []
    for o in outcomes:
        job = JOBS[o.job]
        lines.append(f"{'PASS' if o.passed else 'FAIL'}  {job.title}  (mission {o.task_id[:8] or '-'}, "
                     f"{o.specialist or 'no specialist'}, {o.minutes} min, ${o.cost_usd:.2f} / about "
                     f"£{o.cost_usd * GBP_PER_USD:.2f})")
        if o.stopped_by_bench:
            lines.append(f"      stopped: {o.stopped_by_bench}")
        for c in o.checks:
            lines.append(f"      [{'x' if c.passed else ' '}] {c.what}: {c.detail}")
    passed = sum(1 for o in outcomes if o.passed)
    spent = sum(o.cost_usd for o in outcomes)
    lines.append(f"\n{passed} of {len(outcomes)} jobs passed; spent ${spent:.2f} (about £{spent * GBP_PER_USD:.2f}).")
    return "\n".join(lines)


async def run(names: List[str], say: Callable[[str], None] = print) -> List[Outcome]:
    outcomes: List[Outcome] = []
    for name in names:
        job = JOBS[name]
        say(f"\n{job.title} (allowance £{ALLOWANCE_GBP:.2f})")
        try:
            outcomes.append(await run_job(job, say))
        except Exception as exc:  # noqa: BLE001 - one job's fault is reported and the others still run
            outcomes.append(Outcome(job=name, answer=f"{type(exc).__name__}: {exc}",
                                    checks=[Check("the job could be run", False, f"{type(exc).__name__}: {exc}")]))
        say(render(outcomes[-1:]).split("\n\n")[0])
    return outcomes


def main(argv: List[str]) -> int:
    names = [a for a in argv if a in JOBS] or list(JOBS)
    unknown = [a for a in argv if a not in JOBS]
    if unknown:
        print(f"Not a bench job: {', '.join(unknown)}. The jobs: {', '.join(JOBS)}.")
        return 2
    outcomes = asyncio.run(run(names))
    print("\n" + render(outcomes))
    record = [{"job": o.job, "passed": o.passed, "task_id": o.task_id, "status": o.status, "verified": o.verified,
               "engine": o.engine, "specialist": o.specialist, "delegated": o.delegated, "minutes": o.minutes,
               "cost_usd": round(o.cost_usd, 4), "stopped_by_bench": o.stopped_by_bench, "unmet": o.unmet,
               "answer": o.answer, "checks": [c.__dict__ for c in o.checks]} for o in outcomes]
    print("\nBENCH-JSON " + json.dumps(record, default=str))
    return 0 if all(o.passed for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
