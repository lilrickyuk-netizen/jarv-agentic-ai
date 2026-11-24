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
  sandbox before).

When it ends, the facts are worked out here, where the file is: the exit code, whether the output exists and its
size, ffprobe's width, height, length and streams, ffmpeg's freezedetect on the whole video, and the last 50 lines
of the log. JAI's backend reads them every 30 seconds (a Celery job, no AI) and resumes the mission with them.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
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
FREEZE = re.compile(r"freeze_(start|duration|end): ([\d.]+)")


def _iso(moment: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(moment, timezone.utc).isoformat(timespec="seconds") if moment else None


class Job:
    def __init__(self, job_id: str, workspace: str, command: str, cwd: str, output: str):
        self.id, self.workspace, self.command, self.cwd, self.output = job_id, workspace, command, cwd, output
        self.status = "queued"  # queued, running, finished, failed
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
                "output": self.output, "log": str(self.log), "exit_code": self.exit_code,
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


def submit(job_id: str, workspace: str, command: str, cwd: str, output: str) -> Job:
    global _WORKER
    with _LOCK:
        if job_id in JOBS:
            raise ValueError(f"Render {job_id} exists already.")
        job = Job(job_id, workspace, command, cwd, output)
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
        job.exit_code = job.process.wait()
    job.ended_at = time.time()
    job.facts = facts(job)
    job.status = "finished" if job.exit_code == 0 and job.facts.get("output_exists") else "failed"
    logger.info("render %s %s (exit %s) in %ss", job.id, job.status, job.exit_code,
                int(job.ended_at - job.started_at))


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


def facts(job: Job) -> Dict[str, Any]:
    output = Path(job.output) if os.path.isabs(job.output) else Path(job.cwd) / job.output
    out: Dict[str, Any] = {"exit_code": job.exit_code, "output": str(output), "output_exists": output.is_file(),
                           "seconds": int((job.ended_at or time.time()) - (job.started_at or time.time()))}
    if output.is_file():
        out["size_bytes"] = output.stat().st_size
        out.update(probe(output))
        out.update(freezes(output))
    out["log_tail"] = _tail(job.log)
    return out


def counts() -> Dict[str, int]:
    with _LOCK:
        return {"running": sum(j.status == "running" for j in JOBS.values()),
                "queued": sum(j.status == "queued" for j in JOBS.values())}
