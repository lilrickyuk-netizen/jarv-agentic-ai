"""
24 November, Richard: renders run without AI. Real: the sandbox service's /renders API, its one-at-a-time queue, a
real ffmpeg render as a background process, ffprobe and freezedetect on the result, the log in the workspace. No
model is involved anywhere in a render.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

if "app.server" not in sys.modules:
    os.environ.setdefault("OPENHANDS_TOKEN", "sandbox-token-for-tests")
    os.environ.setdefault("JAI_GATEWAY_TOKEN", "gateway-token-must-never-reach-the-shell")
    os.environ.setdefault("WORKSPACE_ROOT", tempfile.mkdtemp(prefix="workspaces-"))

from fastapi.testclient import TestClient  # noqa: E402

from app import renders, server  # noqa: E402

AUTH = {"Authorization": "Bearer sandbox-token-for-tests"}
RENDER = ("ffmpeg -loglevel error -y -f lavfi -i testsrc=size=320x240:rate=25:duration={d} -f lavfi "
          "-i sine=frequency=440:duration={d} -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac {out}")


def _workspace() -> Path:
    folder = Path(tempfile.mkdtemp(prefix="mission-", dir=os.environ["WORKSPACE_ROOT"]))
    os.chmod(folder, 0o777)
    return folder


def _wait(client, job_id, seconds=120):
    deadline = time.time() + seconds
    while time.time() < deadline:
        view = client.get(f"/renders/{job_id}", headers=AUTH).json()
        if view["status"] in ("finished", "failed"):
            return view
        time.sleep(0.2)
    raise AssertionError(f"render {job_id} did not end")


def test_a_short_ffmpeg_render_runs_in_the_background_and_reports_its_facts(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    started = time.time()
    answer = client.post("/renders", headers=AUTH, json={
        "job_id": "render-ok-0001", "workspace": str(folder), "cwd": str(folder),
        "command": RENDER.format(d=2, out="final.mp4"), "output": "final.mp4"})
    assert answer.status_code == 200 and time.time() - started < 2  # the job id comes back straight away
    assert answer.json()["status"] in ("queued", "running")
    view = _wait(client, "render-ok-0001")
    facts = view["facts"]
    assert view["status"] == "finished" and view["exit_code"] == 0
    assert facts["output_exists"] and facts["size_bytes"] > 0
    assert (facts["width"], facts["height"]) == (320, 240) and 1.8 <= facts["duration_seconds"] <= 2.2
    assert facts["streams"] == ["audio", "video"] and facts["frozen"] == [] and facts["frozen_at_end"] is False
    log = folder / ".jai" / "renders" / "render-ok-0001.log"
    assert log.is_file() and "$ ffmpeg" in log.read_text() and facts["log_tail"][0].startswith("$ ffmpeg")


def test_a_failing_render_reports_its_exit_code_and_log_lines(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    client.post("/renders", headers=AUTH, json={
        "job_id": "render-bad-0001", "workspace": str(folder), "cwd": str(folder),
        "command": "ffmpeg -loglevel error -i missing-scene.mp4 out.mp4", "output": "out.mp4"})
    view = _wait(client, "render-bad-0001")
    assert view["status"] == "failed" and view["exit_code"] != 0
    assert view["facts"]["output_exists"] is False
    assert any("missing-scene.mp4" in line for line in view["facts"]["log_tail"])


def test_one_render_at_a_time_the_next_waits_its_turn(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    for job, d in (("render-q-0001", 3), ("render-q2-0002", 1)):   # two missions' renders
        client.post("/renders", headers=AUTH, json={
            "job_id": job, "workspace": str(folder), "cwd": str(folder),
            "command": RENDER.format(d=d, out=f"{job}.mp4"), "output": f"{job}.mp4"})
    second = client.get("/renders/render-q2-0002", headers=AUTH).json()
    assert second["status"] == "queued" and second["position"] >= 1
    first, second = _wait(client, "render-q-0001"), _wait(client, "render-q2-0002")
    assert first["status"] == second["status"] == "finished"
    assert renders.JOBS["render-q2-0002"].started_at >= renders.JOBS["render-q-0001"].ended_at  # never together


def test_a_render_outside_the_workspace_or_without_the_token_is_refused(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    body = {"job_id": "render-x-0001", "workspace": str(folder), "cwd": "/etc", "command": "true", "output": "x"}
    assert client.post("/renders", headers=AUTH, json=body).status_code == 400
    assert client.post("/renders", json={**body, "cwd": str(folder)}).status_code == 401
    assert client.get("/renders/render-x-0001", headers=AUTH).status_code == 404


# 24 November: mission 6c748110 had 1 render running and 2 queued, all its own. One render per mission, and a
# cancelled mission's renders stop.
SLOW = ("ffmpeg -loglevel error -y -re -f lavfi -i testsrc=size=320x240:rate=25:duration=60 -c:v libx264 "
        "-pix_fmt yuv420p {out}")


def _job_processes(folder: Path) -> list:
    import subprocess

    out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if str(folder) in line or "slow-" in line and "ffmpeg" in line]


def test_a_mission_gets_one_render_a_second_request_returns_the_first(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    body = {"workspace": str(folder), "cwd": str(folder), "command": SLOW.format(out="one.mp4"), "output": "one.mp4"}
    first = client.post("/renders", headers=AUTH, json={**body, "job_id": "render-onemiss-0001"}).json()
    again = client.post("/renders", headers=AUTH, json={**body, "job_id": "render-onemiss-0002"}).json()
    try:
        assert first["existing"] is False and again["existing"] is True
        assert again["job_id"] == "render-onemiss-0001" and "render-onemiss-0002" not in renders.JOBS
        assert [j.id for j in renders.active_for("render-onemiss-")] == ["render-onemiss-0001"]
    finally:
        client.post("/renders/cancel", headers=AUTH, json={"mission": "onemiss"})


def test_cancelling_a_mission_stops_its_running_render_and_drops_its_queued_one(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    client.post("/renders", headers=AUTH, json={"job_id": "render-cancela-0001", "workspace": str(folder),
                                                 "cwd": str(folder), "command": SLOW.format(out="slow-a.mp4"),
                                                 "output": "slow-a.mp4"})
    client.post("/renders", headers=AUTH, json={"job_id": "render-cancelb-0001", "workspace": str(folder),
                                                 "cwd": str(folder), "command": SLOW.format(out="slow-b.mp4"),
                                                 "output": "slow-b.mp4"})
    deadline = time.time() + 30
    while renders.JOBS["render-cancela-0001"].status != "running" and time.time() < deadline:
        time.sleep(0.2)
    time.sleep(1)
    assert renders.JOBS["render-cancela-0001"].status == "running"
    assert renders.JOBS["render-cancelb-0001"].status == "queued"
    assert client.post("/renders/cancel", json={"mission": "cancelb"}).status_code == 401
    dropped = client.post("/renders/cancel", headers=AUTH, json={"mission": "cancelb"}).json()
    assert dropped["cancelled"] == ["render-cancelb-0001"]
    began = time.time()
    stopped = client.post("/renders/cancel", headers=AUTH, json={"mission": "cancela"}).json()
    assert stopped["cancelled"] == ["render-cancela-0001"] and time.time() - began < 15
    view = client.get("/renders/render-cancela-0001", headers=AUTH).json()
    assert view["status"] == "cancelled" and view["facts"].get("cancelled") is True
    deadline = time.time() + 15
    while time.time() < deadline and any("slow-a.mp4" in line for line in _job_processes(folder)):
        time.sleep(0.2)
    left = [line for line in _job_processes(folder) if "slow-a.mp4" in line]
    assert not left, left   # its process group is gone
    assert client.get("/renders/render-cancelb-0001", headers=AUTH).json()["status"] == "cancelled"
    assert renders.counts() == {"running": 0, "queued": 0}


# 24 November, mission 5670069a: "Render failed · exit 0" over a Node warning on stderr and a file written elsewhere.
WARN = "echo '(node:42) MaxListenersExceededWarning: Possible EventEmitter memory leak detected.' >&2; "


def test_exit_0_with_warnings_on_stderr_and_the_file_present_is_finished(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    client.post("/renders", headers=AUTH, json={
        "job_id": "render-warn-0001", "workspace": str(folder), "cwd": str(folder),
        "command": WARN + RENDER.format(d=1, out="final.mp4"), "output": "final.mp4"})
    view = _wait(client, "render-warn-0001")
    assert view["status"] == "finished" and view["exit_code"] == 0, view
    assert view["facts"]["output"] == str(folder / "final.mp4") and "note" not in view["facts"]
    assert any("MaxListenersExceededWarning" in line for line in view["facts"]["log_tail"])


def test_a_video_written_somewhere_else_is_finished_and_says_where(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    (folder / "renders").mkdir()
    os.chmod(folder / "renders", 0o777)
    client.post("/renders", headers=AUTH, json={
        "job_id": "render-else-0001", "workspace": str(folder), "cwd": str(folder),
        "command": WARN + RENDER.format(d=1, out="renders/segment-01.mp4"), "output": "final.mp4"})
    view = _wait(client, "render-else-0001")
    assert view["status"] == "finished", view
    assert view["facts"]["output"] == str(folder / "renders" / "segment-01.mp4")
    assert view["facts"]["output_asked"] == str(folder / "final.mp4")
    assert "renders/segment-01.mp4" in view["facts"]["note"] and view["facts"]["duration_seconds"] > 0


def test_exit_0_with_no_video_anywhere_is_failed_and_says_why(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    client.post("/renders", headers=AUTH, json={
        "job_id": "render-none-0001", "workspace": str(folder), "cwd": str(folder),
        "command": WARN + "true", "output": "final.mp4"})
    view = _wait(client, "render-none-0001")
    assert view["status"] == "failed" and view["exit_code"] == 0
    assert "exited 0 but no video" in view["facts"]["note"]


# 24 November, mission bb2a4d3c: HyperFrames' pre-render check hit the terminal's 300 s limit and the agent switched it
# off. Long checks run in the same no-AI queue; a check makes no video, so its exit code is its verdict.
def test_a_long_check_runs_in_the_queue_and_its_exit_code_is_its_verdict(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    for job, code in (("render-chka-0001", 0), ("render-chkb-0001", 3)):
        answer = client.post("/renders", headers=AUTH, json={
            "job_id": job, "workspace": str(folder), "cwd": str(folder), "kind": "check",
            "command": f"echo 'lint: {code} problem(s) found'; exit {code}"})
        assert answer.status_code == 200, answer.text
    passed, failed = _wait(client, "render-chka-0001"), _wait(client, "render-chkb-0001")
    assert passed["status"] == "finished" and passed["kind"] == "check" and passed["facts"]["exit_code"] == 0
    assert "output_exists" not in passed["facts"] and "lint: 0 problem(s) found" in passed["facts"]["log_tail"]
    assert failed["status"] == "failed" and failed["facts"]["exit_code"] == 3


def test_the_sandbox_rules_say_never_switch_a_check_off_for_a_time_limit():
    assert "Never switch a check off, skip it, cut it short or edit a script to get round a time limit" in \
        server.ENGINEERING_RULES and "start_render" in server.ENGINEERING_RULES


def test_a_render_a_time_limit_stopped_is_reported_as_a_timeout_not_a_failure(monkeypatch):
    """24 November, mission bb2a4d3c: OpenMontage stopped HyperFrames at timeout=1800, its timeout path raised "can't
    concat str to bytes", the wrapper exited 0, and the card said "Render failed · exit 0"."""
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    client.post("/renders", headers=AUTH, json={
        "job_id": "render-tout-0001", "workspace": str(folder), "cwd": str(folder), "output": "ep03.mp4",
        "command": "echo 'hyperframes render [timeout after 1800s]'; echo \"TypeError: can't concat str to bytes\""})
    view = _wait(client, "render-tout-0001")
    assert view["status"] == "failed" and view["exit_code"] == 0
    assert view["facts"]["timed_out"] is True and "1800 s" in view["facts"]["timeout"]
    assert "note" not in view["facts"]


