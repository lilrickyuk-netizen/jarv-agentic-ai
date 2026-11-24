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
# A render command: what start_render accepts (each part of a chain is one of these, or a cd or export before it).
_RENDERERS = (
    re.compile(r"^(?:\S*/)?ffmpeg\b"),
    re.compile(r"^npx\s+(?:--yes\s+|-y\s+)?remotion\s+render\b"),
    re.compile(r"^npx\s+(?:--yes\s+|-y\s+)?hyperframes\s+render\b"),
    # OpenMontage's own render routes, run with its Python: VideoCompose (any operation) and render_existing.
    re.compile(r"^(?:\S*/)?python3?\b.*\b(?:VideoCompose|video_compose|render_existing|hyperframes_compose)\b",
               re.S),
)
_SETUP = re.compile(r"^(?:cd\s+\S+|export\s+[A-Z_][A-Z0-9_]*=\S*|source\s+\S+|\.\s+\S+)$")


def is_render(command: str) -> bool:
    """True when every part of the command is a render, or a cd / export / source before one, and one is a render."""
    parts = [p.strip() for p in re.split(r"\s*(?:&&|;)\s*", (command or "").strip()) if p.strip()]
    if not parts or any(re.search(r"[|`]|\$\(|>\s*/(?!dev/null)", p) for p in parts):
        return False
    renders = [p for p in parts if any(r.search(p) for r in _RENDERERS)]
    return bool(renders) and all(p in renders or _SETUP.match(p) for p in parts)


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
                output: str, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """Hand a checked render to the sandbox and keep its job on the mission. {"success", "job_id", ...}."""
    if task_id is None:
        return {"success": False, "error": "start_render needs a mission to pause and resume."}
    job_id = f"render-{str(task_id)[:8]}-{uuid4().hex[:8]}"
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    try:
        answer = await client.post(f"{_sandbox()}/renders", headers=_headers(), json={
            "job_id": job_id, "workspace": container_root, "command": command, "cwd": cwd, "output": output})
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
    job = {"job_id": job_id, "command": command[:2000], "cwd": cwd, "output": output, "status": view.get("status"),
           "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "log": view.get("log"), "host_root": host_root}
    await _mark(task_id, job)
    return {"success": True, "job_id": job_id, "status": view.get("status"), "log": view.get("log"),
            "next": ("The render is running with no AI. Stop now: end your turn with your report, the render's "
                     "requirement open (`R<n>: open — rendering, job " + job_id + "`). The mission pauses and comes "
                     "back to you with the render's facts when it ends.")}


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
    return f"{PHASE}{queued}, {elapsed(job, now)} so far."


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
                    if view["status"] != job.get("status"):
                        task.meta_data = {**(task.meta_data or {}), "render_job": {**job, "status": view["status"]}}
                        await db.commit()
                        job = {**job, "status": view["status"]}
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
                meta = dict(task.meta_data or {})
                meta["render_job"] = {**job, "status": view.get("status"), "ended_at": view.get("ended_at")}
                meta["render_result"] = facts
                task.meta_data = meta
                ok = view.get("status") == "finished"
                _feed(db, task, "Render finished" if ok else "Render failed",
                      (f"{facts.get('output')}: {facts.get('width')}x{facts.get('height')}, "
                       f"{facts.get('duration_seconds')} s" if ok else
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


def facts_brief(facts: Optional[Dict[str, Any]]) -> str:
    """The render's facts for the maker's next round."""
    if not facts:
        return ""
    ok = facts.get("status") == "finished"
    lines = [f"THE RENDER YOU STARTED HAS ENDED (job {facts.get('job_id')}; no AI was used while it ran, "
             f"{facts.get('seconds')} s):",
             f"- result: {'finished' if ok else 'FAILED'}, exit code {facts.get('exit_code')}",
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
    if facts.get("error"):
        lines.append(f"- error: {facts['error']}")
    lines.append("- the last lines of its log:\n" + "\n".join(f"    {line}" for line in (facts.get("log_tail") or [])))
    lines.append("If it failed, read the log lines above, fix the cause and start the render again with "
                 "start_render. If it finished, look at a few stills of the output to check it, copy it where the "
                 "brief says and finish; do not render it again.")
    return "\n".join(lines)
