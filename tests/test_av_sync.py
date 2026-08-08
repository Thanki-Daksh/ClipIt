"""
tests/test_av_sync.py - TSK-A06-10: audio-visual sync verification.

Renders a real vertical clip through the production VideoClipper and proves
the A/V streams stay aligned: the audio container duration must match the
video duration within a small tolerance (drift would show up as a growing
delta). Burning subtitles uses `-c:a copy`, so a captioned clip must keep
the audio perfectly aligned too.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from . import media_qa

MAX_SYNC_DELTA = 0.35  # seconds; MP4 edit lists pad slightly (muxing jitter)


def _synth_source(ffmpeg_path: str, out: Path, duration: int = 8) -> Path:
    subprocess.run(
        [ffmpeg_path, "-y",
         "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=24:duration={duration}",
         "-f", "lavfi", "-i", f"sine=frequency=660:duration={duration}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return out


def _stream_deltas(ffprobe_path: str, media: Path) -> dict:
    streams = media_qa.probe_streams(ffprobe_path, media)
    by_type: dict[str, dict] = {s["codec_type"]: s for s in streams}
    assert "video" in by_type and "audio" in by_type, f"missing stream in {media}"
    v, a = by_type["video"], by_type["audio"]
    return {
        "v_dur": float(v["duration"]),
        "a_dur": float(a["duration"]),
        "delta": abs(float(v["duration"]) - float(a["duration"])),
    }


@pytest.mark.ffprobe
def test_rendered_clip_audio_matches_video_duration(
        ffmpeg_path, ffprobe_path, tmp_path):
    if not (ffmpeg_path and ffprobe_path):
        pytest.skip("ffmpeg/ffprobe required")

    from modules.clipper import VideoClipper

    src = _synth_source(ffmpeg_path, tmp_path / "src.mp4")
    clip = tmp_path / "clip.mp4"
    VideoClipper(ffmpeg=ffmpeg_path, ffprobe=ffprobe_path).cut_clip(
        raw_video=str(src), start_time=0.0, end_time=5.5, output_path=str(clip))

    d = _stream_deltas(ffprobe_path, clip)
    assert d["delta"] <= MAX_SYNC_DELTA, (
        f"audio {d['a_dur']:.2f}s vs video {d['v_dur']:.2f}s — drift {d['delta']:.2f}s"
    )


@pytest.mark.ffprobe
def test_captioned_clip_keeps_audio_aligned(
        ffmpeg_path, ffprobe_path, tmp_path):
    """Burning subtitles must not shift audio (it is stream-copied)."""
    if not (ffmpeg_path and ffprobe_path):
        pytest.skip("ffmpeg/ffprobe required")

    from modules.captioner import ASSSubtitleGenerator, SubtitleRenderer
    from modules.clipper import VideoClipper

    src = _synth_source(ffmpeg_path, tmp_path / "src.mp4")
    clip = tmp_path / "clip.mp4"
    VideoClipper(ffmpeg=ffmpeg_path, ffprobe=ffprobe_path).cut_clip(
        raw_video=str(src), start_time=0.0, end_time=5.5, output_path=str(clip))

    ass = tmp_path / "cap.ass"
    ASSSubtitleGenerator().generate_ass(
        [{"word": "hello", "start": 0.0, "end": 0.6}], str(ass))
    final = tmp_path / "final.mp4"
    SubtitleRenderer(ffmpeg=ffmpeg_path, ffprobe=ffprobe_path).burn_subtitles(
        str(clip), str(ass), str(final))

    after = _stream_deltas(ffprobe_path, Path(final))
    assert after["delta"] <= MAX_SYNC_DELTA, (
        f"post-caption drift: audio {after['a_dur']:.2f}s vs video {after['v_dur']:.2f}s"
    )


@pytest.mark.ffprobe
def test_no_audio_drift_after_reencode(
        ffmpeg_path, ffprobe_path, tmp_path):
    """Even a full re-encode (loudnorm) keeps v/a within the same tolerance."""
    if not (ffmpeg_path and ffprobe_path):
        pytest.skip("ffmpeg/ffprobe required")

    from modules.clipper import VideoClipper

    src = _synth_source(ffmpeg_path, tmp_path / "src.mp4")
    clip = tmp_path / "clip.mp4"
    VideoClipper(ffmpeg=ffmpeg_path, ffprobe=ffprobe_path).cut_clip(
        raw_video=str(src), start_time=0.0, end_time=5.5,
        output_path=str(clip), audio_loudnorm=True)

    d = _stream_deltas(ffprobe_path, clip)
    assert d["delta"] <= MAX_SYNC_DELTA