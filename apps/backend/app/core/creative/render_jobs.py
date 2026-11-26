"""
JAI Backend - Renders run without AI (24 November, Richard)

"When a video mission's scene is ready, the AI must not sit in the mission paying tokens while frames render."
On 23 and 24 November 3D renders took about 5 seconds a frame on the processor while the agent polled, timed out and
retried. Now:

1. The studio agent calls start_render (tool_runtime.start_render) with the render command, its working folder and
   the output path. JAI checks the command with the sandbox's own rules (sandbox_policy, the mission's scope and
   authority), accepts only a render (OpenMontage's VideoCompose or render_existing, npx remotion render, npx
   hyperframes render, ffmpeg), and the sandbox starts it in the background (services/openhands/app/renders.py:
   no command timeout, its log in the project, one render at a time, the rest queued). The job id comes back at
   once and is kept on the mission (meta_data["render_job"]).
2. The agent stops; the round ends with the render's requirement open, so the mission saves its checkpoint and
   pauses as needs_continuation, the existing checkpoint and continuation path. The mission runner does not carry
   it on while its render is running (runtime/missions._auto_continue), so no model call is made.
3. check_renders (a plain Celery job, every 30 seconds, no AI) asks the sandbox about each render: still queued or
   running (the mission's card says "Rendering (no AI cost)" with the time so far), finished or failed.
4. When it has ended, its facts are kept on the mission (exit code, output path, ffprobe size, length and streams,
   freezedetect, the last 50 log lines) and the mission is queued to carry on the usual way; its next round starts
   with the facts in the maker's brief (MissionTeam._brief): look only if it failed, or to check the finished video.
5. One render per mission: while the mission has a render queued or running, start_render refuses and gives that
   job's id and status (the sandbox's queue refuses a second one for the mission too). Cancelling a mission cancels
   its renders in the sandbox (24 November: mission 6c748110 had 1 running and 2 queued, all its own).
"""
from __future__ import annotations

import logging
import re
import shlex
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import httpx

logger = logging.getLogger(__name__)

ACTIVE_KEY = "renders:active"           # Redis set of mission ids with a render queued or running
CHECK_SECONDS = 30.0
PHASE = "Rendering (no AI cost)"
# A render command: what start_render accepts. One command, never a chain: JAI's permission gate blocks any chained
# command (24 November: "cd folder && render" passed this check, then the gate refused it, on every round of
# episode 2); the folder it runs from is start_render's cwd.
_RENDERERS = (
    re.compile(r"^(?:\S*/)?ffmpeg\b"),
    re.compile(r"^npx\s+(?:--yes\s+|-y\s+)?remotion\s+render\b"),
    re.compile(r"^npx\s+(?:--yes\s+|-y\s+)?hyperframes\s+render\b"),
)
# OpenMontage's render routes run with its Python are judged by what the Python runs (python_runs), never by a file
# name (25 November: render_clip.py, videocompose_render_.py and render_all.py were refused and VideoCompose_render_.py
# accepted, because the old pattern matched "VideoCompose" anywhere in the command): a VideoCompose call.
_PY = re.compile(r"^(?:\S*/)?python3?(?:\.\d+)?$")
_PY_RENDER = re.compile(r"\bVideoCompose\s*\(")
_SCRIPT_LIMIT = 400_000


# A long check run the same way (24 November, mission bb2a4d3c: HyperFrames' pre-render check hit the terminal's
# 300 s limit and the agent switched it off): HyperFrames' lint, validate, check and snapshot (0.9.58's commands).
_CHECKS = (re.compile(r"^npx\s+(?:--yes\s+|-y\s+)?hyperframes\s+(?:lint|validate|check|snapshot)\b"),)


