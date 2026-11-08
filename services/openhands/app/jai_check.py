"""
jai-check: run a build, test, lint or acceptance command the way an agent should see it

  jai-check -- pnpm -r test          run it; print PASS or the failing lines, keep the full log
  jai-check --fresh -- task verify   run it even if an identical passing run is cached

An agent that reads a full test log pays for every line of it, every time, and an agent that re-runs a passing
check whose inputs have not changed pays for the run again. jai-check prints only what matters (PASS with the
duration, or the lines that look like failures plus the last lines of output) and keeps the whole log under
/tmp/jai-check/logs. A passing result is cached under a key made of the command, the working folder, the git
commit, the working tree's changes (tracked diffs and the content of new files) and the tool versions on PATH, so
it is reused only while none of those has changed. Failures are never cached. Outside a git repository nothing is
cached. The exit code is the command's own.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(os.environ.get("JAI_CHECK_DIR", "/tmp/jai-check"))
FAILURE = re.compile(r"(error|fail|failed|failure|✗|×|✕|panic|traceback|exception|cannot find|not found|"
                     r"no such file|denied|fatal|assert)", re.I)
MAX_FAILURE_LINES = 60
TAIL_LINES = 25
MAX_NEW_FILE_BYTES = 2_000_000


def _git(args: List[str], cwd: str) -> Optional[bytes]:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def state_key(command: str, cwd: str) -> Optional[str]:
    """What the result depends on, or None when it cannot be known (not a git repository)."""
    head = _git(["rev-parse", "HEAD"], cwd)
    if head is None:
        return None
    digest = hashlib.sha256()
    digest.update(command.encode())
    digest.update(os.path.realpath(cwd).encode())
    digest.update(head)
    digest.update(_git(["diff", "HEAD", "--binary"], cwd) or b"")
    untracked = (_git(["ls-files", "--others", "--exclude-standard", "-z"], cwd) or b"").split(b"\0")
    for name in sorted(n for n in untracked if n):
        path = Path(cwd) / name.decode(errors="replace")
        digest.update(name)
        try:
            if path.is_file() and path.stat().st_size <= MAX_NEW_FILE_BYTES:
                digest.update(path.read_bytes())
            else:
                digest.update(str(path.stat().st_size).encode())
        except OSError:
            continue
    digest.update(os.environ.get("PATH", "").encode())
    return digest.hexdigest()[:32]


def summarise(output: str) -> List[str]:
    lines = output.splitlines()
    picked = [line for line in lines if FAILURE.search(line)][:MAX_FAILURE_LINES]
    tail = [line for line in lines[-TAIL_LINES:] if line not in picked]
    return picked + (["--- last lines ---"] + tail if tail else [])


def run(command: str, cwd: str, fresh: bool = False) -> Tuple[int, str]:
    key = state_key(command, cwd)
    cache = ROOT / "passed" / f"{key}.json" if key else None
    if cache is not None and cache.exists() and not fresh:
        record = json.loads(cache.read_text())
        return 0, (f"PASS (cached: nothing it depends on has changed since {record['at']}, "
                   f"{record['seconds']:.0f}s) {command}\nfull log: {record['log']}")
    started = time.monotonic()
    done = subprocess.run(command, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, errors="replace")
    seconds = time.monotonic() - started
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    log = ROOT / "logs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{hashlib.sha1(command.encode()).hexdigest()[:8]}.log"
    log.write_text(done.stdout or "")
    if done.returncode == 0:
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"at": time.strftime("%H:%M:%S"), "seconds": seconds, "log": str(log)}))
        return 0, f"PASS ({seconds:.0f}s) {command}\nfull log: {log}"
    body = "\n".join(summarise(done.stdout or ""))
    return done.returncode, f"FAIL (exit {done.returncode}, {seconds:.0f}s) {command}\n{body}\nfull log: {log}"


def main(argv: List[str]) -> int:
    fresh = False
    args = list(argv)
    while args and args[0].startswith("--") and args[0] != "--":
        if args[0] == "--fresh":
            fresh = True
        args.pop(0)
    if args and args[0] == "--":
        args.pop(0)
    if not args:
        print(__doc__.strip().splitlines()[0])
        print("usage: jai-check [--fresh] -- <command>")
        return 2
    command = args[0] if len(args) == 1 else shlex.join(args)
    code, text = run(command, os.getcwd(), fresh)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
