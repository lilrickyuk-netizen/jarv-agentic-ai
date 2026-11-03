"""
Download the image model files JAI uses into ComfyUI's model folders, once, each checked against the SHA-256 that
Hugging Face publishes for it (a file that does not match is deleted, never used). All are licensed for commercial
use: FLUX.1-schnell (Apache-2.0), the T5 text encoder (Apache-2.0), CLIP-L (MIT) and the FLUX autoencoder
(Apache-2.0, from FLUX.1-schnell). Run with internet access; ComfyUI itself runs without it.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

MODELS = Path("/opt/comfyui/models")
# (folder, file name kept, [(repository, path in repository), ...] in the order tried)
FILES = [
    ("unet", "flux1-schnell-Q4_K_S.gguf", [("city96/FLUX.1-schnell-gguf", "flux1-schnell-Q4_K_S.gguf")]),
    ("text_encoders", "t5-v1_1-xxl-encoder-Q5_K_M.gguf",
     [("city96/t5-v1_1-xxl-encoder-gguf", "t5-v1_1-xxl-encoder-Q5_K_M.gguf")]),
    ("text_encoders", "clip_l.safetensors", [("comfyanonymous/flux_text_encoders", "clip_l.safetensors")]),
    ("vae", "ae.safetensors", [("black-forest-labs/FLUX.1-schnell", "ae.safetensors"),
                               ("Comfy-Org/Lumina_Image_2.0_Repackaged", "split_files/vae/ae.safetensors")]),
]
HEADERS = {"User-Agent": "JAI-model-fetch/1.0"}


def published_sha256(repo: str, path: str) -> str:
    """The SHA-256 Hugging Face records for a stored (LFS) file."""
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    url = f"https://huggingface.co/api/models/{repo}/tree/main" + (f"/{folder}" if folder else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
        for entry in json.load(r):
            if entry.get("path") == path and entry.get("lfs", {}).get("oid"):
                return entry["lfs"]["oid"]
    raise RuntimeError(f"no published checksum for {repo}/{path}")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(folder: str, name: str, sources) -> str:
    target = MODELS / folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for repo, path in sources:
        try:
            expected = published_sha256(repo, path)
        except Exception as exc:  # noqa: BLE001 - try the next source
            errors.append(f"{repo}: {exc}")
            continue
        if target.exists() and sha256_of(target) == expected:
            return f"kept {folder}/{name} (checksum matches)"
        partial = target.with_suffix(target.suffix + ".part")
        url = f"https://huggingface.co/{repo}/resolve/main/{path}"
        print(f"downloading {folder}/{name} from {repo} ...", flush=True)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as r, \
                    partial.open("wb") as out:
                while True:
                    block = r.read(8 * 1024 * 1024)
                    if not block:
                        break
                    out.write(block)
        except Exception as exc:  # noqa: BLE001
            partial.unlink(missing_ok=True)
            errors.append(f"{repo}: {exc}")
            continue
        actual = sha256_of(partial)
        if actual != expected:
            partial.unlink(missing_ok=True)
            errors.append(f"{repo}: checksum {actual} does not match the published {expected}; deleted")
            continue
        partial.replace(target)
        return f"downloaded {folder}/{name} ({target.stat().st_size // (1024 * 1024)} MB, sha256 {expected})"
    raise RuntimeError(f"{folder}/{name} could not be downloaded: " + " | ".join(errors))


def main() -> int:
    failed = False
    for folder, name, sources in FILES:
        try:
            print(fetch(folder, name, sources), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED {exc}", flush=True)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