# 25 November, mission 1d110524 (5 clips): several renders as one job, run in order, each with its own facts.
def test_a_batch_runs_its_renders_in_order_as_one_job_and_reports_each(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    steps = [{"command": WARN + RENDER.format(d=1, out="clip-01.mp4"), "cwd": str(folder), "output": "clip-01.mp4"},
             {"command": "echo 'no source'; exit 1", "cwd": str(folder), "output": "clip-02.mp4"},
             {"command": RENDER.format(d=2, out="clip-03.mp4"), "cwd": str(folder), "output": "clip-03.mp4"}]
    answer = client.post("/renders", headers=AUTH, json={
        "job_id": "render-batch-0001", "workspace": str(folder), "cwd": str(folder),
        "command": steps[0]["command"], "output": "clip-01.mp4", "steps": steps})
    assert answer.status_code == 200 and answer.json()["steps"] == 3
    view = _wait(client, "render-batch-0001")
    facts = view["facts"]
    assert view["status"] == "failed" and facts["kind"] == "batch"
    assert [s["status"] for s in facts["steps"]] == ["finished", "failed", "finished"]   # all ran, in order
    assert facts["finished"] == 2 and facts["failed"] == 1 and facts["exit_code"] == 1
    assert facts["steps"][0]["output"] == str(folder / "clip-01.mp4") and facts["steps"][2]["duration_seconds"] > 1
    log = (folder / ".jai" / "renders" / "render-batch-0001.log").read_text()
    assert log.index("[step 1 of 3]") < log.index("[step 2 of 3]") < log.index("[step 3 of 3]")
    assert renders.counts() == {"running": 0, "queued": 0}


def test_a_batch_step_outside_the_workspace_is_refused(monkeypatch):
    monkeypatch.setitem(server.SECRETS, "OPENHANDS_TOKEN", "sandbox-token-for-tests")
    client = TestClient(server.app)
    folder = _workspace()
    answer = client.post("/renders", headers=AUTH, json={
        "job_id": "render-batchx-0001", "workspace": str(folder), "cwd": str(folder), "command": "true",
        "output": "a.mp4", "steps": [{"command": "true", "cwd": str(folder), "output": "a.mp4"},
                                     {"command": "true", "cwd": "/etc", "output": "b.mp4"}]})
    assert answer.status_code == 400 and "/etc" in answer.text


def test_a_renders_sound_is_measured_and_a_silent_one_is_named(tmp_path):
    """26 November: a studio video had no sound. OpenMontage's Explainer plays its clips muted, and Remotion still
    writes an audio track, so the streams said nothing. ffmpeg's volumedetect measures it (real ffmpeg here)."""
    import subprocess

    def make(name, *audio):
        path = tmp_path / name
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=2",
                        *audio, "-shortest", "-pix_fmt", "yuv420p", str(path)], check=True)
        return path

    speech = make("speech.mp4", "-f", "lavfi", "-i", "sine=frequency=440:duration=2")
    muted = make("muted.mp4", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo")
    none = make("none.mp4")
    loud = renders.loudness(speech, renders.probe(speech)["streams"])
    assert loud["silent"] is False and loud["max_volume_db"] > -30
    quiet = renders.loudness(muted, renders.probe(muted)["streams"])
    assert "audio" in renders.probe(muted)["streams"] and quiet["silent"] is True and quiet["max_volume_db"] <= -60
    assert renders.loudness(none, renders.probe(none)["streams"]) == {"silent": True, "sound": "no audio track"}
