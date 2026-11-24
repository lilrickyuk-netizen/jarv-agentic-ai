"""
JAI Backend - Images (Wave 4a)

Images are made on Richard's own graphics card by JAI's ComfyUI (open source) with FLUX.1-schnell (Apache-2.0,
commercial use allowed), compressed (GGUF) to fit a 6 GB card. ComfyUI runs on an internal network with no
internet; only JAI's backend and worker reach it. After each image ComfyUI is asked to release its memory, so the
rest of JAI keeps its share.

Every image is saved into the workspace (assets/images/ unless another path inside it is given) and recorded in the
workspace's ASSET_LICENCES.md with the model, its licence and the prompt, so where each asset came from is known.

18 November: ComfyUI held 5.7 GB of the computer's memory for 19 hours with nothing to make, while Docker had about
10 GB in all; the computer swapped and other services were killed. Releasing the model after each image does not
give that memory back, stopping the container does. So ComfyUI is started when an image is asked for (through JAI's
restricted Docker proxy, docker_ops.switch) and stopped when it has made nothing for IDLE_STOP_MINUTES.

24 November (audit batch 1): ComfyUI now takes all but 1 GB of the 6 GB card (services/comfyui/Dockerfile), so the
natural voice, Chatterbox, which holds its model on the same card, is switched off while an image is made and
switched back on straight after, when it was on before. The live conversation itself keeps running; it speaks with
Kokoro for those moments, as it does whenever Chatterbox is off.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

MODEL = "FLUX.1-schnell (GGUF Q4_K_S)"
LICENCE = "Apache-2.0 (FLUX.1-schnell); commercial use allowed"
UNET = "flux1-schnell-Q4_K_S.gguf"
T5 = "t5-v1_1-xxl-encoder-Q5_K_M.gguf"
CLIP_L = "clip_l.safetensors"
VAE = "ae.safetensors"
SIZES = {"square": (1024, 1024), "landscape": (1344, 768), "portrait": (768, 1344), "wide": (1536, 640),
         "thumbnail": (1280, 720), "story": (768, 1344), "banner": (1536, 512)}
GENERATE_TIMEOUT = 600.0
# Starting ComfyUI and its first answer; it loads the model on the first image, not at start.
WAKE_SECONDS = 180.0
IDLE_STOP_MINUTES = 10
LAST_USED_KEY = "comfyui:last_used"
BUSY_KEY = "comfyui:busy"
# The natural voice on the same graphics card, switched off while an image is made.
GPU_VOICE = "chatterbox"
# When the voice was last switched back on after an image (voiceover.speak waits for it to finish starting).
VOICE_BACK_KEY = "comfyui:voice_back"


def comfyui_url() -> str:
    from app.core.config import settings

    return str(getattr(settings, "COMFYUI_URL", "") or "").rstrip("/")


def size_of(shape: Optional[str], width: Optional[int] = None, height: Optional[int] = None) -> tuple:
    """Width and height in multiples of 16 (FLUX's step), from a named shape or given sizes, at most 1536."""
    w, h = SIZES.get((shape or "").lower(), (width or 1024, height or 1024))
    clamp = lambda v: max(256, min(1536, int(v) // 16 * 16))  # noqa: E731
    return clamp(w), clamp(h)


def workflow(prompt: str, width: int, height: int, seed: int, prefix: str = "jai") -> Dict[str, Any]:
    """The ComfyUI graph (API format) for one FLUX.1-schnell image: 4 steps, guidance 1, as schnell is made for."""
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET}},
        "2": {"class_type": "DualCLIPLoaderGGUF", "inputs": {"clip_name1": CLIP_L, "clip_name2": T5, "type": "flux"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["3", 0]}},
        "5": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "seed": seed, "steps": 4, "cfg": 1.0,
                                                    "sampler_name": "euler", "scheduler": "simple",
                                                    "positive": ["3", 0], "negative": ["4", 0],
                                                    "latent_image": ["5", 0], "denoise": 1.0}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["7", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }


class ImageUnavailable(RuntimeError):
    """JAI's image generator is not running or cannot make this image."""


