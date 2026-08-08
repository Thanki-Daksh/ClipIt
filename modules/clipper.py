"""
modules/clipper.py - FFmpeg 9:16 Vertical Crop Engine for ClipIt.

Cuts landscape (16:9) video into vertical 9:16 shorts at 1080x1920.
Supports four crop/layout strategies:
    * center   - Smart center-crop a 9:16 window from the middle of the frame.
    * blur     - Stacked blurred-background padding (landscape fits centered).
    * pad      - Auto-pad to 9:16 without stretching (TSK-A03-14).
Plus optional speaker-face auto-crop (dynamic 9:16 window centered on a
face bounding box), a dual-pass render engine (h264_nvenc with libx264
automatic fallback), FFmpeg loudnorm audio normalisation (-14 LUFS mobile
spec), dynamic bottom-right watermark overlay, auto color-grading presets,
a minterpolate 60fps motion-blur doubler, 1080x1920 poster-frame thumbnail
extraction, and a 120s hard timeout guard on every FFmpeg process.

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
RENDER_TIMEOUT = 120             # TSK-A03-15: hard cap on every FFmpeg render process.
WATERMARK_MARGIN = 36            # Bottom-right logo inset (px) for TSK-A03-08.

# Broadcast loudness targets (EBU R128 style) - mobile-speaker friendly.
LOUDNESS_I = -14.0               # TSK-A03-09: -14 LUFS integrated for mobile.
LOUDNESS_TP = -1.5
LOUDNESS_LRA = 11.0

# Auto color-grading presets (TSK-A03-13) - mobile-display friendly.
COLOR_PRESETS = {
    "vivid": "eq=contrast=1.12:saturation=1.28:brightness=0.01",
    "punch": "eq=contrast=1.18:saturation=1.4:brightness=0.015",
    "cinematic": "eq=contrast=1.06:saturation=0.92:gamma=0.96",
    "warm": "eq=contrast=1.08:saturation=1.12:gamma=1.02:colorbalance=rs=0.04:bs=-0.03",
}


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
        timeout: int = RENDER_TIMEOUT,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.prefer_nvenc = prefer_nvenc
        self.timeout = timeout          # TSK-A03-15: 120s render cap.
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
        """
        Return True if FFmpeg can actually USE the h264_nvenc encoder.

        Merely being present in `ffmpeg -encoders` is not enough - the NVIDIA
        driver runtime (nvcuda.dll) may be missing on the host. We probe by
        attempting a tiny 1-frame h264_nvenc encode; if the driver cannot be
        loaded this fails fast and we correctly fall back to libx264.
        """
        try:
            enc_out = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            if not any(b"h264_nvenc" in line for line in enc_out.stdout.splitlines()):
                return False
            # Functional probe: 60x40, 1 frame, null muxer.
            probe = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=black:s=60x40:d=0.03",
                 "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=20,
            )
            return probe.returncode == 0
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
        crf: int = 23,
        quality: int = 23,               # NVENC constant-quality (CQ)
        audio_bitrate: str = "192k",
        watermark_path: Optional[str] = None,
        watermark_scale: float = 0.12,
        smooth_60fps: bool = False,
        minterpolate_mode: str = "mci",
        color_grade: Optional[str] = None,
    ) -> ClipRenderResult:
        """
        Cut a 9:16 vertical clip from a landscape source.

        Args:
            raw_video:   Path to source video file.
            start_time:  Clip start (seconds).
            end_time:    Clip end (seconds).
            output_path: Destination .mp4 path.
            crop_mode:   'center' (default), 'blur', or 'pad' (auto-pad
                         9:16 without stretching, TSK-A03-14).
            face_bbox:   Optional (x, y, w, h) face bounding box in source
                         pixels -> dynamic 9:16 window centered on the face.
            encoder:     'auto' (h264_nvenc w/ libx264 fallback), 'nvenc',
                         or 'libx264'.
            audio_loudnorm: apply EBU R128 loudnorm (default target -14 LUFS,
                            mobile-speaker spec, TSK-A03-09).
            watermark_path: optional logo image -> burned bottom-right
                            (TSK-A03-08 dynamic watermark overlay).
            watermark_scale: logo width as a fraction of 1080 (default 0.12).
            smooth_60fps:    enable minterpolate motion blur + 60fps doubler
                             (TSK-A03-12).
            minterpolate_mode: 'mci' (motion-compensated, slow HQ) or
                               'blend' (fast). Default 'mci'.
            color_grade:   optional grading preset name (TSK-A03-13):
                           'vivid', 'punch', 'cinematic', 'warm'.

        Returns a ClipRenderResult.

        Raises:
            ValueError:   Invalid timestamps / clip < 5s.
            RuntimeError: All encoder attempts fail, output is off-spec,
                          or a render exceeds the timeout guard (TSK-A03-15).
        """
        self._validate_clip(raw_video, start_time, end_time, output_path)
        self._check_disk_space(output_path)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        # Resolve the crop window (dynamic face crop overrides static center).
        crop_window = None
        if face_bbox is not None:
            crop_mode = "center"
            src_w, src_h, _ = self._probe_dimensions(raw_video)
            crop_window = self.face_crop_window(face_bbox, src_w, src_h)

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
                watermark_path=watermark_path,
                watermark_scale=watermark_scale,
                smooth_60fps=smooth_60fps,
                color_grade=color_grade,
                minterpolate_mode=minterpolate_mode,
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

    def extract_thumbnail(
        self,
        video_path: str,
        output_png: str,
        at_time: float = 1.0,
    ) -> str:
        """
        TSK-A03-10: extract a 1080x1920 poster-frame PNG thumbnail.

        The frame is scaled with force_original_aspect_ratio=increase and
        center-cropped so the poster is always exactly 1080x1920 regardless
        of the clip's content AR.

        Returns the output PNG path.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found for thumbnail: {video_path}")
        os.makedirs(os.path.dirname(os.path.abspath(output_png)) or ".", exist_ok=True)

        cmd = [
            self.ffmpeg, "-y",
            "-ss", f"{max(0.0, float(at_time)):.3f}",
            "-i", video_path,
            "-vf",
            f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_WIDTH}:{TARGET_HEIGHT}",
            "-frames:v", "1",
            "-q:v", "2",
            output_png,
        ]
        self._run(cmd)

        w, h, _ = self._probe(output_png)
        if (w, h) != (TARGET_WIDTH, TARGET_HEIGHT):
            raise RuntimeError(
                f"Thumbnail rendered at {w}x{h}, expected "
                f"{TARGET_WIDTH}x{TARGET_HEIGHT}."
            )
        logger.info("Extracted thumbnail (1080x1920): %s", output_png)
        return output_png

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
        watermark_path: Optional[str] = None,
        watermark_scale: float = 0.12,
        smooth_60fps: bool = False,
        color_grade: Optional[str] = None,
        minterpolate_mode: str = "mci",
    ) -> List[str]:
        """Assemble the FFmpeg invocation for the requested render.

        Crop strategies: 'center'/'face' (smart crop), 'blur' (stacked
        blurred background), 'pad' (auto-pad 9:16 without stretching,
        TSK-A03-14). Optional chained extras: color grading (TSK-A03-13),
        minterpolate 60fps motion-blur doubler (TSK-A03-12), and a
        bottom-right watermark overlay (TSK-A03-08).
        """
        duration = end - start
        has_watermark = bool(watermark_path)

        cmd = [
            self.ffmpeg, "-y",
            "-ss", f"{start:.3f}",
            "-i", raw_video,
        ]
        if has_watermark:
            if not os.path.exists(watermark_path):
                raise FileNotFoundError(f"Watermark image not found: {watermark_path}")
            cmd += ["-i", watermark_path]
        cmd += ["-to", f"{duration:.3f}"]

        # 1) Main video chain: (filter, in_labels, out_label) segments.
        segs: List[Tuple[str, str, str]] = []
        if crop_mode == "blur":
            segs.append((
                f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
                f"boxblur=25:5,crop={TARGET_WIDTH}:{TARGET_HEIGHT}",
                "[0:v]", "[bg]",
            ))
            segs.append(("scale=1080:-1", "[0:v]", "[fg]"))
            segs.append(("overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2", "[bg][fg]", "[vmain]"))
        elif crop_mode == "pad":
            # TSK-A03-14: fit inside 1080x1920, then pad to exact 9:16 - no stretching.
            segs.append((
                f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black",
                "[0:v]", "[vmain]",
            ))
        else:
            if crop_window is not None:
                crop = (
                    f"crop={crop_window.w}:{crop_window.h}:{crop_window.x}:{crop_window.y},"
                    f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
                )
            else:
                crop = f"crop=ih*({TARGET_AR:.6f}):ih,scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
            segs.append((crop, "[0:v]", "[vmain]"))

        # 2) Optional color grading (TSK-A03-13) + 60fps doubler (TSK-A03-12).
        extra: List[str] = []
        grade_filter = None
        if color_grade:
            grade_filter = COLOR_PRESETS.get(str(color_grade).strip().lower())
            if grade_filter is None:
                raise ValueError(
                    f"Unknown color grade '{color_grade}'. "
                    f"Available: {', '.join(sorted(COLOR_PRESETS))}"
                )
            extra.append(grade_filter)
        if smooth_60fps:
            extra.append(f"minterpolate=fps=60:mi_mode={minterpolate_mode}")
        if extra:
            segs.append((",".join(extra), "[vmain]", "[vgraded]"))
            video_in = "[vgraded]"
        else:
            video_in = "[vmain]"

        # 3) Watermark overlay, bottom-right corner (TSK-A03-08).
        out_label = video_in
        if has_watermark:
            logo_w = max(24, int(TARGET_WIDTH * watermark_scale))
            segs.append((f"scale={logo_w}:-1", "[1:v]", "[logo]"))
            segs.append((
                f"overlay=main_w-overlay_w-{WATERMARK_MARGIN}:main_h-overlay_h-{WATERMARK_MARGIN}",
                f"{video_in}[logo]", "[vout]",
            ))
            out_label = "[vout]"

        is_complex = crop_mode == "blur" or has_watermark or len(segs) > 1
        if is_complex:
            vf = ";".join(f"{in_l}{filt}{out_l}" for filt, in_l, out_l in segs)
            cmd += ["-filter_complex", vf]
            cmd += ["-map", out_label, "-map", "0:a?"]
        else:
            # Single plain chain - simple -vf (keeps legacy command shape).
            cmd += ["-vf", segs[0][0]]
            # No explicit video -map: default mapping keeps the filtered
            # video plus all audio. (Do NOT add `-map 0:a?` here - it would
            # drop video.)

        codec_args = self._codec_args(
            encoder=encoder, preset=preset, crf=crf, quality=quality
        )
        audio_args: List[str] = []
        if audio_filter:
            audio_args = ["-af", audio_filter, "-c:a", "aac", "-b:a", audio_bitrate]
        else:
            audio_args = ["-c:a", "aac", "-b:a", audio_bitrate]

        cmd += list(codec_args)
        cmd += audio_args
        cmd += ["-pix_fmt", "yuv420p", "-avoid_negative_ts", "make_zero"]
        cmd += [output_path]
        return cmd

    def _codec_args(
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

    def _probe_dimensions(self, video_path: str) -> Tuple[int, int, float]:
        """Alias for _probe: probe stream dimensions + duration."""
        return self._probe(video_path)

    def _run(self, cmd: List[str]) -> str:
        """Execute FFmpeg non-blocking; surface stderr on failure.

        TSK-A03-15: every FFmpeg process runs under a hard timeout cap
        (default 120s). A hung filter graph kills the render fast instead
        of wedging the worker.
        """
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False, timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            logger.error("FFmpeg render exceeded %ds timeout: %s", self.timeout, cmd[0])
            raise RuntimeError(
                f"FFmpeg render timed out after {self.timeout}s (TSK-A03-15 guard). "
                f"Command: {os.path.basename(cmd[0])} ..."
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