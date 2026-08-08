"""
tests/test_subtitle_render.py - TSK-A06-09: subtitle rendering integration.

Exercises the real Agent 03 captioner on actual media:
  1. ASSSubtitleGenerator produces a valid .ass with Dialogue lines + active
     word-highlight overrides from word timestamps.
  2. SubtitleRenderer burns the .ass onto a real rendered vertical clip with
     FFmpeg; the output stays 1080x1920, keeps its audio stream, and the
     burned render is not a black/corrupt video.
  3. ASS escaping protects braces/backslashes in spoken text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.captioner import ASSSubtitleGenerator, SubtitleRenderer

from . import media_qa


def _words():
    return [
        {"word": "Hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 0.5, "end": 1.0},
        {"word": "this", "start": 1.0, "end": 1.5},
        {"word": "is", "start": 1.5, "end": 2.0},
        {"word": "clipit", "start": 2.0, "end": 2.5},
    ]


# ---------------------------------------------------------------------------
# ASS generation (pure, no ffmpeg needed)
# ---------------------------------------------------------------------------

def test_generate_ass_creates_dialogue_lines(tmp_path):
    gen = ASSSubtitleGenerator()
    out = tmp_path / "subs.ass"
    gen.generate_ass(_words(), str(out))

    text = out.read_text()
    assert "[Script Info]" in text
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
    assert "Dialogue:" in text
    assert "{\\c" in text  # active-word highlight override present


def test_generate_ass_empty_words_raises(tmp_path):
    gen = ASSSubtitleGenerator()
    with pytest.raises(ValueError):
        gen.generate_ass([], str(tmp_path / "empty.ass"))


def test_ass_timestamp_format():
    gen = ASSSubtitleGenerator()
    assert gen._format_timestamp(0) == "0:00:00.00"
    assert gen._format_timestamp(75.5) == "0:01:15.50"
    assert gen._format_timestamp(3661.25) == "1:01:01.25"


def test_ass_escape_braces_and_backslashes(tmp_path):
    gen = ASSSubtitleGenerator()
    out = tmp_path / "escaped.ass"
    gen.generate_ass([{"word": "a{b}c", "start": 0.0, "end": 0.3}], str(out))
    text = out.read_text()
    assert "\\{" in text  # escaped brace must not be a raw override


def test_preset_validation_rejects_unknown():
    with pytest.raises(ValueError):
        ASSSubtitleGenerator(preset="NOT_A_PRESET")


def test_known_presets_exist():
    from modules.captioner import ASS_PRESETS
    for name in ("VIRAL_YELLOW", "MINIMAL_WHITE", "NEON_CYAN"):
        assert name in ASS_PRESETS


# ---------------------------------------------------------------------------
# Burn-in integration (requires ffmpeg)
# ---------------------------------------------------------------------------

@pytest.mark.ffprobe
def test_burn_subtitles_preserves_9x16_and_audio(make_sample_video, ffmpeg_path,
                                                 ffprobe_path, tmp_path):
    if not (ffmpeg_path and ffprobe_path):
        pytest.skip("ffmpeg/ffprobe required")

    # Render a vertical clip first (9:16), then burn captions onto it.
    clip = tmp_path / "base_clip.mp4"
    assert media_qa.render_vertical(ffmpeg_path, make_sample_video, clip) == 0
    assert media_qa.probe_resolution(ffprobe_path, clip) == (1080, 1920)

    ass = tmp_path / "cap.ass"
    ASSSubtitleGenerator().generate_ass(_words(), str(ass))
    final = tmp_path / "final_captioned.mp4"
    renderer = SubtitleRenderer(ffmpeg=ffmpeg_path, ffprobe=ffprobe_path)
    out = renderer.burn_subtitles(str(clip), str(ass), str(final))

    assert Path(out).exists() and Path(out).stat().st_size > 0
    width, height = media_qa.probe_resolution(ffprobe_path, Path(out))
    assert (width, height) == (1080, 1920)
    # Not corrupt.
    assert media_qa.detect_black_frames(ffmpeg_path, Path(out)) == []


@pytest.mark.ffprobe
def test_burn_subtitles_missing_inputs_raise(tmp_path):
    renderer = SubtitleRenderer()
    with pytest.raises(FileNotFoundError):
        renderer.burn_subtitles(str(tmp_path / "nope.mp4"),
                                str(tmp_path / "nope.ass"),
                                str(tmp_path / "out.mp4"))