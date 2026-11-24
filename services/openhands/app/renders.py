"""
Renders run without AI (24 November, Richard)

A video's final render can take many minutes on this computer's processor (3D scenes about 5 seconds a frame), and
the agent sat in the mission paying for tokens while it polled, timed out and retried. Now the agent hands the render
to JAI (its start_render tool, decided and recorded by JAI's backend), which starts it here as a plain background
process and the mission pauses. The process:

- runs as the agent's own unprivileged user, in a login shell (the sandbox's settings, as the agent's shell has
  them), with no command timeout;
- writes everything it prints to .jai/renders/<job>.log in the mission's workspace;
- waits its turn: one render at a time on this computer, the rest queue (two processor renders at once crashed the
  sandbox before);
- is the mission's only one: while a mission has a render queued or running, a new one for it is not queued and
  the existing one is returned (24 November: mission 6c748110 had 1 running and 2 queued, each round handing over a
  new render before the last ended);
- can be cancelled (POST /renders/cancel): a queued render is dropped, a running one is stopped with its whole
  process group (the renderer, Chromium, ffmpeg).

When it ends, the facts are worked out here, where the file is. A render that exits 0 and whose video ffprobe can
read is a success whatever it printed on stderr (24 November, mission 5670069a: a Node MaxListenersExceededWarning and
a file written elsewhere were reported as "Render failed · exit 0"). The video is looked for where start_render said,
then where the command itself says it writes (--output, -o, its last video argument), then as the newest video written
in the workspace since the render began; if it is not where start_render said, the facts say where it is.
The facts are: the exit code, whether the output exists and its
size, ffprobe's width, height, length and streams, ffmpeg's freezedetect on the whole video, and the last 50 lines
of the log. JAI's backend reads them every 30 seconds (a Celery job, no AI) and resumes the mission with them.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import signal
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jai.sandbox.renders")

AGENT_USER = os.environ.get("JAI_AGENT_USER", "openhands")
LOG_DIR = ".jai/renders"
LOG_LINES = 50
STOP_SECONDS = 10  # how long a cancelled render has to stop before it is killed
FREEZE = re.compile(r"freeze_(start|duration|end): ([\d.]+)")
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
SKIP_DIRS = {"node_modules", ".git", ".venv", "__pycache__", ".cache"}
_OUTPUT_FLAG = re.compile(r"(?:--output|--out|-o)(?:=|\s+)(?P<q>['\"]?)(?P<path>[^'\"\s]+)(?P=q)")


def _iso(moment: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(moment, timezone.utc).isoformat(timespec="seconds") if moment else None


class Job:
    def __init__(self, job_id: str, workspace: str, command: str, cwd: str, output: str, kind: str = "render"):
        self.kind = kind  # "render" (makes a video) or "check" (HyperFrames' lint, validate, check, snapshot)
        self.id, self.workspace, self.command, self.cwd, self.output = job_id, workspace, command, cwd, output
        self.status = "queued"  # queued, running, finished, failed, cancelled
        self.exit_code: Optional[int] = None
        self.queued_at = time.time()
        self.started_at: Optional[float] = None
        self.ended_at: Optional[float] = None
        self.facts: Dict[str, Any] = {}
        self.log = Path(workspace) / LOG_DIR / f"{job_id}.log"
        self.process: Optional[subprocess.Popen] = None

    def view(self) -> Dict[str, Any]:
        now = time.time()
        return {"job_id": self.id, "status": self.status, "command": self.command, "cwd": self.cwd,
                "output": self.output, "log": str(self.log), "exit_code": self.exit_code, "kind": self.kind,
                "queued_at": _iso(self.queued_at), "started_at": _iso(self.started_at),
                "ended_at": _iso(self.ended_at),
                "seconds": int((self.ended_at or now) - (self.started_at or now)) if self.started_at else 0,
                "position": queue_position(self.id), "facts": dict(self.facts)}


JOBS: Dict[str, Job] = {}
_QUEUE: "queue.Queue[str]" = queue.Queue()
_LOCK = threading.Lock()
_WORKER: Optional[threading.Thread] = None


def queue_position(job_id: str) -> int:
    """0 when running or ended; otherwise how many renders are ahead of it (the running one included)."""
    with _LOCK:
        job = JOBS.get(job_id)
        if job is None or job.status != "queued":
            return 0
        ahead = [j for j in JOBS.values() if j.status == "running"
                 or (j.status == "queued" and j.queued_at < job.queued_at)]
    return len(ahead)


def mission_of(job_id: str) -> str:
    """The mission part of a job id ("render-<mission>-<n>" -> "render-<mission>-")."""
    return job_id.rsplit("-", 1)[0] + "-"


def active_for(prefix: str) -> List[Job]:
    with _LOCK:
        return [j for j in JOBS.values() if j.id.startswith(prefix) and j.status in ("queued", "running")]


def submit(job_id: str, workspace: str, command: str, cwd: str, output: str, kind: str = "render") -> Job:
    """Queue a render, or return the mission's render already queued or running (job.id tells which)."""
    global _WORKER
    with _LOCK:
        if job_id in JOBS:
            raise ValueError(f"Render {job_id} exists already.")
        mission = mission_of(job_id)
        existing = next((j for j in JOBS.values() if j.id.startswith(mission)
                         and j.status in ("queued", "running")), None)
        if existing is not None:
            return existing
        job = Job(job_id, workspace, command, cwd, output, kind)
        JOBS[job_id] = job
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_work, name="renders", daemon=True)
            _WORKER.start()
    _QUEUE.put(job_id)
    return job