def chained(command: str) -> bool:
    """True when the shell would run more than one command: ;, &&, ||, | or a redirection outside quotes, or a
    $( ) or backtick substitution anywhere (bash expands those inside double quotes too). A ; inside quoted Python
    code is not a chain."""
    if re.search(r"`|\$\(", command or ""):
        return True
    try:
        lexer = shlex.shlex(command or "", posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        return any(set(token) <= set(";&|<>") for token in lexer)
    except ValueError:
        return True


def is_check(command: str) -> bool:
    """True when the command is one long check (no chain, pipe, redirection or substitution)."""
    command = (command or "").strip()
    if not command or chained(command):
        return False
    return any(r.search(command) for r in _CHECKS)


# OpenMontage's own route for a HyperFrames composition (hyperframes_compose, render_existing) runs HyperFrames with
# timeout=1800 (tools/video/hyperframes_compose.py at the pinned commit), and its timeout path then raises "can't
# concat str to bytes" (24 November, mission bb2a4d3c: a 32-second 3D episode takes 28-30 minutes on Richard's
# processor and was killed). A HyperFrames composition is rendered with HyperFrames' own command instead, the one
# OpenMontage would run, from the composition's folder, with no limit beyond JAI's queue.
HYPERFRAMES_DIRECT = ("npx hyperframes render --output <file> --fps 30 --quality <draft|standard|high> --strict, "
                      "with the composition's folder (the one holding its index.html) as cwd")
_OPENMONTAGE_HYPERFRAMES = re.compile(r"\b(?:hyperframes_compose|HyperframesCompose|render_existing)\b|"
                                      r"render_runtime['\"]?\s*[:=]\s*['\"]hyperframes")


def openmontage_hyperframes(command: str, cwd: str = "") -> bool:
    """True when the command renders a HyperFrames composition through OpenMontage's Python (its 30-minute cap),
    in its -c code or in the script it runs."""
    runs = python_runs(command, cwd)
    return bool(runs is not None and _OPENMONTAGE_HYPERFRAMES.search(runs))


BATCH_LIMIT = 20  # renders start_render takes at once (one job, in order)


def python_runs(command: str, cwd: str = "") -> Optional[str]:
    """What a Python command runs: its -c code (file names in it left out) and the text of any script it runs (a
    .py argument, or runpy's run_path target). None when it is not a Python command, or a script it runs cannot be
    read here (then it is not judged a render)."""
    from pathlib import Path

    try:
        argv = shlex.split(command or "")
    except ValueError:
        return None
    if not argv or not _PY.match(argv[0]):
        return None
    code, files = "", []
    rest = argv[1:]
    while rest:
        arg = rest.pop(0)
        if arg == "-c" and rest:
            code = rest.pop(0)
            break
        if arg == "-m" and rest:
            code = f"import {rest.pop(0)}"
            break
        if arg.startswith("-"):
            continue
        files.append(arg)
        break
    files += re.findall(r"run_path\(\s*['\"]([^'\"]+?\.py)['\"]", code)
    text = re.sub(r"(['\"])[^'\"\n]*?\.py\1", "''", code)  # a file's name says nothing about what it runs
    for name in files:
        path = Path(name) if name.startswith("/") else Path(cwd or ".") / name
        try:
            text += "\n" + path.read_text(encoding="utf-8", errors="replace")[:_SCRIPT_LIMIT]
        except OSError:
            return None
    return text


def is_render(command: str, cwd: str = "") -> bool:
    """True when the command is one render (no chain, pipe, redirection or substitution), judged by what it runs:
    ffmpeg, npx remotion render, npx hyperframes render, or Python that makes a VideoCompose call (in its -c code or
    in the script it runs, whatever the script is called)."""
    command = (command or "").strip()
    if not command or chained(command):
        return False
    runs = python_runs(command, cwd)
    if runs is not None:
        return bool(_PY_RENDER.search(runs))
    return any(r.search(command) for r in _RENDERERS)


def _changed_since(root: str, since: float) -> bool:
    """Whether any file in the workspace (not its videos, renders or tool folders) changed after since."""
    import os

    skip = {"node_modules", ".git", ".venv", "__pycache__", ".cache"}
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".jai")]
        for name in files:
            if name.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".m4v", ".log")):
                continue
            try:
                if os.path.getmtime(os.path.join(folder, name)) > since:
                    return True
            except OSError:
                continue
    return False


def _sandbox() -> str:
    from app.core.command.sandbox_engine import sandbox_url

    return sandbox_url()