async def _mark(busy: Optional[bool]) -> None:
    """Record that an image is being made (busy) or was just made; a Redis failure never stops the image."""
    try:
        from app.core.redis import get_redis

        redis = await get_redis()
        await redis.set(LAST_USED_KEY, str(time.time()))
        if busy:
            await redis.set(BUSY_KEY, "1", ex=int(GENERATE_TIMEOUT + WAKE_SECONDS + 60))
        elif busy is False:
            await redis.delete(BUSY_KEY)
    except Exception as exc:  # noqa: BLE001 - the record is a convenience, the image is the job
        logger.info(f"image generator use not recorded: {exc}")


async def _answers(client: httpx.AsyncClient, base: str) -> bool:
    try:
        return (await client.get(f"{base}/system_stats", timeout=5.0)).status_code == 200
    except httpx.HTTPError:
        return False


async def wake(client: httpx.AsyncClient, base: str, wait_seconds: float = WAKE_SECONDS) -> bool:
    """Start ComfyUI if it is stopped and wait until it answers; False when it cannot be started from here."""
    if await _answers(client, base):
        return True
    from app.core.ops import docker_ops

    ops = docker_ops.get_docker_ops()
    if not ops.available:
        return False
    try:
        await ops.switch("comfyui", True)
    except (docker_ops.OpsRefused, docker_ops.OpsUnavailable) as exc:
        logger.warning(f"image generator could not be started: {exc}")
        return False
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if await _answers(client, base):
            return True
        await asyncio.sleep(3.0)
    return False


async def pause_voice() -> bool:
    """Switch the natural voice off for an image; True when it was running (so it is switched back on after)."""
    from app.core.ops import docker_ops

    ops = docker_ops.get_docker_ops()
    if not ops.available:
        return False
    try:
        if not any(c.service == GPU_VOICE and c.state == "running" for c in await ops.containers()):
            return False
        await ops.switch(GPU_VOICE, False)
    except (docker_ops.OpsRefused, docker_ops.OpsUnavailable) as exc:
        logger.warning(f"the natural voice could not be switched off for an image: {exc}")
        return False
    return True


async def resume_voice() -> None:
    """Switch the natural voice back on after an image; a failure is logged, never raised."""
    from app.core.ops import docker_ops

    try:
        await docker_ops.get_docker_ops().switch(GPU_VOICE, True)
    except (docker_ops.OpsRefused, docker_ops.OpsUnavailable) as exc:
        logger.warning(f"the natural voice could not be switched back on after an image: {exc}")
        return
    try:
        from app.core.redis import get_redis

        await (await get_redis()).set(VOICE_BACK_KEY, str(time.time()), ex=600)
    except Exception as exc:  # noqa: BLE001 - only a hint for voiceovers
        logger.info(f"voice restart not recorded: {exc}")


async def voice_back_since() -> Optional[float]:
    """When the natural voice was last switched back on after an image (None: not recently)."""
    try:
        from app.core.redis import get_redis

        value = await (await get_redis()).get(VOICE_BACK_KEY)
        return float(value) if value is not None else None
    except Exception:  # noqa: BLE001
        return None


async def stop_if_idle(now: Optional[float] = None, idle_minutes: float = IDLE_STOP_MINUTES) -> Dict[str, Any]:
    """Stop ComfyUI when it is running and has made no image for idle_minutes (Celery beat). Seen running with no
    record of use, it gets idle_minutes from now."""
    from app.core.ops import docker_ops
    from app.core.redis import get_redis

    ops = docker_ops.get_docker_ops()
    if not ops.available:
        return {"stopped": False, "reason": "container operations are not configured"}
    now = time.time() if now is None else now
    try:
        running = any(c.service == "comfyui" and c.state == "running" for c in await ops.containers())
        if not running:
            return {"stopped": False, "reason": "not running"}
        redis = await get_redis()
        if await redis.get(BUSY_KEY):
            return {"stopped": False, "reason": "making an image"}
        last = await redis.get(LAST_USED_KEY)
        if last is None:
            await redis.set(LAST_USED_KEY, str(now))
            return {"stopped": False, "reason": "first seen running"}
        idle = (now - float(last)) / 60
        if idle < idle_minutes:
            return {"stopped": False, "reason": f"used {idle:.0f} minutes ago"}
        await ops.switch("comfyui", False)
    except (docker_ops.OpsRefused, docker_ops.OpsUnavailable) as exc:
        return {"stopped": False, "reason": str(exc)}
    logger.warning(f"Stopped the image generator: no image for {idle:.0f} minutes")
    return {"stopped": True, "reason": f"no image for {idle:.0f} minutes"}