def _work() -> None:
    while True:
        job_id = _QUEUE.get()
        job = JOBS.get(job_id)
        if job is not None and job.status == "queued":
            try:
                run(job)
            except Exception as exc:  # noqa: BLE001 - a render's failure is its own; the queue goes on
                logger.exception("render %s failed to run", job_id)
                job.status, job.exit_code, job.ended_at = "failed", job.exit_code if job.exit_code is not None \
                    else -1, time.time()
                job.facts = {**job.facts, "error": f"{type(exc).__name__}: {exc}"[:500]}
        _QUEUE.task_done()


def _as_agent() -> Dict[str, Any]:
    """Run as the agent's own user when this service is root (as OpenHands' terminal does); otherwise as is."""
    if os.geteuid() != 0:
        return {}
    import pwd

    try:
        entry = pwd.getpwnam(AGENT_USER)
    except KeyError:
        return {}
    return {"user": entry.pw_uid, "group": entry.pw_gid, "extra_groups": [],
            "env": {**os.environ, "HOME": entry.pw_dir, "USER": entry.pw_name, "LOGNAME": entry.pw_name}}


def run(job: Job) -> None:
    """Run one render to its end (no timeout) and work out its facts."""
    job.log.parent.mkdir(parents=True, exist_ok=True)
    job.status, job.started_at = "running", time.time()
    with open(job.log, "ab") as log:
        log.write(f"$ {job.command}\n(in {job.cwd}, started {_iso(job.started_at)})\n".encode())
        log.flush()
        job.process = subprocess.Popen(["bash", "-lc", f"cd {_quote(job.cwd)} && {job.command}"], cwd=job.cwd,
                                       stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       start_new_session=True, **_as_agent())
        if job.status == "cancelled":  # cancelled while it was starting
            _stop(job.process)
        job.exit_code = job.process.wait()
    job.ended_at = time.time()
    if job.status == "cancelled":
        job.facts = {"exit_code": job.exit_code, "cancelled": True, "log_tail": _tail(job.log)}
        logger.info("render %s cancelled after %ss", job.id, int(job.ended_at - job.started_at))
        return
    if job.kind == "check":  # a check makes no video: its exit code is its verdict, its log the findings
        job.facts = {"kind": "check", "exit_code": job.exit_code, "log_tail": _tail(job.log),
                     "seconds": int(job.ended_at - (job.started_at or job.ended_at))}
        job.status = "finished" if job.exit_code == 0 else "failed"
        logger.info("check %s %s (exit %s)", job.id, job.status, job.exit_code)
        return
    job.facts = facts(job)
    job.status = "finished" if job.exit_code == 0 and _readable(job.facts) else "failed"
    logger.info("render %s %s (exit %s) in %ss", job.id, job.status, job.exit_code,
                int(job.ended_at - job.started_at))


def cancel(prefix: str) -> List[str]:
    """Cancel every queued or running render whose id starts with prefix (a mission's: "render-<mission>-"). A
    running one is sent SIGTERM with its process group, then SIGKILL if it has not stopped in STOP_SECONDS."""
    stopped = []
    for job in active_for(prefix):
        with _LOCK:
            was = job.status
            job.status = "cancelled"
            if was == "queued":
                job.ended_at = time.time()
                job.facts = {"cancelled": True}
        if was == "running" and job.process is not None:
            _stop(job.process)
        stopped.append(job.id)
    return stopped


