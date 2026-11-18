"""
18 November: ComfyUI held 5.7 GB of memory for 19 hours with nothing to make, and the computer swapped until other
services were killed. It is now started when an image is asked for and stopped when it has made nothing for
IDLE_STOP_MINUTES. Real: the image module, Redis (the test double) and the Docker adapter's rules; the Docker proxy
itself is replaced by a recorded answer. Nothing is spent.
"""
import asyncio

import httpx

from app.core.creative import images
from app.core.ops import docker_ops


def _run(coro):
    return asyncio.run(coro)


class Ops:
    """The restricted Docker proxy's answers for one ComfyUI container."""

    def __init__(self, running: bool):
        self.running = running
        self.switched = []
        self.available = True

    async def containers(self):
        return [docker_ops.Container(id="c1", name="jarv-comfyui", service="comfyui",
                                     state="running" if self.running else "exited", status="", health=None,
                                     restart_count=0, image="comfyui")]

    async def switch(self, service, on):
        assert service == "comfyui"
        self.switched.append(on)
        self.running = on
        return {"service": service, "on": on, "changed": ["jarv-comfyui"]}


async def _clear():
    from app.core.redis import get_redis

    redis = await get_redis()
    await redis.delete(images.LAST_USED_KEY, images.BUSY_KEY)
    return redis


def test_a_stopped_generator_is_started_and_waited_for(monkeypatch):
    ops = Ops(running=False)
    monkeypatch.setattr(docker_ops, "get_docker_ops", lambda: ops)

    def answer(request):
        return httpx.Response(200 if ops.running else 503, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    assert _run(images.wake(client, "http://comfyui:8188", wait_seconds=10)) is True
    assert ops.switched == [True]
    assert _run(images.wake(client, "http://comfyui:8188", wait_seconds=10)) is True
    assert ops.switched == [True]  # already answering: nothing started twice


def test_an_idle_generator_is_stopped_and_a_busy_or_recent_one_is_not(monkeypatch):
    ops = Ops(running=True)
    monkeypatch.setattr(docker_ops, "get_docker_ops", lambda: ops)

    async def run():
        redis = await _clear()
        first = await images.stop_if_idle(now=1000.0)              # seen running, no record: gets its time
        recent = await images.stop_if_idle(now=1000.0 + 5 * 60)
        await redis.set(images.BUSY_KEY, "1")
        busy = await images.stop_if_idle(now=1000.0 + 60 * 60)
        await redis.delete(images.BUSY_KEY)
        idle = await images.stop_if_idle(now=1000.0 + 11 * 60)
        after = await images.stop_if_idle(now=1000.0 + 20 * 60)
        return first, recent, busy, idle, after

    first, recent, busy, idle, after = _run(run())
    assert first["reason"] == "first seen running" and recent["stopped"] is False
    assert busy["reason"] == "making an image"
    assert idle["stopped"] is True and ops.switched == [False]
    assert after["reason"] == "not running"


def test_making_an_image_marks_the_generator_used_and_busy_only_while_it_works(monkeypatch):
    monkeypatch.setattr(images, "comfyui_url", lambda: "http://comfyui:8188")
    seen = {}

    async def answer_async(request):
        from app.core.redis import get_redis

        if request.url.path == "/prompt":
            seen["busy"] = await (await get_redis()).get(images.BUSY_KEY)
            return httpx.Response(200, json={"prompt_id": "p9"})
        if request.url.path == "/history/p9":
            return httpx.Response(200, json={"p9": {"status": {"status_str": "success"}, "outputs": {
                "9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}}}})
        if request.url.path == "/view":
            return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nimage")
        return httpx.Response(200, json={})

    async def run():
        redis = await _clear()
        client = httpx.AsyncClient(transport=httpx.MockTransport(answer_async))
        await images.generate("A desk at dawn", client=client)
        return await redis.get(images.BUSY_KEY), await redis.get(images.LAST_USED_KEY)

    busy_after, last_used = _run(run())
    assert seen["busy"] is not None and busy_after is None and last_used is not None


def test_the_worker_checks_for_an_idle_generator_on_a_schedule():
    from app.core.celery import SCHEDULED_JOBS, celery_app
    from app.workers import tasks

    assert any(e["task"] == "stop_idle_image_generator" for e in celery_app.conf.beat_schedule.values())
    assert any(j["task"] == "stop_idle_image_generator" for j in SCHEDULED_JOBS)
    assert callable(tasks.stop_idle_image_generator)
