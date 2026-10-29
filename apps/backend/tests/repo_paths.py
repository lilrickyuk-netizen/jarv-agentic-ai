"""
Locating repository-level files (compose files, scripts, CI, docs) from the backend tests.

The test image holds only apps/backend, so the owner's run mounts the repository read-only
and sets JARV_REPO_ROOT. From a checkout, the nearest parent holding docker-compose.yml is used.
"""
import os
from pathlib import Path
from typing import Optional

import pytest


def repo_root() -> Optional[Path]:
    if os.environ.get("JARV_REPO_ROOT"):
        return Path(os.environ["JARV_REPO_ROOT"])
    for parent in Path(__file__).resolve().parents:
        if (parent / "docker-compose.yml").is_file():
            return parent
    return None


def repo_path(*parts: str) -> Path:
    """Path of a repository-level file; the test is skipped when the repository is not available."""
    root = repo_root()
    if root is None:
        pytest.skip("repository files are outside the test image; mount the repository and set JARV_REPO_ROOT")
    return root.joinpath(*parts)