def _headers() -> Dict[str, str]:
    from app.core.config import settings

    return {"Authorization": f"Bearer {settings.OPENHANDS_TOKEN or ''}"}


async def _mark(task_id: UUID, job: Dict[str, Any]) -> None:
    from app.core.redis import get_redis

    from app.core.runtime.missions import session_factory
    from app.models.task import Task
    from sqlalchemy import select

    async with session_factory()() as db:
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if task is not None:
            meta = dict(task.meta_data or {})
            meta["render_job"] = job
            meta.pop("render_result", None)
            task.meta_data = meta
            await db.commit()
    await (await get_redis()).sadd(ACTIVE_KEY, str(task_id))


async def start(*, task_id: Optional[UUID], container_root: str, host_root: str, command: str, cwd: str,
                output: str, client: Optional[httpx.AsyncClient] = None,
                steps: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Hand a checked render (or a batch: steps, run in order as one job) to the sandbox and keep its job on the
    mission. {"success", "job_id", ...}."""
    if steps:  # what identifies a batch for the same-again check: all its commands, in order
        command = "\n".join(" ".join(str(s["command"]).split()) for s in steps)
    if task_id is None:
        return {"success": False, "error": "start_render needs a mission to pause and resume."}
    meta = await _meta(task_id) or {}
    current = rendering(meta)
    if current is not None:
        return _already(current["job_id"], str(current.get("status")))
    last, previous = meta.get("render_result") or {}, meta.get("render_job") or {}
    if last and last.get("status") != "finished" and " ".join(str(last.get("command") or "").split()) == \
            " ".join(command.split()) and str(previous.get("cwd") or cwd) == cwd:
        # 24 November, mission bb2a4d3c queued the identical render again after it failed: a retry changes
        # something (the command, or the files that caused it) or the mission stops and says why.
        try:
            ended = datetime.fromisoformat(str(previous.get("ended_at") or "")).timestamp()
        except ValueError:
            ended = None
        if ended is None or not _changed_since(container_root, ended):
            why = "timed out" if last.get("timed_out") else f"failed (exit {last.get('exit_code')})"
            return {"success": False, "same_again": True, "job_id": last.get("job_id"),
                    "error": (f"This is the render that just {why} (job {last.get('job_id')}), with the same "
                              "command and no file changed since. Change something first (fix the cause in the "
                              "files, or the command), or stop and say in your report why it cannot be rendered."
                              + (f" For a HyperFrames composition run {HYPERFRAMES_DIRECT}." if last.get("timed_out")
                                 else ""))}
    job_id = f"render-{str(task_id)[:8]}-{uuid4().hex[:8]}"
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    try:
        kind = "batch" if steps else "check" if is_check(command) else "render"
        body = {"job_id": job_id, "workspace": container_root, "command": command.split("\n")[0], "cwd": cwd,
                "output": output, "kind": "check" if kind == "check" else "render"}
        if steps:
            body["steps"] = [{"command": s["command"], "cwd": s["cwd"], "output": s.get("output") or "",
                              "kind": s.get("kind") or "render"} for s in steps]
        answer = await client.post(f"{_sandbox()}/renders", headers=_headers(), json=body)
    except httpx.HTTPError as exc:
        return {"success": False, "error": f"The sandbox could not be reached to start the render "
                                           f"({type(exc).__name__})."}
    finally:
        if owned:
            await client.aclose()
    if answer.status_code != 200:
        return {"success": False, "error": f"The sandbox did not start the render: {answer.status_code} "
                                           f"{answer.text[:300]}"}
    view = answer.json()
    if view.get("existing"):  # the sandbox already has this mission's render queued or running
        job_id = str(view.get("job_id") or job_id)
        await _mark(task_id, {"job_id": job_id, "command": str(view.get("command") or "")[:2000],
                              "cwd": view.get("cwd"), "output": view.get("output"), "status": view.get("status"),
                              "started_at": view.get("started_at") or view.get("queued_at"),
                              "log": view.get("log"), "host_root": host_root})
        return _already(job_id, str(view.get("status")))
    job = {"job_id": job_id, "kind": kind, "command": command[:4000], "cwd": cwd, "output": output,
           "status": view.get("status"), "renders": len(steps) if steps else 1,
           "outputs": [s.get("output") or "" for s in steps] if steps else [output],
           "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "log": view.get("log"), "host_root": host_root}
    await _mark(task_id, job)
    return {"success": True, "job_id": job_id, "status": view.get("status"), "log": view.get("log"),
            "renders": len(steps) if steps else 1,
            "next": ("The render is running with no AI" + (f" ({len(steps)} renders in order, one job)" if steps
                                                            else "") + ". Stop now: end your turn with your report, "
                     "the render's "
                     "requirement open (`R<n>: open — rendering, job " + job_id + "`). The mission pauses and comes "
                     "back to you with the render's facts when it ends.")}


def _already(job_id: str, status: str) -> Dict[str, Any]:
    return {"success": False, "already": True, "job_id": job_id, "status": status,
            "error": (f"This mission's render {job_id} is already {status}; one render per mission. End your turn "
                      f"now with the render's requirement open (`R<n>: open — rendering, job {job_id}`): the "
                      f"mission comes back to you with its facts when it ends.")}


async def _meta(task_id: UUID) -> Optional[Dict[str, Any]]:
    from sqlalchemy import select

    from app.core.runtime.missions import session_factory
    from app.models.task import Task

    async with session_factory()() as db:
        meta = (await db.execute(select(Task.meta_data).where(Task.id == task_id))).scalar_one_or_none()
    return meta if isinstance(meta, dict) else None


async def cancel(task: Any, client: Optional[httpx.AsyncClient] = None) -> List[str]:
    """Stop a cancelled mission's queued and running renders in the sandbox and mark its render cancelled on the
    record (the caller saves it). Returns the job ids the sandbox stopped."""
    from app.core.redis import get_redis

    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    try:
        answer = await client.post(f"{_sandbox()}/renders/cancel", headers=_headers(),
                                   json={"mission": str(task.id)[:8]})
        stopped = list(answer.json().get("cancelled") or []) if answer.status_code == 200 else []
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(f"could not cancel the renders of {task.id}: {exc}")
        stopped = []
    finally:
        if owned:
            await client.aclose()
    meta = dict(task.meta_data or {})
    if isinstance(meta.get("render_job"), dict) and meta["render_job"].get("status") in ("queued", "running"):
        meta["render_job"] = {**meta["render_job"], "status": "cancelled"}
        task.meta_data = meta
    try:
        await (await get_redis()).srem(ACTIVE_KEY, str(task.id))
    except Exception as exc:  # noqa: BLE001 - the watcher skips cancelled missions anyway
        logger.warning(f"could not clear {task.id} from the active renders: {exc}")
    return stopped


RENDER_KEYS = ("render_job", "render_result")


async def keep_render_state(db: Any, task: Any) -> None:
    """Carry the render state written during a round (by start_render and the watcher, in their own sessions) onto
    the mission's record before the round's outcome is saved. The round's session loaded the record when the round
    began, so saving it as it was wiped the render the round had just started (24 November: episode 2 carried on
    a minute and a half into its render and queued a second render of the same file behind it)."""
    from sqlalchemy import select

    from app.models.task import Task

    with db.no_autoflush:  # read what is in the database now, not this session's older copy
        fresh = (await db.execute(select(Task.meta_data).where(Task.id == task.id))).scalar_one_or_none()
    if not isinstance(fresh, dict):
        return
    meta = dict(task.meta_data or {})
    for key in RENDER_KEYS:
        if key in fresh:
            meta[key] = fresh[key]
        else:
            meta.pop(key, None)
    task.meta_data = meta


def rendering(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The mission's render while it is queued or running, else None."""
    job = (meta or {}).get("render_job")
    return job if isinstance(job, dict) and job.get("status") in ("queued", "running") else None


def elapsed(job: Dict[str, Any], now: Optional[float] = None) -> str:
    try:
        began = datetime.fromisoformat(str(job.get("started_at"))).timestamp()
    except ValueError:
        return ""
    seconds = max(0, int((now or time.time()) - began))
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def card_line(job: Dict[str, Any], now: Optional[float] = None) -> str:
    queued = " (waiting its turn: one render at a time)" if job.get("status") == "queued" else ""
    phase = "Checking (no AI cost)" if job.get("kind") == "check" else PHASE
    count = int(job.get("renders") or 1)
    which = (f" render {job.get('step')} of {count}" if job.get("step") else f" {count} renders") if count > 1 else ""
    return f"{phase}{queued}{',' if which else ''}{which}, {elapsed(job, now)} so far."


async def check_once(client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """One pass of the watcher (Celery beat, every 30 seconds; no AI): each mission's render, still going, or ended
    and its mission carried on."""
    from sqlalchemy import select

    from app.core.command import progress
    from app.core.redis import get_redis
    from app.core.runtime import lifecycle
    from app.core.runtime.missions import _feed, session_factory
    from app.models.task import Task

    redis = await get_redis()
    ids = [i.decode() if isinstance(i, bytes) else str(i) for i in await redis.smembers(ACTIVE_KEY)]
    summary: Dict[str, List[str]] = {"running": [], "ended": [], "resumed": [], "lost": []}
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
    try:
        for raw in ids:
            task_id = UUID(raw)
            async with session_factory()() as db:
                task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
                job = rendering(task.meta_data if task is not None else None)
                if task is None or job is None or lifecycle.normalise(task.status) in lifecycle.TERMINAL:
                    await redis.srem(ACTIVE_KEY, raw)
                    continue
                try:
                    answer = await client.get(f"{_sandbox()}/renders/{job['job_id']}", headers=_headers())
                    view = answer.json() if answer.status_code == 200 else (
                        {"status": "failed", "facts": {"error": "The sandbox no longer knows this render (it was "
                                                                "restarted while it rendered)."}}
                        if answer.status_code == 404 else None)
                except (httpx.HTTPError, ValueError):
                    view = None  # the sandbox did not answer this time: asked again in 30 seconds
                if view is None:
                    continue
                if view.get("status") in ("queued", "running"):
                    if view["status"] != job.get("status") or view.get("step") != job.get("step"):
                        job = {**job, "status": view["status"], "step": view.get("step")}
                        task.meta_data = {**(task.meta_data or {}), "render_job": job}
                        await db.commit()
                    record = await progress.load(task_id) or {}
                    record.update({"phase": card_line(job), "agent_said": card_line(job),
                                   "rendering": {"job_id": job["job_id"], "status": job["status"],
                                                 "elapsed": elapsed(job)},
                                   "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                    await progress.save(task_id, record)
                    summary["running"].append(raw)
                    continue
                facts = dict(view.get("facts") or {})
                facts.update({"job_id": job["job_id"], "status": view.get("status"),
                              "exit_code": view.get("exit_code", facts.get("exit_code")),
                              "command": job.get("command"), "seconds": view.get("seconds", facts.get("seconds"))})
                # Exit 0 and a video ffprobe read is a success, whatever the render printed on stderr (24 November,
                # mission 5670069a: "Render failed · exit 0" over a Node warning and a file written elsewhere).
                check = job.get("kind") == "check" or facts.get("kind") == "check"
                batch = facts.get("kind") == "batch" or job.get("kind") == "batch"
                if batch:  # each clip by the same rule: exit 0 and a video ffprobe read is finished
                    steps = list(facts.get("steps") or [])
                    for step in steps:
                        if step.get("kind") != "check" and step.get("exit_code") == 0 and readable(step):
                            step["status"] = "finished"
                    ok = bool(steps) and len(steps) == int(job.get("renders") or len(steps)) and all(
                        s.get("status") == "finished" for s in steps)
                    facts["finished"] = sum(s.get("status") == "finished" for s in steps)
                    facts["failed"] = len(steps) - facts["finished"]
                else:
                    ok = view.get("status") == "finished" or (not check and facts.get("exit_code") == 0
                                                              and readable(facts))
                facts["status"] = "finished" if ok else view.get("status")
                meta = dict(task.meta_data or {})
                meta["render_job"] = {**job, "status": facts["status"], "ended_at": view.get("ended_at")}
                meta["render_result"] = facts
                task.meta_data = meta
                if batch:
                    _feed(db, task, f"Renders {'finished' if ok else 'ended'}: {facts['finished']} of "
                                    f"{len(facts.get('steps') or [])} made",
                          "; ".join(f"{s.get('output')}: " + (f"{s.get('duration_seconds')} s, sound {sound(s)}"
                                                               if s.get("status")
                                                               == "finished" else "timed out" if s.get("timed_out")
                                                               else f"failed (exit {s.get('exit_code')})")
                                    for s in facts.get("steps") or [])[:1500], severity="info" if ok else "warning")
                else:
                    _feed(db, task, ("Check" if check else "Render") + (
                                         " finished" if ok else " timed out" if facts.get("timed_out") else " failed"),
                      (f"exit 0 in {facts.get('seconds')} s" if check and ok else
                       f"{facts.get('output')}: {facts.get('width')}x{facts.get('height')}, "
                       f"{facts.get('duration_seconds')} s, sound {sound(facts)}"
                       + (f". {facts['note']}" if facts.get("note") else "")
                       if ok else
                       f"exit {facts.get('exit_code')}: " + " | ".join((facts.get("log_tail") or [])[-3:]))[:900],
                      severity="info" if ok else "warning")
                resumed = False
                if lifecycle.normalise(task.status) == lifecycle.NEEDS_CONTINUATION:
                    lifecycle.transition(task, lifecycle.QUEUED, actor="render-watcher",
                                         reason=f"render {job['job_id']} {view.get('status')}: carry on")
                    task.meta_data = {**(task.meta_data or {}), "resume_mode": "continuation"}
                    resumed = True
                await db.commit()
                await redis.srem(ACTIVE_KEY, raw)
                summary["ended"].append(raw)
            if resumed:
                from app.core.runtime.dispatcher import dispatch_mission

                await dispatch_mission(task_id, reason="render ended")
                summary["resumed"].append(raw)
    finally:
        if owned:
            await client.aclose()
    return summary


def sound(facts: Dict[str, Any]) -> str:
    """The render's sound in a few words, from the sandbox's volumedetect (26 November: a video with no sound)."""
    if facts.get("sound"):
        return f"SILENT ({facts['sound']})"
    if facts.get("max_volume_db") is None:
        return "not measured" + (f" ({facts['volumedetect_error'][:120]})" if facts.get("volumedetect_error") else "")
    level = f"loudest {facts.get('max_volume_db')} dB, average {facts.get('mean_volume_db')} dB"
    return f"SILENT ({level})" if facts.get("silent") else level


# 26 November, Richard: "what about videos that don't have sound?" Silence is allowed (the studio's rule: no music
# unless the brief asks, sound design or silence instead), so a silent render is held back only when the brief
# itself has people speaking, a voice, narration, music or sound in it, and never when it asks for silence.
_ASKS_SILENCE = re.compile(r"\b(silent|silence|no (sound|audio)|without (sound|audio)|mute[ds]?|muting)\b", re.I)
_HAS_SOUND = re.compile(r"\b(talk\w*|speak\w*|speech\w*|says?|said|saying|interview\w*|podcast\w*|voice\w*|"
                        r"narrat\w*|dialogue|quotes?|music\w*|songs?|soundtrack|sound|sounds|audio|sfx|lyrics?)\b", re.I)


_SOUND_WORD = r"(music\w*|voice\w*|narrat\w*|songs?|soundtrack|sfx|sound effects?)"
_NONE_OF = re.compile(rf"\b(no|without|zero|never any)\s+(\w+\s+){{0,2}}?{_SOUND_WORD}"
                      rf"(\s*(,|or|nor|and)\s+(any\s+|a\s+|an\s+)?(\w+\s+)?{_SOUND_WORD})*\b", re.I)


def wants_sound(brief: Optional[str]) -> bool:
    """Whether the brief's video has sound in it: people speaking, a voice, narration, music or sound, and no ask
    for silence ("no music" or "without a voiceover" is not a sound it asks for). Without either, a silent video is
    a choice the studio may make."""
    text = _NONE_OF.sub(" ", brief or "")
    return not _ASKS_SILENCE.search(text) and bool(_HAS_SOUND.search(text))


SILENT_NEXT = ("ITS SOUND IS SILENT. A video whose brief has people speaking, sound or music is not finished silent. "
               "OpenMontage's Explainer and CinematicRenderer compositions play every video clip muted: the speech "
               "must be handed to them as its own audio (VideoCompose's edit_decisions audio.narration.src for "
               "Explainer, soundtrack for CinematicRenderer), the clips' own sound trimmed and joined in the cuts' "
               "order with OpenMontage's audio tools, or, for one speaker on camera, renderer_family \"presenter\" "
               "(TalkingHead plays its clip's sound). Fix the audio and start the render again through start_render. "
               "Only if the brief's video is meant to be silent: say so in one line and end your turn.")


def facts_brief(facts: Optional[Dict[str, Any]], silence_ok: bool = False) -> str:
    """The render's facts for the maker's next round. silence_ok: the brief's video may be silent (wants_sound)."""
    if not facts:
        return ""
    ok = facts.get("status") == "finished"
    if facts.get("kind") == "batch":
        steps = list(facts.get("steps") or [])
        lines = [f"THE {len(steps)} RENDERS YOU STARTED HAVE ENDED (job {facts.get('job_id')}, run in order; no AI "
                 f"was used while they ran, {facts.get('seconds')} s): {facts.get('finished')} made, "
                 f"{facts.get('failed')} not."]
        for n, step in enumerate(steps, 1):
            state = ("finished" if step.get("status") == "finished" else "TIMED OUT" if step.get("timed_out")
                     else "FAILED")
            line = f"- {n}. {step.get('output')}: {state}, exit {step.get('exit_code')}"
            if step.get("output_exists"):
                line += (f", {step.get('width')}x{step.get('height')}, {step.get('duration_seconds')} s, "
                         f"{int(step.get('size_bytes') or 0) / 1_000_000:.1f} MB, sound {sound(step)}")
            for key in ("note", "timeout", "error"):
                if step.get(key):
                    line += f" ({step[key]})"
            lines.append(line)
        lines += ["- the log's last lines:", *[f"    {line}" for line in (facts.get("log_tail") or [])[-30:]],
                  "Carry on with what the skill does next with these renders. For any that did not finish, fix the "
                  "cause and start only those again through start_render (renders: [...]); never the same command "
                  "again without a change."]
        if not silence_ok and any(s.get("silent") for s in steps if s.get("status") == "finished"):
            lines.append("Some of these are SILENT (above). " + SILENT_NEXT)
        return "\n".join(lines)
    if facts.get("kind") == "check":
        lines = [f"THE CHECK YOU STARTED HAS ENDED (job {facts.get('job_id')}; no AI was used while it ran, "
                 f"{facts.get('seconds')} s):",
                 f"- result: {'passed' if ok else 'FAILED'}, exit code {facts.get('exit_code')}",
                 f"- command: {facts.get('command')}",
                 "- its last log lines:", *[f"    {line}" for line in (facts.get("log_tail") or [])[-50:]],
                 "Fix what it found, then carry on: render through start_render. Never switch a check off, skip "
                 "it or cut it short to fit a time limit."]
        return "\n".join(lines)
    lines = [f"THE RENDER YOU STARTED HAS ENDED (job {facts.get('job_id')}; no AI was used while it ran, "
             f"{facts.get('seconds')} s):",
             f"- result: {'finished' if ok else 'TIMED OUT' if facts.get('timed_out') else 'FAILED'}, exit code "
             f"{facts.get('exit_code')}",
             f"- command: {facts.get('command')}",
             f"- output: {facts.get('output')} ({'exists' if facts.get('output_exists') else 'missing'}"
             + (f", {facts.get('size_bytes')} bytes" if facts.get("size_bytes") else "") + ")"]
    if facts.get("output_exists"):
        lines.append(f"- ffprobe: {facts.get('width')}x{facts.get('height')}, {facts.get('duration_seconds')} s, "
                     f"streams {', '.join(facts.get('streams') or []) or 'none'}")
        frozen = facts.get("frozen") or []
        lines.append("- freezedetect: " + ("no frozen picture" if not frozen else
                                           f"{len(frozen)} frozen stretch(es) "
                                           + ("including the ending " if facts.get("frozen_at_end") else "")
                                           + str(frozen[:5])))
        lines.append(f"- sound (volumedetect): {sound(facts)}"
                     + (" — the brief's video may be silent" if silence_ok and facts.get("silent") else ""))
    if facts.get("note"):
        lines.append(f"- note: {facts['note']}")
    if facts.get("error"):
        lines.append(f"- error: {facts['error']}")
    lines.append("- the last lines of its log:\n" + "\n".join(f"    {line}" for line in (facts.get("log_tail") or [])))
    if passes(facts, silence_ok):
        # 24 November (mission 92b195d8): after a finished render the maker went on for rounds re-checking sound
        # levels, files and stills of a video already saved. Its render's facts are the check; the round is short.
        # 24 November (mission d0a0f858): told not to look, the maker reported 13 of 21 requirements "not
        # checked". One look at one contact sheet of the rendered frames, then stop.
        sheet = contact_sheet_command(facts)
        warned = [line for line in (facts.get("log_tail") or []) if re.search(r"warn|timeout|error", line, re.I)]
        lines.append("THIS IS THE MISSION'S LAST ROUND. JAI has checked the file (the facts above). Do only this, "
                     "once: (1) if the video is not yet where the brief says, copy it there; (2) make one contact "
                     f"sheet of the rendered frames with `{sheet}` and open it once; (3) check the story, the names, "
                     "the on-screen text and the motion on it against the brief"
                     + (" (the render warned: " + "; ".join(w.strip()[:160] for w in warned[:3])
                        + ": look at those moments on the sheet)" if warned else "")
                     + "; (4) report each requirement in one line (`R<n>: done — what the sheet shows` or `R<n>: "
                     "open — what is wrong`) and end your turn. One sheet, one look: no further sheets or stills, "
                     "no sound checks, no other agent reviewing it, no render again and no changes. Richard watches "
                     "the video and has the last word.")
    elif ok and facts.get("silent"):
        lines.append("The render finished, but " + SILENT_NEXT)
    elif facts.get("timed_out"):
        lines.append(f"The render did not fail: {facts.get('timeout') or 'a time limit stopped it'}. Render it "
                     f"again with no limit but JAI's queue: for a HyperFrames composition give start_render "
                     f"{HYPERFRAMES_DIRECT}.")
    else:
        lines.append("The render failed: read the log lines above, fix the cause and start the render again with "
                     "start_render. Never start the same render again without changing something.")
    return "\n".join(lines)


def readable(facts: Optional[Dict[str, Any]]) -> bool:
    """ffprobe read a video from the render's output: it exists, with a video stream and a length."""
    facts = facts or {}
    return bool(facts.get("output_exists") and "video" in (facts.get("streams") or [])
                and float(facts.get("duration_seconds") or 0) > 0)


def contact_sheet_command(facts: Dict[str, Any], frames: int = 18) -> str:
    """The ffmpeg command for one contact sheet of a rendered video: frames spread evenly, 6 to a row."""
    video = str(facts.get("output") or "final.mp4")
    duration = max(float(facts.get("duration_seconds") or 0), 1.0)
    rows = -(-frames // 6)
    return (f"ffmpeg -v error -y -i {shlex.quote(video)} -vf \"fps={frames}/{duration:.2f},scale=270:-1,"
            f"tile=6x{rows}\" -frames:v 1 .jai/work/final-contact-sheet.png")


def passes(facts: Optional[Dict[str, Any]], silence_ok: bool = False) -> bool:
    """A finished render whose file is a real video: it exists, has a size, a video stream, a length, and sound
    unless the brief's video may be silent (silence_ok, from wants_sound)."""
    facts = facts or {}
    return bool(facts.get("status") == "finished" and facts.get("output_exists") and int(facts.get("size_bytes") or 0)
                and "video" in (facts.get("streams") or []) and float(facts.get("duration_seconds") or 0) > 0
                and (silence_ok or not facts.get("silent")))  # 26 November: silent only when the brief allows
