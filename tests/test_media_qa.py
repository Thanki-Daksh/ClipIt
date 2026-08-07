"""
tests/test_media_qa.py - TSK-A06-06: Black-frame & silence probe tests.

Confirms the ffmpeg-based corruption probes (tests/media_qa.py) correctly flag
broken renders AND pass clean ones:
  - a good testsrc+sine clip has NO black frames and NO silence
  - a black-only color clip IS flagged as all-black frames
  - a silent audio clip IS flagged as silence
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from . import media_qa


def _synth_with_audio(tmp_path: Path, ffmpeg: str, name: str,
                      video_src: str, audio_src: str) -> Path:
    """Build a tiny synthetic AV clip. Returns its path."""
    out = tmp_path / name
    subprocess.run([
        ffmpeg, "-y",
        "-f", "lavfi", "-i", video_src,
        "-f", "lavfi", "-i", audio_src,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(out),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return out


@pytest.mark.media
def test_good_clip_has_no_black_frames(ffmpeg_path, tmp_path, make_sample_video):
    if not ffmpeg_path:
        pytest.skip("ffmpeg required")
    assert media_qa.detect_black_frames(ffmpeg_path,
                                        make_sample_video) == []


@pytest.mark.media
def test_black_video_is_flagged(ffmpeg_path, tmp_path):
    if not ffmpeg_path:
        pytest.skip("ffmpeg required")
    video = _synth_with_audio(
        tmp_path, ffmpeg_path, "black.mp4",
        video_src="color=black:size=320x240:rate=10:duration=1",
        audio_src="sine=frequency=440:duration=1",
    )
    black = media_qa.detect_black_frames(ffmpeg_path, video)
    assert len(black) > 0, "a fully black video must be flagged"


@pytest.mark.media
def test_good_clip_has_no_silence(ffmpeg_path, tmp_path, make_sample_video):
    if not ffmpeg_path:
        pytest.skip("ffmpeg required")
    assert media_qa.detect_silence(ffmpeg_path, make_sample_video) == []


@pytest.mark.media
def test_silent_audio_is_flagged(ffmpeg_path, tmp_path):
    if not ffmpeg_path:
        pytest.skip("ffmpeg required")
    silent = _synth_with_audio(
        tmp_path, ffmpeg_path, "silent.mp4",
        video_src="testsrc=size=320x240:rate=10:duration=1",
        audio_src="anullsrc=r=44100:cl=stereo",
    )
    silence = media_qa.detect_silence(ffmpeg_path, silent)
    assert len(silence) > 0, "expected a silent clip to be flagged"


@pytest.mark.media
def test_resolution_probe_reports_good_dimensions(ffprobe_path, make_sample_video):
    if not ffprobe_path:
        pytest.skip("ffprobe required")
    assert media_qa.probe_resolution(ffprobe_path, make_sample_video) == (1280, 720)