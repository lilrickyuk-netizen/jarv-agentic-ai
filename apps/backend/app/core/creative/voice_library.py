"""
JAI Backend - The voice library for narration

22 November. Richard: "every voiceover I've heard sounds unnatural and robotic". Chatterbox Turbo (MIT) speaks in the
voice of whatever reference clip it is given (zero-shot cloning from about ten seconds of speech, its documented use),
and the only clip JAI had was George, made with Kokoro, so every narration inherited a synthetic voice. The library
gives it real human speakers instead: clean read-speech clips from LibriTTS-R (Google's restored LibriTTS, CC BY 4.0,
openslr.org/141), the corpus speech models are routinely prompted from for zero-shot voices. They are chosen by
scripts/voice-library.sh into Chatterbox's voice folder (the jai_voice_refs volume) with library.json beside them:
each voice's id, gender, pace and source. A content mission chooses the voice that fits each piece.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

LIBRARY_FILE = "library.json"
ATTRIBUTION = ("LibriTTS-R (Koizumi et al., 2023, CC BY 4.0, https://www.openslr.org/141/), restored from LibriTTS "
               "and the LibriVox public-domain audiobooks")


def library_dir() -> Path:
    from app.core.config import settings

    return Path(str(getattr(settings, "VOICE_LIBRARY_DIR", "") or "/srv/voices"))


def voices(root: Optional[Path] = None) -> List[Dict]:
    """The library's voices whose clip is present, in the order library.json lists them; [] when it is not built."""
    base = root or library_dir()
    try:
        data = json.loads((base / LIBRARY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [v for v in data.get("voices", []) if isinstance(v, dict) and v.get("id")
            and (base / f"{v['id']}.wav").is_file()]


def find(voice: str, root: Optional[Path] = None) -> Optional[Dict]:
    return next((v for v in voices(root) if v["id"] == (voice or "").strip().lower()), None)


def licence_line(voice: str, root: Optional[Path] = None) -> str:
    """What the licence file says about the voice a narration used."""
    entry = find(voice, root)
    if entry is None:
        return "(reference made with Kokoro, Apache-2.0)"
    return f"(reference clip: speaker {entry.get('speaker')} of {ATTRIBUTION})"


def describe(root: Optional[Path] = None) -> str:
    """The voices as one line each, for a brief; "" when the library is not built."""
    lines = [f"{v['id']} ({v.get('gender', '?')}, {v.get('pace', '?')} pace, {v.get('words_per_second', '?')} words "
             "a second)" for v in voices(root)]
    return "; ".join(lines)
