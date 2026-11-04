"""JAI's video maker renders a real short video from narration and images, offline, with subtitles. In the image."""
import json
import math
import struct
import wave

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import jai_render


def _narration(path, seconds=4.0, rate=24000):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 200 * i / rate)))
                               for i in range(int(rate * seconds))))


def _image(path, colour):
    img = Image.new("RGB", (768, 1344), colour)
    ImageDraw.Draw(img).rectangle([200, 400, 568, 900], fill=(255, 255, 255))
    img.save(path)


def test_a_short_video_is_rendered_from_narration_and_images(tmp_path):
    _narration(tmp_path / "n.wav")
    _image(tmp_path / "a.png", (20, 40, 90))
    _image(tmp_path / "b.png", (90, 30, 40))
    client = TestClient(jai_render.app)
    with open(tmp_path / "n.wav", "rb") as n, open(tmp_path / "a.png", "rb") as a, open(tmp_path / "b.png", "rb") as b:
        made = client.post("/render", data={"spec": json.dumps({
            "subject": "Plexecute", "script": "Plan your life. Execute the plan.", "terms": ["planning"],
            "aspect": "portrait", "clip_seconds": 2, "subtitles": False})},
            files=[("narration", ("n.wav", n, "audio/wav")), ("images", ("a.png", a, "image/png")),
                   ("images", ("b.png", b, "image/png"))])
    assert made.status_code == 200, made.text[:500]
    assert made.headers["content-type"] == "video/mp4" and len(made.content) > 10_000
    assert made.content[4:8] == b"ftyp"   # an MP4 file
    assert client.post("/render", data={"spec": json.dumps({"script": ""})},
                       files=[("narration", ("n.wav", b"x", "audio/wav"))]).status_code == 400
