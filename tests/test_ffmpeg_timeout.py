"""
tests/test_ffmpeg_timeout.py - TSK-A06-09: FFmpeg timeout hardening.

A hung FFmpeg subprocess must be terminated cleanly after the configured
timeout instead of wedging the worker forever. Uses a FAKE ffmpeg (a tiny
.bat that pretends to be ffmpeg then sleeps) so failure is deterministic:
the fake answers finder probes instantly and hangs on any real render.

Production behaviour under test:
  * VideoClipper(timeout=N) -> cut_clip() raises RuntimeError on a hung
    render and the child is gone.
  * SubtitleRenderer().burn_subtitles(..., timeout=N) kills a hung burn.
"""

from __future__ import annotations

import os
import textwrap
import time
from pathlib import Path

import pytest

FAKE_FFMPEG_BAT = textwrap.dedent(
    """\
    @echo off
    echo %*| findstr /C:"-version" >nul && exit /b 0
    echo %*| findstr /C:"-encoders" >nul && exit /b 0
    echo %*| findstr /C:"-f null" >nul && exit /b 0
    if defined HANG_MARKER echo started> "%HANG_MARKER%"
    timeout /t 60 /nobreak >nul
    exit /b 0
    """
)


@pytest.fixture
def fake_hang_ffmpeg(tmp_path: Path) -> tuple[str, Path]:
    """A fake ffmpeg that hangs on real work; returns (binary, marker)."""
    binary = tmp_path / "fake_ffmpeg.bat"
    marker = tmp_path / "hang_marker.txt"
    binary.write_text(FAKE_FFMPEG_BAT, encoding="utf-8")
    return str(binary), marker


def _synth_source(ffmpeg_path: str, out: Path) -> Path:
    import subprocess
    subprocess.run(
        [ffmpeg_path, "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return out


def test_render_timeout_kills_fake_ffmpeg(
        fake_hang_ffmpeg, ffmpeg_path, ffprobe_path, tmp_path, monkeypatch):
    binary, marker = fake_hang_ffmpeg
    if not (ffmpeg_path and ffprobe_path):
        pytest.skip("ffmpeg/ffprobe required")
    monkeypatch.setenv("HANG_MARKER", str(marker))

    from modules.clipper import VideoClipper

    src = _synth_source(ffmpeg_path, tmp_path / "src.mp4")
    clipper = VideoClipper(ffmpeg=binary, ffprobe=ffprobe_path, timeout=1)

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="(?i)timed out|timeout"):
        clipper.cut_clip(
            raw_video=str(src), start_time=0.0, end_time=5.5,
            output_path=str(tmp_path / "out.mp4"),
        )
    assert marker.exists(), "hung ffmpeg was never started"
    assert time.monotonic() - started < 5  # bounded, not a 60s hang


def test_burn_timeout_kills_fake_ffmpeg(
        fake_hang_ffmpeg, ffmpeg_path, ffprobe_path, tmp_path, monkeypatch):
    binary, marker = fake_hang_ffmpeg
    if not (ffmpeg_path and ffprobe_path):
        pytest.skip("ffmpeg/ffprobe required")
    monkeypatch.setenv("HANG_MARKER", str(marker))

    from modules.captioner import ASSSubtitleGenerator, SubtitleRenderer

    src = _synth_source(ffmpeg_path, tmp_path / "clip.mp4")
    ass = tmp_path / "cap.ass"
    ASSSubtitleGenerator().generate_ass(
        [{"word": "x", "start": 0.0, "end": 0.4}], str(ass))

    renderer = SubtitleRenderer(ffmpeg=binary, ffprobe=ffprobe_path)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="(?i)timed out|timeout"):
        renderer.burn_subtitles(str(src), str(ass),
                                str(tmp_path / "final.mp4"), timeout=1)
    assert marker.exists(), "burn process was never started"
    assert time.monotonic() - started < 5


def test_default_render_timeout_guard_constant():
    """The production default render cap must exist and be sane (>=30s)."""
    from modules.clipper import RENDER_TIMEOUT
    assert RENDER_TIMEOUT >= 30