"""
tests/test_clipper.py - FFmpeg 9:16 vertical crop render + ffprobe verification.

Simulates the Agent 03 "clipper" stage: takes a 16:9 source MP4, renders a
9:16 vertical clip at 1080x1920 (covering a phone-friendly Short/Reel/TikTok
canvas), then probes the output with ffprobe to assert resolution + aspect.

Real FFmpeg/ffprobe are used when available; otherwise the suite skips cleanly
so CI without a media toolchain does not fail.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Pure helper: the crop/scale filter string (unit-testable without media)
# ---------------------------------------------------------------------------

def build_vertical_crop_filter(
    target_width: int = 1080,
    target_height: int = 1920,
) -> str:
    """
    Produce an FFmpeg -vf string that scales a source to cover the 9:16 canvas
    (preserving aspect, overflowing as needed) then center-crops to exact size.

    `force_original_aspect_ratio=increase` (1) means "scale to fill" then crop
    the centre -> exact 9:16.
    """
    return (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
        f"crop={target_width}:{target_height}"
    )


def render_vertical_filter(target_width: int = 1080, target_height: int = 1920) -> str:
    """Alias kept for readability in callers."""
    return build_vertical_crop_filter(target_width, target_height)


def render_vertical_clip(
    ffmpeg_path: str,
    source: Path,
    output: Path,
    start: float = 0.0,
    duration: float = 1.0,
    width: int = 1080,
    height: int = 1920,
) -> int:
    """Render a 9:16 vertical clip from `source`. Returns ffmpeg return code."""
    filt = render_vertical_filter(width, height)
    cmd = [
        ffmpeg_path, "-y",
        "-ss", str(start), "-t", str(duration), "-i", str(source),
        "-vf", filt,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-an",
        str(output),
    ]
    return subprocess.run(cmd, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).returncode


# ---------------------------------------------------------------------------
# Unit tests (no media required)
# ---------------------------------------------------------------------------

def test_vertical_filter_requests_1080x1920():
    filt = render_vertical_filter()
    assert "1080:1920" in filt
    assert "crop=1080:1920" in filt
    assert "force_original_aspect_ratio=increase" in filt


def test_custom_canvas_filter():
    f = render_vertical_filter(target_width=720, target_height=1280)
    assert "crop=720:1280" in f


# ---------------------------------------------------------------------------
# Integration tests (require ffmpeg + ffprobe)
# ---------------------------------------------------------------------------

@pytest.mark.ffprobe
def test_render_9x16_output_is_1080x1920(
    make_sample_video, ffmpeg_path, ffprobe_path,
):
    from tests.conftest import ffprobe_resolution

    out = make_sample_video.parent / "clip_9x16.mp4"
    render = render_vertical_clip(ffmpeg_path, make_sample_video, out)
    assert render == 0, f"ffmpeg render failed with code {render}"
    assert out.exists()

    width, height = ffprobe_resolution(ffprobe_path, out)
    assert (width, height) == (1080, 1920), f"got {width}x{height}, want 1080x1920"


def test_render_output_is_nonempty_file(make_sample_video, ffmpeg_path):
    out = make_sample_video.parent / "clip_2.mp4"
    assert render_vertical_clip(ffmpeg_path, make_sample_video, out) == 0
    assert out.stat().st_size > 0