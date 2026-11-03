"""JAI's natural voice speaks offline, in a voice prepared from a clip, and reports its device. Runs in the image."""
import wave
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

import server


def _clip(path: Path, seconds: float = 6.0) -> None:
    t = np.arange(int(server.SAMPLE_RATE * seconds)) / server.SAMPLE_RATE
    tone = (0.2 * np.sin(2 * np.pi * 180 * t) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(server.SAMPLE_RATE)
        f.writeframes((tone * 32767).astype(np.int16).tobytes())


def test_it_speaks_a_sentence_offline_in_the_given_voice_and_the_built_in_one(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "VOICES", tmp_path)
    _clip(tmp_path / "george.wav")
    client = TestClient(server.app)
    spoken = client.post("/speak", json={"text": "Good evening, Richard. Phase zero is verified.", "voice": "george"})
    assert spoken.status_code == 200 and spoken.headers["x-sample-rate"] == "24000"
    assert len(spoken.content) > server.SAMPLE_RATE * 2  # over a second of 16-bit speech
    builtin = client.post("/speak", json={"text": "Hello.", "voice": "nobody"})
    assert builtin.status_code == 200 and len(builtin.content) > 1000
    health = client.get("/health").json()
    assert health["device"] in ("gpu", "cpu") and "george" in health["voices"]
    assert client.post("/speak", json={"text": ""}).status_code == 422