def _stop(process: subprocess.Popen) -> None:
    try:
        group = os.getpgid(process.pid)
    except ProcessLookupError:
        return
    for sig, wait in ((signal.SIGTERM, STOP_SECONDS), (signal.SIGKILL, STOP_SECONDS)):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def _quote(path: str) -> str:
    import shlex

    return shlex.quote(path)


def _tail(path: Path, lines: int = LOG_LINES) -> List[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [line.rstrip("\n") for line in deque(f, maxlen=lines)]
    except OSError:
        return []


def probe(output: Path) -> Dict[str, Any]:
    """ffprobe's view of a video: width, height, length in seconds, and which streams it has."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration,size:stream=codec_type,width,height", "-of", "json", str(output)],
                             capture_output=True, text=True, timeout=120)
        data = json.loads(out.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"probe_error": f"{type(exc).__name__}: {exc}"[:300]}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    fmt = data.get("format") or {}
    return {"width": video.get("width"), "height": video.get("height"),
            "duration_seconds": round(float(fmt.get("duration") or 0), 2),
            "streams": sorted({str(s.get("codec_type")) for s in streams if s.get("codec_type")})}


def freezes(output: Path) -> Dict[str, Any]:
    """ffmpeg's freezedetect (a still picture for 2 seconds or more) over the whole video."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(output), "-map", "0:v:0", "-vf",
                              "freezedetect=n=-60dB:d=2", "-f", "null", "-"], capture_output=True, text=True,
                             timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"freezedetect_error": f"{type(exc).__name__}: {exc}"[:300]}
    found: List[Dict[str, float]] = []
    for kind, value in FREEZE.findall(out.stderr or ""):
        if kind == "start":
            found.append({"start": float(value)})
        elif found and kind in ("duration", "end"):
            found[-1][kind] = float(value)
    return {"frozen": found, "frozen_at_end": bool(found and "end" not in found[-1])}


def _readable(found: Dict[str, Any]) -> bool:
    """ffprobe read a video from it: a video stream and a length."""
    return bool(found.get("output_exists") and "video" in (found.get("streams") or [])
                and float(found.get("duration_seconds") or 0) > 0)


def _candidates(job: Job) -> List[Path]:
    """Where the render's video may be, in order: where start_render said (from the render's folder, then the
    workspace), where the command says it writes, then the newest video written in the workspace since it began."""
    def resolved(name: str) -> List[Path]:
        p = Path(name)
        return [p] if p.is_absolute() else [Path(job.cwd) / p, Path(job.workspace) / p]

    out: List[Path] = resolved(job.output)
    for match in _OUTPUT_FLAG.finditer(job.command):
        out += resolved(match.group("path"))
    out += [p for token in reversed(job.command.split()) if token.strip("'\"").lower().endswith(VIDEO_EXT)
            for p in resolved(token.strip("'\""))][:2]
    began = (job.started_at or time.time()) - 1
    newest: List[Path] = []
    for folder, dirs, files in os.walk(job.workspace):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".jai")]
        for name in files:
            if name.lower().endswith(VIDEO_EXT):
                path = Path(folder) / name
                try:
                    if path.stat().st_mtime >= began:
                        newest.append(path)
                except OSError:
                    continue
    out += sorted(newest, key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    return list(dict.fromkeys(out))


def facts(job: Job) -> Dict[str, Any]:
    asked = Path(job.output) if os.path.isabs(job.output) else Path(job.cwd) / job.output
    out: Dict[str, Any] = {"exit_code": job.exit_code, "output": str(asked), "output_exists": False,
                           "seconds": int((job.ended_at or time.time()) - (job.started_at or time.time()))}
    for path in _candidates(job):
        if not path.is_file():
            continue
        found: Dict[str, Any] = {"output": str(path), "output_exists": True, "size_bytes": path.stat().st_size}
        found.update(probe(path))
        if _readable(found):
            found.update(freezes(path))
            out.update(found)
            if path.resolve() != asked.resolve():
                out["output_asked"] = str(asked)
                out["note"] = f"The video is at {path}, not at {asked} where start_render said."
            break
    if not out["output_exists"] and job.exit_code == 0:
        out["note"] = (f"The render exited 0 but no video ffprobe can read was found at {asked}, where its command "
                       "writes, or written in the workspace since it began.")
    out["log_tail"] = _tail(job.log)
    return out


def counts() -> Dict[str, int]:
    with _LOCK:
        return {"running": sum(j.status == "running" for j in JOBS.values()),
                "queued": sum(j.status == "queued" for j in JOBS.values())}
