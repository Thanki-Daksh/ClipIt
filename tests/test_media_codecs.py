"""
tests/test_media_codecs.py - TSK-A06-04: FFmpeg render probe & sanity check.

Completes the render verification with CODEC-level assertions (the existing
suite already proved 9:16 resolution via ffprobe). A real clip rendered
through the production VideoClipper must be h264 video + AAC audio, and
burning subtitles onto it must preserve both codecs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from . import media_qa


def _stream_by_type(streams: list[dict], codec_type: str) -> dict | None:
    return next((s for s in streams if s.get("codec_type") == codec_type), None)


def synth_source(ffmpeg_path: str, out: Path, duration: int = 6) -> Path:
    """Real 16:9 testsrc+sine source (≥5s so VideoClipper can cut it)."""
    subprocess.run(
        [ffmpeg_path, "-y",
         "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=24:duration={duration}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return out


@pytest.mark.ffprobe
def test_rendered_clip_is_h264_with_aac(
        ffmpeg_path, ffprobe_path, tmp_path):
    if not (ffmpeg_path and ffprobe_path):
        pytest.skip("ffmpeg/ffprobe required")

    from modules.clipper import VideoClipper

    src = synth_source(ffmpeg_path, tmp_path / "src.mp4")
    clip = tmp_path / "vertical.mp4"
    result = VideoClipper(ffmpeg=ffmpeg_path, ffprobe=ffprobe_path).cut_clip(
        raw_video=str(src), start_time=0.0, end_time=5.5,
        output_path=str(clip))
    assert clip.exists() and result.output_path == str(clip)

    streams = media_qa.probe_streams(ffprobe_path, clip)
    video, audio = _stream_by_type(streams, "video"), _stream_by_type(streams, "audio")
    assert video is not None and audio is not None, f"missing streams in {clip}"
    assert video["codec_name"] == "h264", f"video codec={video.get('codec_name')}"
    assert (video["width"], video["height"]) == (1080, 1920)
    assert audio["codec_name"] == "aac", f"audio codec={audio.get('codec_name')}"


@pytest.mark.ffprobe
def test_burn_in_preserves_h264_and_aac(
        ffmpeg_path, ffprobe_path, tmp_path):
    """Captioned final clip keeps h264 video + aac audio (audio is copied)."""
    if not (ffmpeg_path and ffprobe_path):
        pytest.skip("ffmpeg/ffprobe required")

    from modules.captioner import ASSSubtitleGenerator, SubtitleRenderer
    from modules.clipper import VideoClipper

    src = synth_source(ffmpeg_path, tmp_path / "source.mp4")
    clip = tmp_path / "base.mp4"
    VideoClipper(ffmpeg=ffmpeg_path, ffprobe=ffprobe_path).cut_clip(
        raw_video=str(src), start_time=0.0, end_time=5.5, output_path=str(clip))

    ass = tmp_path / "cap.ass"
    ASSSubtitleGenerator().generate_ass(
        [{"word": "ok", "start": 0.0, "end": 0.5}], str(ass))
    final = tmp_path / "captioned.mp4"
    SubtitleRenderer(ffmpeg=ffmpeg_path, ffprobe=ffprobe_path).burn_subtitles(
        str(clip), str(ass), str(final))

    streams = media_qa.probe_streams(ffprobe_path, Path(final))
    video, audio = _stream_by_type(streams, "video"), _stream_by_type(streams, "audio")
    assert video["codec_name"] == "h264"
    assert audio["codec_name"] == "aac"
    assert (video["width"], video["height"]) == (1080, 1920)


@pytest.mark.ffprobe
def test_probe_streams_reports_durations(make_sample_video, ffprobe_path):
    if not ffprobe_path:
        pytest.skip("ffprobe required")
    streams = media_qa.probe_streams(ffprobe_path, make_sample_video)
    assert len(streams) >= 2  # video + audio
    for s in streams:
        assert float(s.get("duration", 0)) > 0.5  # ~2s synth clip