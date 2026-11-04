"""
Wave 4b-d, content: voiceovers in JAI's natural voice, short videos (JAI writes and narrates, its GPU makes the
footage, MoneyPrinterTurbo renders), and social posts drafted in Postiz (never scheduled or published by JAI).
Real: the modules' conversations with Chatterbox, MoneyPrinterTurbo and Postiz (against httpx MockTransports), the
toolbox and runtime with a sandbox workspace folder. No GPU, Chatterbox, MoneyPrinterTurbo or Postiz is needed.
"""
import asyncio
import io
import json
import wave

import httpx
import pytest

from app.core.agents.base import AuthorityLevel
from app.core.agents.specialists.content import ContentAgent
from app.core.agents.toolbox import AgentToolbox
from app.core.config import settings
from app.core.creative import images, social, videos, voiceover
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12c_agent_tools import _agent, _ctx, _seed, project  # noqa: F401 - project is a fixture

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"jai-video" * 200


def _run(coro):
    return asyncio.run(coro)


def test_a_voiceover_is_spoken_sentence_by_sentence_into_one_wav(monkeypatch):
    monkeypatch.setattr(settings, "CHATTERBOX_URL", "http://chatterbox:8770")
    said = []

    def answer(request):
        said.append(json.loads(request.content))
        return httpx.Response(200, content=b"\x01\x00" * 24000)  # one second each

    made = _run(voiceover.speak("Plan your life. Execute the plan! Join the waitlist today?",
                                client=httpx.AsyncClient(transport=httpx.MockTransport(answer))))
    assert [s["text"] for s in said] == ["Plan your life.", "Execute the plan!", "Join the waitlist today?"]
    assert said[0]["voice"] == settings.VOICE_PIPELINE_CHATTERBOX_VOICE
    with wave.open(io.BytesIO(made["wav"])) as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1
        assert w.getnframes() == 3 * 24000 + 3 * int(24000 * voiceover.PAUSE_SECONDS)
    assert made["sentences"] == 3 and made["seconds"] == pytest.approx(3.8, abs=0.1)
    assert list(voiceover.sentences("a" * 650))[0] == "a" * 300   # long sentences are split
    with pytest.raises(voiceover.VoiceoverUnavailable, match="turned off"):
        monkeypatch.setattr(settings, "CHATTERBOX_URL", "")
        _run(voiceover.speak("Hello."))


def test_the_video_plan_is_read_from_the_model_and_filled_in_when_short():
    plan = videos.parse_plan('Here: {"title": "Plan it", "script": "Plan your life.  Execute it.", '
                             '"terms": ["planner", "goals"], "image_prompts": ["a desk at dawn"]}', "Plexecute", 3)
    assert plan["script"] == "Plan your life. Execute it." and plan["terms"] == ["planner", "goals"]
    assert len(plan["image_prompts"]) == 3 and plan["image_prompts"][0] == "a desk at dawn"
    assert videos.parse_plan("no json", "Plexecute", 2)["terms"] == ["Plexecute"]


def test_a_video_is_rendered_by_the_video_maker(monkeypatch):
    monkeypatch.setattr(settings, "MONEYPRINTER_URL", "http://moneyprinter:8090")
    seen = {}

    def answer(request):
        seen["body"] = request.content
        return httpx.Response(200, content=MP4, headers={"content-type": "video/mp4"})

    mp4 = _run(videos.render({"subject": "x", "script": "Hello."}, b"RIFFwav", [b"png1", b"png2"],
                             client=httpx.AsyncClient(transport=httpx.MockTransport(answer))))
    assert mp4 == MP4 and b'name="narration"' in seen["body"] and seen["body"].count(b'name="images"') == 2


