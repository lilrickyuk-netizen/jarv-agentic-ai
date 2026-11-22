"""
22 November: narration in real human voices. Chatterbox Turbo clones the voice of the reference clip it is given, and
JAI's only clip (George) was made with Kokoro, so every voiceover sounded synthetic. The voice library is clean read
speech from LibriTTS-R (CC BY 4.0), chosen by scripts/voice_library_pick.py; a content mission picks the voice that
fits each piece and make_voiceover speaks in it. Pure: synthetic WAVs, Chatterbox answered by a stand-in, no GPU.
"""
from __future__ import annotations

import array
import asyncio
import importlib.util
import json
import math
import wave
from pathlib import Path

from app.core.config import settings
from app.core.creative import voice_library, voiceover
from app.core.knowledge import content_rules
from tests.repo_paths import repo_path
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12c_agent_tools import _agent, _ctx, _seed, project  # noqa: F401 - project is a fixture


def _wav(path: Path, seconds: float, amplitude: int = 6000) -> None:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(array.array("h", (int(amplitude * math.sin(i / 7)) for i in range(int(seconds * 24000))))
                      .tobytes())


def _picker():
    spec = importlib.util.spec_from_file_location("voice_library_pick", repo_path("scripts", "voice_library_pick.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _library(root: Path) -> Path:
    voices = [{"id": "woman-calm-1089", "speaker": "1089", "gender": "woman", "pace": "calm", "words_per_second": 2.2,
               "seconds": 11.2}, {"id": "man-lively-237", "speaker": "237", "gender": "man", "pace": "lively",
                                  "words_per_second": 3.1, "seconds": 10.4},
              {"id": "man-steady-999", "speaker": "999", "gender": "man", "pace": "steady"}]
    (root / "library.json").write_text(json.dumps({"voices": voices}))
    for v in voices[:2]:  # the third voice's clip is missing, so it is never offered
        _wav(root / f"{v['id']}.wav", 1)
    return root


def test_the_picker_keeps_clean_clips_of_the_right_length_across_paces(tmp_path):
    picker = _picker()
    root = tmp_path / "LibriTTS_R"
    (root / "test-clean").mkdir(parents=True)
    readers = "".join(f"{s}\t{'F' if s % 2 else 'M'}\ttest-clean\tR\n" for s in range(100, 124))
    (root / "speakers.tsv").write_text("READER\tGENDER\tSUBSET\tNAME\n" + readers)
    for s in range(100, 124):
        chapter = root / "test-clean" / str(s) / "1"
        chapter.mkdir(parents=True)
        for k, seconds in enumerate((5, 11, 20)):
            utterance = f"{s}_1_000{k}_000000"
            _wav(chapter / f"{utterance}.wav", seconds, amplitude=32767 if s == 102 else 6000)
            words = int(seconds * (2.0 + (s - 100) * 0.06))
            (chapter / f"{utterance}.normalized.txt").write_text(" ".join(["word"] * words) + ".")
    failed = tmp_path / "failed"
    failed.mkdir()
    (failed / "failed.txt").write_text("101_1_0001_000000\n")
    out = tmp_path / "out"
    assert picker.main(["pick", str(tmp_path), str(failed), str(out)]) == 0
    library = json.loads((out / "library.json").read_text())
    voices = library["voices"]
    assert library["licence"] == "CC-BY-4.0" and "LibriTTS-R" in library["attribution"]
    assert len([v for v in voices if v["gender"] == "woman"]) == 8 and len(voices) == 16
    assert all(9 <= v["seconds"] <= 15 and (out / f"{v['id']}.wav").is_file() for v in voices)
    assert {"calm", "lively"} <= {v["pace"] for v in voices}
    assert not {v["speaker"] for v in voices} & {"101", "102"}  # a failed restoration and a clipped clip


def test_the_library_lists_only_voices_whose_clip_is_there(tmp_path):
    root = _library(tmp_path)
    assert [v["id"] for v in voice_library.voices(root)] == ["woman-calm-1089", "man-lively-237"]
    assert "woman-calm-1089 (woman, calm pace" in voice_library.describe(root)
    assert "LibriTTS-R" in voice_library.licence_line("man-lively-237", root)
    assert "Kokoro" in voice_library.licence_line("george", root)
    assert voice_library.voices(tmp_path / "nothing") == [] and voice_library.describe(tmp_path / "nothing") == ""


def test_a_content_brief_offers_the_voices_and_rules_out_robotic_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_LIBRARY_DIR", str(_library(tmp_path)))
    rule = content_rules.voice_rule()
    assert "make_voiceover" in rule and "woman-calm-1089" in rule and "man-lively-237" in rule
    assert "Never Kokoro, Piper, `npx hyperframes tts`" in rule and "assets/narration/" not in rule
    studio = content_rules.voice_rule(studio=True)
    assert "assets/narration/" in studio and "instead of its tts_selector" in studio
    assert "ASSET_LICENCES.md names the voice" in content_rules.content_check("Make a reel")
    monkeypatch.setattr(settings, "VOICE_LIBRARY_DIR", str(tmp_path / "missing"))
    assert "this piece has no voice" in content_rules.voice_rule()


def test_make_voiceover_speaks_in_the_chosen_voice_and_refuses_one_not_in_the_library(project, tmp_path, monkeypatch):
    from app.core.agents.base import AuthorityLevel
    from app.core.agents.specialists.content import ContentAgent
    from app.core.agents.toolbox import AgentToolbox

    root_host, root, _ = project
    monkeypatch.setattr(settings, "VOICE_LIBRARY_DIR", str(_library(tmp_path)))
    used = []

    async def speak(text, voice=None, client=None):
        used.append(voice)
        return {"wav": b"RIFF" + b"\x00" * 100, "seconds": 3.0, "sentences": 1, "voice": voice or "george"}

    monkeypatch.setattr(voiceover, "speak", speak)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, root_host)
            box = await AgentToolbox(_agent(ContentAgent, ws_id, user_id, AuthorityLevel.LEVEL_3_CODE_EXECUTION),
                                     _ctx(db, ws_id, user_id)).prepare()
            chosen = await box.call("make_voiceover", {"text": "Day three.", "voice": "man-lively-237"})
            unknown = await box.call("make_voiceover", {"text": "Day three.", "voice": "someone-else"})
            await db.commit()
            return chosen, unknown

    chosen, unknown = asyncio.run(run())
    assert chosen["success"] is True and chosen["voice"] == "man-lively-237" and used == ["man-lively-237"]
    assert unknown["success"] is False and "not in JAI's voice library" in unknown["error"]
    licences = (root / "ASSET_LICENCES.md").read_text()
    assert "voice man-lively-237 (reference clip: speaker 237 of LibriTTS-R" in licences


def test_the_backend_and_worker_read_the_library_and_the_builder_checks_the_download():
    compose = repo_path("docker-compose.yml").read_text()
    assert compose.count("voice_refs:/srv/voices:ro") == 3  # Chatterbox, the backend and the worker
    script = repo_path("scripts", "voice-library.sh").read_text()
    assert "openslr" in script and "md5sum.txt" in script and "test_clean.tar.gz" in script
    assert "voice_library_pick.py" in script and "jai_voice_refs" in script
