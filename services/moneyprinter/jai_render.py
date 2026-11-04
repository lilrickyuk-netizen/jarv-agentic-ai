"""
JAI's video API over MoneyPrinterTurbo. POST /render (multipart): "spec" (JSON: subject, script, terms, aspect,
clip_seconds, subtitles), "narration" (a WAV JAI's voice spoke) and optional "images" (JAI's generated images, used
as footage with a slow zoom). The video is made with MoneyPrinterTurbo's own pipeline in a task folder it owns; the
response is the finished MP4. Footage comes from Pexels when PEXELS_API_KEY is set and no images are given.
MoneyPrinterTurbo is never asked to write a script or search terms, so it never calls an AI provider.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import task as tm
from app.utils import utils

# JAI's settings for MoneyPrinterTurbo: subtitles timed by whisper (from JAI's narration), on the processor (the GPU
# is JAI's voice's and image generator's), an open-licence subtitle font, and Pexels only when a key is given.
config.app["subtitle_provider"] = "whisper"
config.whisper.update({"model_size": "small", "device": "cpu", "compute_type": "int8"})
if os.environ.get("PEXELS_API_KEY"):
    config.app["pexels_api_keys"] = [os.environ["PEXELS_API_KEY"]]
FONT = "BeVietnamPro-Bold.ttf"  # SIL Open Font Licence
ASPECTS = {"portrait": VideoAspect.portrait, "landscape": VideoAspect.landscape, "square": VideoAspect.square}
_one_at_a_time = threading.Lock()

app = FastAPI(title="JAI videos", docs_url=None, redoc_url=None)


@app.get("/health")
async def health():
    return {"status": "ok", "pexels": bool(os.environ.get("PEXELS_API_KEY")), "subtitles": "whisper-small"}


def render(task_id: str, spec: dict, narration: Path, images: List[Path]) -> Path:
    """Make one video with MoneyPrinterTurbo's pipeline; returns the MP4's path."""
    params = VideoParams(
        video_subject=str(spec.get("subject") or "video")[:200],
        video_script=str(spec.get("script") or ""),
        video_terms=[str(t) for t in (spec.get("terms") or [])][:10] or [str(spec.get("subject") or "abstract")],
        video_aspect=ASPECTS.get(str(spec.get("aspect") or "portrait"), VideoAspect.portrait),
        video_clip_duration=int(spec.get("clip_seconds") or 5),
        video_count=1,
        video_source="local" if images else "pexels",
        video_materials=[MaterialInfo(provider="local", url=str(p.resolve()), duration=0) for p in images] or None,
        custom_audio_file=str(narration),
        voice_name="",
        bgm_type="",          # no background music: its licence could not be confirmed for commercial use
        subtitle_enabled=bool(spec.get("subtitles", True)),
        font_name=FONT, font_size=int(spec.get("font_size") or 60), text_color="#FFFFFF",
        stroke_color="#000000", stroke_width=1.5,
    )
    with _one_at_a_time:  # FFmpeg and whisper are heavy: one video at a time
        result = tm.start(task_id, params, stop_at="video", allow_server_file_input=True)
    if not result or result.get("state") == tm.const.TASK_STATE_FAILED or not result.get("videos"):
        error = (result or {}).get("error") or "the video could not be made"
        raise RuntimeError(f"{(result or {}).get('failed_stage', 'render')}: {error}")
    return Path(result["videos"][0])


@app.post("/render")
async def render_route(spec: str = Form(...), narration: UploadFile = File(...),
                       images: Optional[List[UploadFile]] = File(None)):
    try:
        details = json.loads(spec)
    except ValueError:
        raise HTTPException(status_code=400, detail="spec must be JSON")
    if not str(details.get("script") or "").strip():
        raise HTTPException(status_code=400, detail="the script is empty")
    task_id = str(uuid.uuid4())
    folder = Path(utils.task_dir(task_id))
    audio = folder / "jai-narration.wav"
    audio.write_bytes(await narration.read())
    stills: List[Path] = []
    # MoneyPrinterTurbo only uses local footage from inside its local_videos folder (anything else is refused as
    # unsafe), so JAI's images go in a folder of their own there for this video.
    footage = Path(utils.storage_dir("local_videos", create=True)) / task_id
    footage.mkdir(parents=True, exist_ok=True)
    for index, image in enumerate(images or []):
        suffix = Path(image.filename or "image.png").suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
            raise HTTPException(status_code=400, detail=f"{image.filename} is not an image")
        path = footage / f"jai-image-{index:02d}{suffix}"
        path.write_bytes(await image.read())
        stills.append(path)
    if not stills and not os.environ.get("PEXELS_API_KEY"):
        raise HTTPException(status_code=400, detail="no footage: give images or set PEXELS_API_KEY")
    try:
        video = await asyncio.to_thread(render, task_id, details, audio, stills)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"the video could not be made: {exc}"[:500])
    finally:
        shutil.rmtree(footage, ignore_errors=True)  # the images are in the video now
    return FileResponse(video, media_type="video/mp4", filename=f"{task_id}.mp4",
                        headers={"X-Task-Id": task_id})