def test_an_agent_makes_a_narrated_video_and_a_voiceover_in_the_workspace(project, monkeypatch):
    root_host, root, _ = project

    async def plan(topic, seconds, audience, scenes):
        return {"title": "Plexecute in 30 seconds", "script": "Plan your life. Execute the plan.",
                "terms": ["planning"], "image_prompts": [f"scene {i}" for i in range(scenes)]}

    async def speak(text, voice=None, client=None):
        return {"wav": b"RIFF" + b"\x00" * 100, "seconds": 30.0, "sentences": 2, "voice": "george"}

    async def generate(prompt, width=1024, height=1024, seed=None, client=None):
        return {"png": b"\x89PNG" + prompt.encode(), "seed": 1, "seconds": 1.0, "width": width, "height": height}

    async def render(spec, wav, stills, client=None):
        assert spec["subtitles"] is True and spec["aspect"] == "portrait" and len(stills) == 4
        return MP4

    async def no_stock():
        return False

    monkeypatch.setattr(videos, "plan_video", plan)
    monkeypatch.setattr(videos, "render", render)
    monkeypatch.setattr(videos, "stock_available", no_stock)
    monkeypatch.setattr(voiceover, "speak", speak)
    monkeypatch.setattr(images, "generate", generate)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, root_host)
            box = await AgentToolbox(_agent(ContentAgent, ws_id, user_id, AuthorityLevel.LEVEL_3_CODE_EXECUTION),
                                     _ctx(db, ws_id, user_id)).prepare()
            video = await box.call("make_video", {"brief": "Plexecute waitlist launch", "seconds": 30})
            voice = await box.call("make_voiceover", {"text": "Welcome to Plexecute."})
            await db.commit()
            return box.available, video, voice

    available, video, voice = _run(run())
    assert {"make_video", "make_voiceover", "social_draft", "social_channels"} <= set(available)
    assert video["success"] is True and video["footage"] == "4 generated images", video
    saved = list((root / "assets" / "videos").glob("plexecute-waitlist-launch-*.mp4"))
    assert len(saved) == 1 and saved[0].read_bytes() == MP4
    assert saved[0].with_suffix("").with_suffix(".script.txt").exists() or \
        list((root / "assets" / "videos").glob("*.script.txt"))
    assert voice["success"] is True and list((root / "assets" / "audio").glob("welcome-to-plexecute-*.wav"))
    licences = (root / "ASSET_LICENCES.md").read_text()
    assert "MoneyPrinterTurbo (MIT)" in licences and "FLUX.1-schnell" in licences and "Chatterbox Turbo" in licences


def test_posts_are_only_ever_drafted_in_postiz(monkeypatch):
    with pytest.raises(social.SocialUnavailable, match="turned off"):
        _run(social.channels())
    monkeypatch.setattr(settings, "POSTIZ_URL", "http://postiz:5000/api")
    with pytest.raises(social.SocialUnavailable, match="POSTIZ_API_KEY"):
        _run(social.channels())
    monkeypatch.setattr(settings, "POSTIZ_API_KEY", "pz-test-key")
    sent = []

    def answer(request):
        sent.append(request)
        assert request.headers["authorization"] == "pz-test-key"
        if request.url.path == "/api/public/v1/integrations":
            return httpx.Response(200, json=[{"id": "li1", "name": "Richard on LinkedIn", "identifier": "linkedin"},
                                             {"id": "x1", "name": "@plexecute", "identifier": "x"}])
        if request.url.path == "/api/public/v1/posts":
            return httpx.Response(200, json=[{"postId": "p1", "integration": "li1"}])
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    drafted = _run(social.draft("Plexecute's waitlist is open.", ["linkedin"],
                                [{"id": "m1", "path": "/uploads/a.png"}], client=client))
    body = json.loads(sent[-1].content)
    assert body["type"] == "draft" and len(body["posts"]) == 1 and body["posts"][0]["integration"]["id"] == "li1"
    assert body["posts"][0]["value"][0]["image"] == [{"id": "m1", "path": "/uploads/a.png"}]
    assert drafted["channels"] == ["Richard on LinkedIn"] and "nothing is published" in drafted["note"]
    with pytest.raises(social.SocialUnavailable, match="None of those channels"):
        _run(social.draft("x", ["tiktok"], client=client))
