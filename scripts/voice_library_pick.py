"""
Chooses JAI's narration voices from LibriTTS-R (CC BY 4.0, openslr.org/141): for each speaker, one clean clip of
real read speech, 9 to 15 seconds, the length Chatterbox clones a voice from. Run by scripts/voice-library.sh; Python's
standard library only, so it runs on the host with nothing installed.

    python3 scripts/voice_library_pick.py <extracted LibriTTS_R folder> <failed-restoration lists folder> <out folder>

Writes <out>/<id>.wav (copied unchanged) and <out>/library.json (each voice's id, speaker, gender, pace, words a
second, seconds, the clip's utterance and transcript, and the dataset's attribution).
"""
from __future__ import annotations

import array
import json
import math
import re
import shutil
import sys
import wave
from pathlib import Path
from typing import Dict, List, Optional, Set

MIN_SECONDS, MAX_SECONDS, BEST_SECONDS = 9.0, 15.0, 11.0
PER_GENDER = 8
UTTERANCE = re.compile(r"\d+_\d+_\d+_\d+")
SOURCE = "https://www.openslr.org/141/"
ATTRIBUTION = ("LibriTTS-R: Koizumi, Zen, Karita, Ding, Yatabe, Morioka, Bacchiani, Zhang, Han and Bapna, "
               "\"LibriTTS-R: A Restored Multi-Speaker Text-to-Speech Corpus\", 2023. CC BY 4.0. Restored from "
               "LibriTTS (openslr.org/60), read from LibriVox public-domain audiobooks.")


def genders(root: Path) -> Dict[str, str]:
    """Speaker id -> "F" or "M", from speakers.tsv (LibriTTS) or SPEAKERS.txt (LibriSpeech's format)."""
    out: Dict[str, str] = {}
    for path in list(root.rglob("speakers.tsv")) + list(root.rglob("SPEAKERS.txt")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip() or line.startswith(";"):
                continue
            parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split("|"))]
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].upper() in ("F", "M"):
                out.setdefault(parts[0], parts[1].upper())
    return out


def failed(folder: Optional[Path]) -> Set[str]:
    """Utterances whose speech restoration failed (the dataset's own lists): never chosen."""
    if folder is None or not folder.exists():
        return set()
    found: Set[str] = set()
    for path in folder.rglob("*"):
        if path.is_file():
            found |= set(UTTERANCE.findall(path.read_text(encoding="utf-8", errors="replace")))
    return found


