"""
Wave 4a, images: JAI makes images on Richard's own GPU with ComfyUI and FLUX.1-schnell (Apache-2.0), saves each in
the workspace with its licence and prompt recorded, and puts it on his screen through a short-lived link. Real: the
image module's ComfyUI conversation (against an httpx MockTransport), the toolbox and runtime with a sandbox
workspace folder, the image link and the route that serves it. No GPU or ComfyUI is needed.
"""
import asyncio
import json

import httpx
import pytest

from app.core.agents.base import AuthorityLevel
from app.core.agents.specialists.content import ContentAgent
from app.core.agents.toolbox import AgentToolbox
from app.core.config import settings
from app.core.creative import images
from app.core.voice import live
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12c_agent_tools import _agent, _ctx, _seed, project  # noqa: F401 - project is a fixture

PNG = b"\x89PNG\r\n\x1a\n" + b"jai-image" * 50


def _run(coro):
    return asyncio.run(coro)


def test_the_flux_schnell_graph_and_the_named_shapes():
    graph = images.workflow("A 'Plexecute' launch banner, neon on black", 1280, 720, 42)
    assert graph["1"]["inputs"]["unet_name"] == images.UNET
    assert graph["2"]["inputs"] == {"clip_name1": images.CLIP_L, "clip_name2": images.T5, "type": "flux"}
    assert graph["6"]["inputs"]["steps"] == 4 and graph["6"]["inputs"]["cfg"] == 1.0 and graph["6"]["inputs"]["seed"] == 42
    assert graph["5"]["inputs"]["width"] == 1280 and graph["9"]["class_type"] == "SaveImage"
    assert images.size_of("thumbnail") == (1280, 720) and images.size_of("story") == (768, 1344)
    assert images.size_of(None, 5000, 100) == (1536, 256)  # held to what the card and model can do
    assert images.default_path("Launch day: Plexecute!").startswith("assets/images/launch-day-plexecute-")


def test_an_image_is_made_collected_and_the_memory_released():
    seen = []
    polls = {"n": 0}

    def answer(request: httpx.Request):
        seen.append((request.method, request.url.path))
        if request.url.path == "/prompt":
            assert json.loads(request.content)["prompt"]["3"]["inputs"]["text"] == "A calm desk at dawn"
            return httpx.Response(200, json={"prompt_id": "p1", "number": 1})
        if request.url.path == "/history/p1":
            polls["n"] += 1
            if polls["n"] < 2:
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"p1": {"status": {"status_str": "success"}, "outputs": {
                "9": {"images": [{"filename": "jai_00001_.png", "subfolder": "", "type": "output"}]}}}})
        if request.url.path == "/view":
            assert request.url.params["filename"] == "jai_00001_.png"
            return httpx.Response(200, content=PNG)
        if request.url.path == "/free":
            assert json.loads(request.content) == {"unload_models": True, "free_memory": True}
            return httpx.Response(200)
        return httpx.Response(404)

    settings.COMFYUI_URL = "http://comfyui:8188"
    try:
        client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
        made = _run(images.generate("A calm desk at dawn", 1024, 1024, seed=7, client=client))
    finally:
        settings.COMFYUI_URL = ""
    assert made["png"] == PNG and made["seed"] == 7
    assert ("POST", "/free") in seen and seen[0] == ("POST", "/prompt")


def test_a_failed_image_and_a_generator_that_is_off_are_reported_plainly(monkeypatch):
    with pytest.raises(images.ImageUnavailable, match="turned off"):
        _run(images.generate("anything"))
    monkeypatch.setattr(settings, "COMFYUI_URL", "http://comfyui:8188")

    def answer(request):
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p2"})
        return httpx.Response(200, json={"p2": {"status": {"status_str": "error", "messages": [
            ["execution_error", {"exception_message": "CUDA out of memory"}]]}}})

    with pytest.raises(images.ImageUnavailable, match="CUDA out of memory"):
        _run(images.generate("anything", client=httpx.AsyncClient(transport=httpx.MockTransport(answer))))


def test_an_agent_saves_the_image_in_the_workspace_with_its_licence_and_it_can_be_shown(project, monkeypatch, client):
    root_host, root, _ = project

    async def fake_generate(prompt, width=1024, height=1024, seed=None, client=None):
        return {"png": PNG, "seed": 11, "seconds": 42.0, "width": width, "height": height}

    monkeypatch.setattr(images, "generate", fake_generate)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, root_host)
            agent = _agent(ContentAgent, ws_id, user_id, AuthorityLevel.LEVEL_3_CODE_EXECUTION)
            box = await AgentToolbox(agent, _ctx(db, ws_id, user_id)).prepare()
            made = await box.call("generate_image", {"prompt": "Plexecute waitlist banner, \"Join the waitlist\"",
                                                      "shape": "banner"})
            await db.commit()
            return box.available, made

    available, made = _run(run())
    assert "generate_image" in available and made["success"] is True, made
    saved = list((root / "assets" / "images").glob("plexecute-waitlist-banner-*.png"))
    assert len(saved) == 1 and saved[0].read_bytes() == PNG
    licences = (root / "ASSET_LICENCES.md").read_text()
    assert "FLUX.1-schnell" in licences and "Apache-2.0" in licences and "Join the waitlist" in licences
    assert "assets/images/plexecute-waitlist-banner-" in licences and "1536x512" in licences

    link = _run(live.image_link(made["container_path"]))
    served = client.get(link.replace("/api/backend", ""))   # no sign-in: the token is the permission
    assert served.status_code == 200 and served.content == PNG and served.headers["content-type"] == "image/png"
    assert client.get("/api/voice/image/not-a-real-token").status_code == 404
    assert _run(live.image_for("x" * 80)) is None


def test_the_voice_asks_which_workspace_an_image_is_for(monkeypatch):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, _ = await _seed(db, None)
            return await live.run_tool(db, user_id, "make_image", {"prompt": "A logo", "workspace": "Nowhere"})

    output = _run(run())
    assert "Say which workspace" in output["error"]
    assert "make_image" in {t["name"] for t in live.VOICE_TOOLS}