async def generate(prompt: str, width: int = 1024, height: int = 1024, seed: Optional[int] = None,
                   client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """Make one image on the GPU; returns the PNG bytes, seed and seconds taken."""
    base = comfyui_url()
    if not base:
        raise ImageUnavailable("JAI's image generator (ComfyUI) is turned off on this computer.")
    prompt = " ".join((prompt or "").split())
    if len(prompt) < 3:
        raise ImageUnavailable("Say what the image should show.")
    seed = int(seed if seed is not None else random.randint(1, 2**31 - 1))
    started = time.monotonic()
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    await _mark(busy=True)
    paused = False
    try:
        paused = await pause_voice()
        await wake(client, base)
        try:
            queued = await client.post(f"{base}/prompt", json={"prompt": workflow(prompt, width, height, seed)})
        except httpx.HTTPError as exc:
            raise ImageUnavailable(f"JAI's image generator could not be reached ({type(exc).__name__}): it did not "
                                   f"start within {int(WAKE_SECONDS)} seconds. Switch it on in the Command Center "
                                   "(JAI's services panel); it needs the NVIDIA GPU and about 7 GB of memory.") from exc
        if queued.status_code >= 400:
            raise ImageUnavailable(f"The image generator refused the image: {queued.text[:300]}")
        prompt_id = queued.json().get("prompt_id")
        image = None
        while time.monotonic() - started < GENERATE_TIMEOUT:
            history = (await client.get(f"{base}/history/{prompt_id}")).json().get(prompt_id) or {}
            status = history.get("status") or {}
            if status.get("status_str") == "error":
                messages = [m for m in status.get("messages") or [] if m and m[0] == "execution_error"]
                detail = (messages[0][1].get("exception_message") if messages else None) or "the image failed"
                raise ImageUnavailable(f"The image generator failed: {str(detail)[:300]}")
            for output in (history.get("outputs") or {}).values():
                for found in output.get("images") or []:
                    image = found
            if image:
                break
            await asyncio.sleep(1.0)
        if not image:
            raise ImageUnavailable(f"The image took longer than {int(GENERATE_TIMEOUT)} seconds.")
        png = await client.get(f"{base}/view", params={"filename": image["filename"],
                                                       "subfolder": image.get("subfolder", ""),
                                                       "type": image.get("type", "output")})
        if png.status_code >= 400 or not png.content.startswith(b"\x89PNG"):
            raise ImageUnavailable("The image could not be collected from the generator.")
        try:  # release the model's memory so the rest of JAI keeps its share
            await client.post(f"{base}/free", json={"unload_models": True, "free_memory": True})
        except httpx.HTTPError:
            pass
        return {"png": png.content, "seed": seed, "seconds": round(time.monotonic() - started, 1),
                "width": width, "height": height}
    finally:
        await _mark(busy=False)
        if paused:
            await resume_voice()
        if own:
            await client.aclose()


def slug(text: str, limit: int = 48) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", (text or "image").lower()).strip("-")[:limit].strip("-")) or "image"


def default_path(prompt: str) -> str:
    return f"assets/images/{slug(prompt)}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.png"


def licence_entry(path: str, prompt: str, seed: int, width: int, height: int) -> str:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (f"\n## {path}\n- Made by JAI on {when} with {MODEL} in ComfyUI, {width}x{height}, seed {seed}\n"
            f"- Licence: {LICENCE}; no third-party image was used\n- Prompt: {prompt}\n")
