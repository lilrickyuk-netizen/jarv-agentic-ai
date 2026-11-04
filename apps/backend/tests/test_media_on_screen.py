"""
JAI puts a workspace's images and videos on Richard's screen as themselves (not their bytes as text): one file as a
picture or a player, a folder as a gallery of its images and videos (subfolders too, newest first), each through a
short-lived link served with its real media type and only from inside the workspaces.
"""
import asyncio
import os
import time

from app.core.voice import live
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12c_agent_tools import _seed, project  # noqa: F401 - project is a fixture

PNG = b"\x89PNG\r\n\x1a\n" + b"plexecute" * 40
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 400


def _run(coro):
    return asyncio.run(coro)


def test_an_image_a_video_and_a_folder_go_on_screen_as_media(project, client):
    root_host, root, _ = project
    (root / "images").mkdir()
    (root / "images" / "jai-test-image.png").write_bytes(PNG)
    (root / "videos").mkdir()
    (root / "videos" / "launch.mp4").write_bytes(MP4)
    later = time.time() + 5
    os.utime(root / "videos" / "launch.mp4", (later, later))

    async def show(path):
        async with AsyncTestingSessionLocal() as db:
            user_id, _ = await _seed(db, root_host)
            return await live.run_tool(db, user_id, "show_on_screen", {"what": "file", "workspace": "R12c",
                                                                        "path": path})

    image = _run(show("images/jai-test-image.png"))["card"]
    assert image["kind"] == "image" and image["sections"][0]["image"].startswith("/api/backend/api/voice/image/")
    assert "code" not in image["sections"][0]                       # never its bytes as text
    served = client.get(image["sections"][0]["image"].replace("/api/backend", ""))
    assert served.status_code == 200 and served.headers["content-type"] == "image/png" and served.content == PNG

    video = _run(show("videos/launch.mp4"))["card"]
    assert video["kind"] == "video"
    played = client.get(video["sections"][0]["video"].replace("/api/backend", ""))
    assert played.status_code == 200 and played.headers["content-type"] == "video/mp4"

    gallery = _run(show(""))["card"]
    assert gallery["kind"] == "gallery"
    assert [s["heading"] for s in gallery["sections"]] == ["videos/launch.mp4", "images/jai-test-image.png"]
    assert "video" in gallery["sections"][0] and "image" in gallery["sections"][1]

    text = _run(show("src/app.py"))["card"]                         # a text file is still shown as text
    assert text["kind"] == "file" and "def add" in text["sections"][0]["code"]
    assert "error" in _run(show("../outside.png"))
