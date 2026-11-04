"""
JAI Backend - Images (Wave 4a)

Images are made on Richard's own graphics card by JAI's ComfyUI (open source) with FLUX.1-schnell (Apache-2.0,
commercial use allowed), compressed (GGUF) to fit a 6 GB card. ComfyUI runs on an internal network with no
internet; only JAI's backend and worker reach it. After each image ComfyUI is asked to release its memory, so the
rest of JAI keeps its share.

Every image is saved into the workspace (assets/images/ unless another path inside it is given) and recorded in the
workspace's ASSET_LICENCES.md with the model, its licence and the prompt, so where each asset came from is known.
"""
from __future__ import annotations

import asyncio
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

MODEL = "FLUX.1-schnell (GGUF Q4_K_S)"
LICENCE = "Apache-2.0 (FLUX.1-schnell); commercial use allowed"
UNET = "flux1-schnell-Q4_K_S.gguf"
T5 = "t5-v1_1-xxl-encoder-Q5_K_M.gguf"
CLIP_L = "clip_l.safetensors"
VAE = "ae.safetensors"
SIZES = {"square": (1024, 1024), "landscape": (1344, 768), "portrait": (768, 1344), "wide": (1536, 640),
         "thumbnail": (1280, 720), "story": (768, 1344), "banner": (1536, 512)}
GENERATE_TIMEOUT = 600.0


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
    try:
        try:
            queued = await client.post(f"{base}/prompt", json={"prompt": workflow(prompt, width, height, seed)})
        except httpx.HTTPError as exc:
            raise ImageUnavailable(f"JAI's image generator could not be reached ({type(exc).__name__}): it is switched "
                                   "off or still starting. Switch it on under \"JAI's services\" in the Command Center "
                                   "(it needs the NVIDIA GPU and about 7 GB of memory).") from exc
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
