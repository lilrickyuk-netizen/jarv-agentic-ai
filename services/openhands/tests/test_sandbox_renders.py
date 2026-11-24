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