def _samples(path: Path):
    """(rate, samples scaled to 16-bit) of a mono WAV in 16-bit PCM or 32-bit float, read chunk by chunk so a float
    file (which Python's wave module refuses) is read too; None for anything else."""
    import struct

    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos, fmt, body = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        chunk = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", chunk[:16])
            if fmt[0] == 0xFFFE and len(chunk) >= 26:  # WAVE_FORMAT_EXTENSIBLE: the real format is in the subformat
                fmt = (struct.unpack("<H", chunk[24:26])[0],) + fmt[1:]
        elif cid == b"data":
            body = chunk
        pos += 8 + size + (size & 1)
    if fmt is None or body is None or fmt[1] != 1:
        return None
    tag, rate, bits = fmt[0], fmt[2], fmt[5]
    if tag == 1 and bits == 16:
        samples = array.array("h")
        samples.frombytes(body[:len(body) // 2 * 2])
        if sys.byteorder == "big":
            samples.byteswap()
        return rate, samples
    if tag == 3 and bits == 32:
        floats = array.array("f")
        floats.frombytes(body[:len(body) // 4 * 4])
        if sys.byteorder == "big":
            floats.byteswap()
        return rate, array.array("h", (max(-32768, min(32767, int(x * 32767))) for x in floats))
    return None


def measure(path: Path) -> Optional[Dict[str, float]]:
    """Seconds, peak and loudness (dBFS) of a mono WAV, or None for a format it cannot read."""
    read = _samples(path)
    if read is None or not read[1]:
        return None
    rate, samples = read
    peak = max(abs(s) for s in samples)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) or 1.0
    return {"seconds": len(samples) / rate, "peak": peak, "dbfs": 20 * math.log10(rms / 32768)}


def pace(words_per_second: float) -> str:
    return "calm" if words_per_second < 2.4 else "steady" if words_per_second < 2.9 else "lively"


COUNTS: Dict[str, int] = {}


def _count(reason: str) -> None:
    COUNTS[reason] = COUNTS.get(reason, 0) + 1


def candidates(root: Path, refused: Set[str]) -> Dict[str, List[Dict]]:
    by_speaker: Dict[str, List[Dict]] = {}
    for wav in sorted(root.rglob("*.wav")):
        utterance = wav.stem
        _count("clips")
        if not UTTERANCE.fullmatch(utterance):
            _count("name not an utterance id")
            continue
        if utterance in refused:
            _count("restoration failed")
            continue
        text_file = wav.with_suffix(".normalized.txt")
        if not text_file.is_file():
            _count("no transcript")
            continue
        text = " ".join(text_file.read_text(encoding="utf-8", errors="replace").split())
        words = len(text.split())
        if words < 18 or not text.endswith((".", "!", "?")):
            _count("short or unfinished sentence")
            continue
        m = measure(wav)
        if m is None:
            _count("audio format not readable")
            continue
        if not (MIN_SECONDS <= m["seconds"] <= MAX_SECONDS):
            _count("not 9 to 15 seconds")
            continue
        if m["peak"] >= 32000 or not (-30.0 <= m["dbfs"] <= -14.0):  # clipped, too quiet or too loud
            _count("clipped, too quiet or too loud")
            continue
        _count("passed")
        by_speaker.setdefault(utterance.split("_")[0], []).append(
            {"path": wav, "utterance": utterance, "text": text, "seconds": round(m["seconds"], 1),
             "words_per_second": round(words / m["seconds"], 2), "dbfs": round(m["dbfs"], 1)})
    return by_speaker


def spread(items: List[Dict], count: int) -> List[Dict]:
    """count items evenly across the range of speaking pace, so the library has calm and lively voices."""
    items = sorted(items, key=lambda v: v["words_per_second"])
    if len(items) <= count:
        return items
    step = (len(items) - 1) / (count - 1)
    return [items[round(i * step)] for i in range(count)]


def choose(root: Path, refused: Set[str]) -> List[Dict]:
    gender = genders(root)
    COUNTS["speakers with a gender"] = len(gender)
    best = []
    for speaker, clips in candidates(root, refused).items():
        if speaker not in gender:
            continue
        clip = min(clips, key=lambda c: (abs(c["seconds"] - BEST_SECONDS), -c["dbfs"]))
        best.append({**clip, "speaker": speaker, "gender": gender[speaker]})
    chosen = []
    for g, word in (("F", "woman"), ("M", "man")):
        for clip in spread([c for c in best if c["gender"] == g], PER_GENDER):
            p = pace(clip["words_per_second"])
            chosen.append({**clip, "id": f"{word}-{p}-{clip['speaker']}", "gender": word, "pace": p})
    return chosen


def main(argv: List[str]) -> int:
    root, failed_dir, out = Path(argv[1]), Path(argv[2]) if argv[2] != "-" else None, Path(argv[3])
    chosen = choose(root, failed(failed_dir))
    print("   " + ", ".join(f"{k}: {v}" for k, v in COUNTS.items()))
    if len(chosen) < 4:
        print(f"Only {len(chosen)} voices passed the checks; the library was not written.")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    voices = []
    for c in chosen:
        shutil.copyfile(c["path"], out / f"{c['id']}.wav")
        voices.append({k: c[k] for k in ("id", "speaker", "gender", "pace", "words_per_second", "seconds",
                                         "utterance", "text")})
    (out / "library.json").write_text(json.dumps({"source": SOURCE, "licence": "CC-BY-4.0",
                                                  "attribution": ATTRIBUTION, "voices": voices}, indent=2),
                                      encoding="utf-8")
    for v in voices:
        print(f"   {v['id']}: {v['seconds']}s, {v['words_per_second']} words a second")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
