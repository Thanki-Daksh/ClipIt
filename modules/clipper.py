"""
modules/clipper.py - FFmpeg 9:16 Vertical Crop Engine for ClipIt.

Cuts landscape (16:9) video into vertical 9:16 shorts at 1080x1920.
Supports two crop strategies:
    * center   - Smart center-crop a 9:16 window from the middle of the frame.
    * blur     - Stacked blurred-background padding (landscape fits centered).

Owned by Agent 03 (Media & Graphics Engineer). Do not edit by other agents.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

from core.logger import get_logger

logger = get_logger("clipper")

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
MIN_CLIP_SECONDS = 5.0          # Reject clips shorter than 5s (spec edge case).
MIN_FREE_MB = 500                # Abort render if free disk < 500MB.


@dataclass
class ClipRenderResult:
    """Result of a successful vertical crop render."""
    raw_video: str
    output_path: str
    crop_mode: str
    duration: float
    start_time: float
    end_time: float
    width: int = TARGET_WIDTH
    height: int = TARGET_HEIGHT
    ffmpeg_cmd: list = field(default_factory=list)


class VideoClipper:
    """Landscape -> vertical (9:16) FFmpeg cutter with two crop modes."""

    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self._ensure_tools()

    def _ensure_tools(self) -> None:
        """Warn early if FFmpeg executables are not on PATH."""
        for tool in (self.ffmpeg, self.ffprobe):
            try:
                subprocess.run(
                    [tool, "-version"],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
            except (FileNotFoundError, subprocess.CalledProcessError):
                logger.error("Required binary not found on PATH: %s", tool)
                raise EnvironmentError(
                    "FFmpeg is required for clip rendering. Install ffmpeg and "
                    "ensure `ffmpeg`/`ffprobe` are on PATH."
                )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def cut_clip(
        self,
        raw_video: str,
        start_time: float,
        end_time: float,
        output_path: str,
        crop_mode: str = "center",
        codec: str = "libx264",
        preset: str = "fast",
        crf: int = 22,
        audio_bitrate: str = "192k",
    ) -> ClipRenderResult:
        """
        Cut a 9:16 vertical clip from a landscape source.

        Args:
            raw_video:  Path to source video file.
            start_time: Clip start (seconds).
            end_time:   Clip end (seconds).
            output_path: Destination .mp4 path.
            crop_mode:  'center' (default) or 'blur'.
            codec/preset/crf/audio_bitrate: FFmpeg encoding controls.

        Raises:
            ValueError:     If timestamps are invalid or clip < 5s.
            RuntimeError:   If FFmpeg fails or output resolution is off-spec.
        """
        self._validate_clip(raw_video, start_time, end_time, output_path)

        # Edge case: refuse to start if we cannot fit the render on disk.
        self._check_disk_space(output_path)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        if crop_mode == "blur":
            cmd = self._build_blur_command(
                raw_video, start_time, end_time, output_path,
                codec, preset, crf, audio_bitrate,
            )
        else:  # center (default)
            cmd = self._build_center_command(
                raw_video, start_time, end_time, output_path,
                codec, preset, crf, audio_bitrate,
            )

        logger.info(
            "Rendering 9:16 clip mode=%s start=%.2fs end=%.2fs -> %s",
            crop_mode, start_time, end_time, output_path,
        )
        self._run(cmd)

        # Verify resolution + duration before we claim success.
        width, height, duration = self._probe(output_path)
        if (width, height) != (TARGET_WIDTH, TARGET_HEIGHT):
            raise RuntimeError(
                f"Clip rendered at {width}x{height}, expected {TARGET_WIDTH}x{TARGET_HEIGHT}. "
                "Crop filter produced off-spec dimensions."
            )

        return ClipRenderResult(
            raw_video=raw_video,
            output_path=output_path,
            crop_mode=crop_mode,
            duration=duration,
            start_time=start_time,
            end_time=end_time,
            width=width,
            height=height,
            ffmpeg_cmd=cmd,
        )

    # ------------------------------------------------------------------ #
    # FFmpeg command builders
    # ------------------------------------------------------------------ #
    def _build_center_command(
        self, raw_video: str, start: float, end: float, output_path: str,
        codec: str, preset: str, crf: int, audio_bitrate: str,
    ) -> list:
        """
        Strategy A: Smart Center Crop.

        Crop a 9:16 window from the center of the frame, then scale it up to
        fill 1080x1920. Uses -avoid_negative_ts make_zero on output so audio
        does not drift when seeking.
        """
        return [
            self.ffmpeg, "-y",
            "-ss", f"{start:.3f}",
            "-i", raw_video,
            "-to", f"{end - start:.3f}",
            "-vf", f"crop=ih*(9/16):ih,scale={TARGET_WIDTH}:{TARGET_HEIGHT}",
            "-c:v", codec, "-preset", preset, "-crf", str(crf),
            "-c:a", "aac", "-b:a", audio_bitrate,
            "-pix_fmt", "yuv420p",
            "-avoid_negative_ts", "make_zero",
            "-t", f"{end - start:.3f}",
            output_path,
        ]

    def _build_blur_command(
        self, raw_video: str, start: float, end: float, output_path: str,
        codec: str, preset: str, crf: int, audio_bitrate: str,
    ) -> list:
        """
        Strategy B: Stacked blurred-background padding.

        Landscape source is blurred and scaled to fill 1080x1920 (background),
        then the original sharp frame is overlaid centered on top.
        """
        filter_complex = (
            "[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            "boxblur=25:5,crop={w}:{h}[bg];"
            "[0:v]scale=1080:-1[fg];"
            "[bg][fg]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2[v]"
        ).format(w=TARGET_WIDTH, h=TARGET_HEIGHT)

        return [
            self.ffmpeg, "-y",
            "-ss", f"{start:.3f}",
            "-i", raw_video,
            "-to", f"{end - start:.3f}",
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "0:a?",
            "-c:v", codec, "-preset", preset, "-crf", str(crf),
            "-c:a", "aac", "-b:a", audio_bitrate,
            "-avoid_negative_ts", "make_zero",
            "-t", f"{end - start:.3f}",
            output_path,
        ]

    # ------------------------------------------------------------------ #
    # Helpers & validation
    # ------------------------------------------------------------------ #
    def _validate_clip(self, raw_video: str, start: float, end: float, output_path: str) -> None:
        if not os.path.exists(raw_video):
            raise FileNotFoundError(f"Source video not found: {raw_video}")
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            raise ValueError(f"Timestamps must be numeric, got start={start!r} end={end!r}")
        if end <= start:
            raise ValueError(f"end_time ({end}) must be greater than start_time ({start}).")
        if end - start < MIN_CLIP_SECONDS:
            raise ValueError(
                f"Clip duration {end - start:.2f}s is below minimum {MIN_CLIP_SECONDS}s."
            )
        if os.path.abspath(raw_video) == os.path.abspath(output_path):
            raise ValueError("output_path must differ from the source video path.")

    def _check_disk_space(self, output_path: str) -> None:
        target_dir = os.path.dirname(os.path.abspath(output_path)) or os.getcwd()
        free = shutil.disk_usage(target_dir).free
        if free < MIN_FREE_MB * 1024 * 1024:
            raise OSError(
                f"Insufficient free disk space: {free / (1024*1024):.0f}MB available, "
                f"needs >= {MIN_FREE_MB}MB."
            )

    def _run(self, cmd: list) -> str:
        """Execute FFmpeg non-blocking; surface stderr on failure."""
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace")
            logger.error("FFmpeg failed for %s\n%s", cmd[0], err)
            raise RuntimeError(f"FFmpeg render failed (exit {result.returncode}): {err}")
        return result.stdout.decode("utf-8", errors="replace")

    def _probe(self, video_path: str) -> tuple[int, int, float]:
        """Probe stream dimensions + duration via ffprobe."""
        cmd = [
            self.ffprobe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json",
            video_path,
        ]
        out = self._run(cmd)
        import json
        data = json.loads(out)
        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format") or {}
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))
        try:
            duration = float(fmt.get("duration", 0.0))
        except (TypeError, ValueError):
            duration = 0.0
        return width, height, duration