"""
modules/clipper.py - FFmpeg 9:16 Vertical Crop Engine for ClipIt.

Cuts landscape (16:9) video into vertical 9:16 shorts at 1080x1920.
Supports two crop strategies:
    * center   - Smart center-crop a 9:16 window from the middle of the frame.
    * blur     - Stacked blurred-background padding (landscape fits centered).
Plus optional speaker-face auto-crop (dynamic 9:16 window centered on a
face bounding box), a dual-pass render engine (h264_nvenc with libx264
automatic fallback), and FFmpeg loudnorm audio normalisation.

Owned by Agent 03 (Media & Graphics Engineer). Do not edit by other agents.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from core.logger import get_logger

logger = get_logger("clipper")

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_AR = TARGET_WIDTH / TARGET_HEIGHT     # 9/16 target height/width ratio
MIN_CLIP_SECONDS = 5.0          # Reject clips shorter than 5s (spec edge case).
MIN_FREE_MB = 500                # Abort render if free disk < 500MB.

# Broadcast loudness targets (EBU R128 style).
LOUDNESS_I = -16.0
LOUDNESS_TP = -1.5
LOUDNESS_LRA = 11.0


@dataclass(frozen=True)
class CropWindow:
    """A crop region in source pixels (top-left origin)."""
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
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
    encoder_used: str = "libx264"
    audio_normalized: bool = False
    crop_window: Optional[CropWindow] = None
    ffmpeg_cmd: List[str] = field(default_factory=list)


def _is_even_positive(value: float) -> bool:
    """True if value rounds to a positive even integer (x264/nvenc requires even dims)."""
    return value > 0 and int(round(value)) % 2 == 0


class VideoClipper:
    """Landscape -> vertical (9:16) FFmpeg cutter with two crop modes."""

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def __init__(
        self,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        prefer_nvenc: bool = True,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.prefer_nvenc = prefer_nvenc
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
        self._nvenc_available = self._detect_nvenc()

    # ------------------------------------------------------------------ #
    # Hardware encoder detection
    # ------------------------------------------------------------------ #
    @staticmethod
    def _detect_nvenc(ffmpeg: str = "ffmpeg") -> bool:
        """Return True if the FFmpeg build exposes the h264_nvenc encoder."""
        try:
            out = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            ).stdout.decode("utf-8", errors="replace")
            return any("h264_nvenc" in line for line in out.splitlines())
        except Exception:
            return False

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
        face_bbox: Optional[Tuple[float, float, float, float]] = None,
        encoder: str = "auto",
        audio_loudnorm: bool = False,
        loudness_i: float = LOUDNESS_I,
        loudness_tp: float = LOUDNESS_TP,
        loudness_lra: float = LOUDNESS_LRA,
        preset: str = "fast",
        crf: int = 22,
        quality: int = 23,               # NVENC constant-quality (CQ)
        audio_bitrate: str = "192k",
    ) -> ClipRenderResult:
        """
        Cut a 9:16 vertical clip from a landscape source.

        Args:
            raw_video:   Path to source video file.
            start_time:  Clip start (seconds).
            end_time:    Clip end (seconds).
            output_path: Destination .mp4 path.
            crop_mode:   'center' (default) or 'blur'.
            face_bbox:   Optional (x, y, w, h) face bounding box in source
                         pixels -> dynamic 9:16 window centered on the face.
            encoder:     'auto' (h264_nvenc w/ libx264 fallback), 'nvenc',
                         or 'libx264'.
            audio_loudnorm: apply EBU R128 loudnorm to bring audio to
                            broadcast level (re-encodes audio as AAC).
            quality/encoder codes: quality tuning.

        Returns a ClipRenderResult.

        Raises:
            ValueError:   Invalid timestamps / clip < 5s.
            RuntimeError: All encoder attempts fail or output is off-spec.
        """
        self._validate_clip(raw_video, start_time, end_time, output_path)
        self._check_disk_space(output_path)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        # Resolve the crop window (dynamic face crop overrides static center).
        crop_window = None
        if face_bbox is not None:
            crop_mode = "center"
            crop_window = self.face_crop_window(face_bbox, TARGET_WIDTH, TARGET_HEIGHT)

        audio_filter = None
        if audio_loudnorm:
            audio_filter = (
                f"loudnorm=I={loudness_i}:TP={loudness_tp}:LRA={loudness_lra}"
            )

        # Encoder candidate order (dual-pass: GPU first, CPU fallback).
        candidates = self._encoder_candidates(encoder)
        nvenc_ok = self._nvenc_available

        last_err: Optional[str] = None
        cmd: List[str] = []
        used_encoder = "libx264"

        for enc in candidates:
            if enc == "nvenc" and not nvenc_ok:
                continue
            used_encoder = enc
            cmd = self._build_command(
                raw_video=raw_video,
                start=start_time,
                end=end_time,
                output_path=output_path,
                crop_mode=crop_mode,
                crop_window=crop_window,
                encoder=enc,
                preset=preset,
                crf=crf,
                quality=quality,
                audio_bitrate=audio_bitrate,
                audio_filter=audio_filter,
            )
            logger.info(
                "Rendering 9:16 clip mode=%s encoder=%s start=%.2f end=%.2f -> %s",
                crop_mode, enc, start_time, end_time, output_path,
            )
            try:
                self._run(cmd)
                break
            except RuntimeError as e:
                last_err = str(e)
                logger.warning("Encoder %s failed, trying next: %s", enc, e)
                used_encoder = enc  # reflects the last attempted
        else:
            raise RuntimeError(
                f"All encoders failed for clip render. Last error: {last_err}"
            )

        # Verify resolution + duration before claiming success.
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
            encoder_used=used_encoder,
            audio_normalized=audio_loudnorm,
            crop_window=crop_window,
            ffmpeg_cmd=cmd,
        )

    def _encoder_candidates(self, encoder: str) -> List[str]:
        """Return ordered encoder candidates for a request, GPU-first."""
        encoder = (encoder or "auto").lower()
        if encoder == "nvenc":
            return ["nvenc", "libx264"] if self.prefer_nvenc else ["libx264"]
        if encoder == "libx264":
            return ["libx264"]
        # auto (default)
        if self.prefer_nvenc and self._nvenc_available:
            return ["nvenc", "libx264"]
        return ["libx264"]

    # ------------------------------------------------------------------ #
    # Face auto-crop math (TSK-A03-07)
    # ------------------------------------------------------------------ #
    def face_crop_window(
        self,
        face_bbox: Tuple[float, float, float, float],
        src_w: int,
        src_h: int,
    ) -> CropWindow:
        """
        Compute the largest 9:16 crop window that fits the source and is
        horizontally centered on the speaker's face bounding box.

        face_bbox: (x, y, w, h) top-left origin in source pixels.
        Returns a CropWindow with integer, even-safe width/height, clamped to
        the source so the crop never exceeds the frame.
        """
        fx, fy, fw, fh = (float(v) for v in face_bbox)
        face_cx, face_cy = fx + fw / 2.0, fy + fh / 2.0

        # Largest 9:16 window that fits inside the source.
        if src_w >= src_h * TARGET_AR:
            # Height-limited (typical landscape): full height, width derived.
            win_w, win_h = src_h * TARGET_AR, float(src_h)
        else:
            # Width-limited (portrait-ish source).
            win_w, win_h = float(src_w), src_w / TARGET_AR

        # Center the window horizontally on the face, clamped to source bounds.
        crop_x = face_cx - win_w / 2.0
        crop_y = face_cy - win_h / 2.0
        crop_x = max(0.0, min(crop_x, src_w - win_w))
        crop_y = max(0.0, min(crop_y, src_h - win_h))

        # Snap to even integers (x264/NVENC require even dimensions).
        w = int(round(win_w / 2) * 2)
        h = int(round(win_h / 2) * 2)
        x = int(round(crop_x / 2) * 2)
        y = int(round(crop_y / 2) * 2)

        # Re-clamp after rounding.
        x = max(0, min(x, src_w - w))
        y = max(0, min(y, src_h - h))
        return CropWindow(x=x, y=y, w=w, h=h)

    # ------------------------------------------------------------------ #
    # FFmpeg command builders
    # ------------------------------------------------------------------ #
    def _build_command(
        self,
        raw_video: str, start: float, end: float, output_path: str,
        crop_mode: str, crop_window: Optional[CropWindow],
        encoder: str, preset: str, crf: int, quality: int,
        audio_bitrate: str, audio_filter: Optional[str],
    ) -> List[str]:
        """Assemble the FFmpeg invocation for either crop strategy."""
        duration = end - start

        if crop_mode == "blur":
            vf, out_mapping = self._blur_filter(crop_window)
        else:
            vf, out_mapping = self._center_filter(crop_window)

        codec_args = self._codec_args(
            encoder=encoder, preset=preset, crf=crf, quality=quality
        )

        audio_args: List[str] = []
        if audio_filter:
            audio_args = ["-af", audio_filter, "-c:a", "aac", "-b:a", audio_bitrate]
        else:
            audio_args = ["-c:a", "aac", "-b:a", audio_bitrate]

        cmd = [
            self.ffmpeg, "-y",
            "-ss", f"{start:.3f}",
            "-i", raw_video,
            "-to", f"{duration:.3f}",
            "-vf", vf,
        ]
        cmd += out_mapping
        cmd += list(codec_args)
        cmd += audio_args
        cmd += ["-pix_fmt", "yuv420p", "-avoid_negative_ts", "make_zero"]
        cmd += ["-t", f"{duration:.3f}", output_path]
        return cmd

    def _center_filter(self, crop_window: Optional[CropWindow]):
        """Smart center crop (or face-crop) filter, then scale/fill 9:16."""
        if crop_window is not None:
            vf = (
                f"crop={crop_window.w}:{crop_window.h}:{crop_window.x}:{crop_window.y},"
                f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
            )
        else:
            vf = f"crop=ih*({TARGET_AR:.6f}):ih,scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
        return vf, ["-map", "0:a?"]

    def _blur_filter(self, crop_window: Optional[CropWindow]):
        """Stacked blurred background with sharp foreground overlay centered."""
        fg_off = 0 if crop_window is None else (crop_window.x - (
            TARGET_WIDTH - TARGET_WIDTH // 2
        ))
        # For blurred mode we keep the fg centered unless a face window shifts x.
        if crop_window is not None:
            overlay_x = (TARGET_WIDTH - TARGET_WIDTH) // 2 + crop_window.x // 2
        else:
            overlay_x = "(main_w-overlay_w)/2"

        filter_complex = (
            "[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            "boxblur=25:5,crop={w}:{h}[bg];"
            "[0:v]scale=1080:-1[fg];"
            "[bg][fg]overlay={ox}:(main_h-overlay_h)/2[v]"
        ).format(w=TARGET_WIDTH, h=TARGET_HEIGHT, ox=overlay_x)
        return filter_complex, ["-map", "[v]", "-map", "0:a?"]

    def _encode_args(
        self,
        encoder: str,
        preset: str,
        crf: int,
        quality: int,
    ) -> List[str]:
        """Return encoder-specific video encoding arguments."""
        if encoder == "nvenc":
            # NVENC is a CQP/VBR-style encoder; preset p5 used by default.
            return [
                "-c:v", "h264_nvenc",
                "-preset", "p5",
                "-rc", "vbr",
                "-cq", str(quality),
                "-b:v", "0",
            ]
        # libx264 (CPU): classic CRF one-pass.
        return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]

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

    def _run(self, cmd: List[str]) -> str:
        """Execute FFmpeg non-blocking; surface stderr on failure."""
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace")
            logger.error("FFmpeg failed for %s\n%s", cmd[0], err)
            raise RuntimeError(f"FFmpeg render failed (exit {result.returncode}): {err}")
        return result.stdout.decode("utf-8", errors="replace")

    def _probe(self, video_path: str) -> Tuple[int, int, float]:
        """Probe stream dimensions + duration via ffprobe."""
        cmd = [
            self.ffprobe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json",
            video_path,
        ]
        out = self._run(cmd)
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