"""
JAI Backend - Short videos (Wave 4b)

A short video for a topic, made the way MoneyPrinterTurbo makes them but driven by JAI: JAI's own model (metered,
within today's spend limit) writes the narration, the search terms and the image prompts; JAI's natural voice
narrates it on the GPU; the footage is JAI's own generated images (FLUX.1-schnell, Apache-2.0) or Pexels stock
footage when a Pexels key is set; MoneyPrinterTurbo adds subtitles and renders it. Nothing is published.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

ASPECT_SHAPES = {"portrait": "story", "landscape": "landscape", "square": "square"}


class VideoUnavailable(RuntimeError):
    """JAI's video maker is not running or could not make this video."""


def moneyprinter_url() -> str:
    from app.core.config import settings

    return str(getattr(settings, "MONEYPRINTER_URL", "") or "").rstrip("/")


async def stock_available() -> bool:
    """Whether the video maker has a Pexels key for stock footage."""
    base = moneyprinter_url()
    if not base:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            return bool((await client.get(f"{base}/health")).json().get("pexels"))
    except (httpx.HTTPError, ValueError):
        return False


def parse_plan(text: str, topic: str, images: int) -> Dict[str, Any]:
    """The model's plan (JSON: script, terms, image_prompts), tidied; the topic stands in for anything missing."""
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        plan = json.loads(match.group(0)) if match else {}
    except ValueError:
        plan = {}
    script = " ".join(str(plan.get("script") or "").split())
    terms = [str(t).strip() for t in plan.get("terms") or [] if str(t).strip()][:6] or [topic]
    prompts = [str(p).strip() for p in plan.get("image_prompts") or [] if str(p).strip()][:images]
    while len(prompts) < images:
        prompts.append(f"{topic}, cinematic, high quality, scene {len(prompts) + 1}")
    return {"script": script, "terms": terms, "image_prompts": prompts, "title": str(plan.get("title") or topic)[:120]}


async def plan_video(topic: str, seconds: int, audience: str, images: int) -> Dict[str, Any]:
    """JAI's model writes the narration (about 2.4 spoken words a second), search terms and image prompts."""
    from app.core.command import CommandService
    from app.core.providers import CompletionRequest, Message, get_router

    words = max(25, int(seconds * 2.4))
    response = await get_router().complete(CompletionRequest(
        model=CommandService().model, max_tokens=1200, temperature=0.6, reasoning_effort="low",
        system=("You write short-form video narration for JAI, Richard Curley's AI operating system. Spoken, "
                "British English, a strong hook in the first sentence, one idea, a clear call to action at the end. "
                "Only claims the brief supports; no made-up statistics. Return only JSON."),
        messages=[Message(role="user", content=(
            f"Topic and brief: {topic}\nAudience: {audience or 'general'}\nLength: about {seconds} seconds, "
            f"so about {words} words.\nReturn JSON with keys: title (short), script (the narration, plain "
            f"sentences), terms (4 to 6 short stock-footage search terms in English), image_prompts ({images} "
            f"detailed image descriptions, one per scene in order, vertical framing, no text unless essential)."))]))
    return parse_plan(response.content or "", topic, images)


async def render(spec: Dict[str, Any], narration_wav: bytes, images: List[bytes],
                 client: Optional[httpx.AsyncClient] = None) -> bytes:
    """MoneyPrinterTurbo renders the video (subtitles timed from the narration); returns MP4 bytes."""
    base = moneyprinter_url()
    if not base:
        raise VideoUnavailable("JAI's video maker (MoneyPrinterTurbo) is turned off on this computer.")
    files = [("narration", ("narration.wav", narration_wav, "audio/wav"))]
    files += [("images", (f"scene-{i:02d}.png", data, "image/png")) for i, data in enumerate(images)]
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(1800.0, connect=5.0))
    try:
        try:
            made = await client.post(f"{base}/render", data={"spec": json.dumps(spec)}, files=files)
        except httpx.HTTPError as exc:
            raise VideoUnavailable(f"JAI's video maker could not be reached ({type(exc).__name__}). Switch it on in the Command Center (JAI's services panel).") from exc
        if made.status_code != 200 or made.content[4:8] != b"ftyp":
            detail = made.text[:300] if made.status_code != 200 else "not an MP4"
            raise VideoUnavailable(f"The video could not be made: {detail}")
        return made.content
    finally:
        if own:
            await client.aclose()


def licence_entry(path: str, title: str, footage: str, seconds: float) -> str:
    from datetime import datetime, timezone

    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sources = {"generated": "JAI's own generated images (FLUX.1-schnell, Apache-2.0)",
               "pexels": "Pexels stock footage (Pexels Licence: free for commercial use, no attribution required)"}
    return (f"\n## {path}\n- Made by JAI on {when} with MoneyPrinterTurbo (MIT): \"{title}\", {seconds:.0f}s\n"
            f"- Narration: JAI's voice (Chatterbox Turbo, MIT; reference voice from Kokoro, Apache-2.0)\n"
            f"- Footage: {sources.get(footage, footage)}; subtitle font Be Vietnam Pro (SIL OFL); no music\n")
