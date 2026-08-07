"""
conftest.py - Shared pytest fixtures for the ClipIt QA suite (Agent 06).

Provides:
  - Project root on sys.path so `core` / `modules` are importable.
  - A temp SQLite `Database` per test (isolated, in tmp_path, WAL + atomic tx).
  - Ready-made enabled accounts.
  - FFmpeg / FFprobe availability fixture + `ffmpeg_available` flag for skips.
  - A canned Whisper (verbose_json) transcript payload.
  - A small helper to synth a real MP4 + WAV with FFmpeg for integration tests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Make the project importable regardless of where pytest is launched from
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CORE_DIR = PROJECT_ROOT / "core"

from core.config import Config  # noqa: E402
from core.db import Database  # noqa: E402


def _binary(name: str) -> str | None:
    """Return the absolute path of an executable or None."""
    found = shutil.which(name)
    return os.path.abspath(found) if found else None


@pytest.fixture(scope="session")
def ffmpeg_path() -> str | None:
    return _binary("ffmpeg")


@pytest.fixture(scope="session")
def ffprobe_path() -> str | None:
    return _binary("ffprobe")


@pytest.fixture(scope="session")
def ffmpeg_available(ffmpeg_path: str | None, ffprobe_path: str | None) -> bool:
    return bool(ffmpeg_path and ffprobe_path)


@pytest.fixture(autouse=True)
def _run_in_project(tmp_path: Path) -> Path:
    """Force CWD to a temp dir so no test writes to the repo by default."""
    os.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Database + accounts
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path) -> Database:
    """A fresh, isolated SQLite Database (WAL + atomic tx) wired to a temp DB file."""
    database = Database(tmp_path / "test.db")
    database.init_schema()
    yield database
    database.close()


@pytest.fixture
def accounts(db: Database) -> dict[str, str]:
    """Create N enabled accounts and return {name: id}."""
    db.create_account(
        "acc_alpha", "Alpha", "tech videos",
        sources=["https://www.youtube.com/@handle1"],
        max_daily_clips=3, enabled=1,
    )
    db.create_account(
        "acc_beta", "Beta Gaming", "gaming highlights",
        sources=["https://www.youtube.com/@handle2"],
        max_daily_clips=4, enabled=1,
    )
    db.create_account(
        "acc_gamma", "Gamma Cooking", "recipes",
        sources=["https://www.youtube.com/@handle3"],
        max_daily_clips=2, enabled=1,
    )
    # One disabled account that must never be scheduled.
    db.create_account(
        "acc_off", "Offline Sports", "sports",
        sources=[], max_daily_clips=5, enabled=0,
    )
    return {"alpha": "acc_alpha", "beta": "acc_beta", "gamma": "acc_gamma", "off": "acc_off"}


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_transcript_json() -> str:
    """A canned Whisper verbose_json response (word + segment timestamps)."""
    import json
    return json.dumps({
        "text": "Hello world this is a sample clip.",
        "language": "en",
        "duration": 4.0,
        "segments": [
            {
                "id": 0, "start": 0.0, "end": 4.0,
                "text": "Hello world this is a sample clip.",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.5},
                    {"word": "world", "start": 0.5, "end": 1.0},
                ],
            }
        ],
        "words": [
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ],
    })


# ---------------------------------------------------------------------------
# Media synthesis + ffprobe helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def make_sample_video(tmp_path: Path, ffmpeg_path, ffprobe_path) -> Path:
    """
    Synthesize a tiny 16:9 1280x720 MP4 using testsrc + sine audio iff both
    binaries exist. Returns the file path (its parent dir is a pytest tmp dir).
    """
    if not (ffmpeg_path and ffprobe_path):
        pytest.skip("ffmpeg/ffprobe not available; skipping media integration test")
    out = tmp_path / "sample_16x9.mp4"
    cmd = [
        ffmpeg_path, "-y", "-f", "lavfi",
        "-i", "testsrc=size=1280x720:rate=24:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(out),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return out


def ffprobe_resolution(ffprobe_path: str, video_path: Path) -> tuple[int, int]:
    """Return (width, height) of a video file via ffprobe, or (0,0) on failure."""
    cmd = [
        ffprobe_path, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0",
        str(video_path),
    ]
    try:
        out = subprocess.check_output(cmd, text=True).strip()
        parts = out.split(",")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except subprocess.CalledProcessError:
        pass
    return 0, 0